"""Tests for engine/trades/convert.py (ConversionPipeline).

Every test runs against a REAL sqlite database in a tmp_path, so INSERT /
INSERT OR REPLACE semantics, the lock/idempotency behaviour and the aggregate
queries are genuinely exercised rather than mocked.

Note: ConversionPipeline.__init__ calls Database.set_db_file(), which is a
process-global class attribute. A fixture restores the previous value so these
tests cannot leak a tmp database into the rest of the suite.
"""
import sqlite3

import pytest

from engine.database import Database
from engine.trades.base import TradeLead
from engine.trades.convert import ConversionPipeline


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    """Initialize the schema ONCE per session.

    Creating a brand-new sqlite file on this Windows box costs ~2.7s (34
    CREATE statements, dominated by filesystem/AV), while re-initializing an
    existing file is ~4ms. Copying a pre-built template per test keeps the
    schema identical while cutting ~2.5 min off the run.
    """
    saved = Database.db_file
    src = tmp_path_factory.mktemp("template") / "lead_gen.db"
    Database.db_file = str(src)
    Database.initialize()
    Database.db_file = saved
    return src


@pytest.fixture
def pipeline(tmp_path, _db_template):
    saved = Database.db_file
    dest = tmp_path / "lead_gen.db"
    dest.write_bytes(_db_template.read_bytes())
    p = ConversionPipeline(data_dir=str(tmp_path))
    try:
        yield p
    finally:
        Database.db_file = saved


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pin `engine.trades.convert.datetime` so payment_id's second-resolution
    timestamp is deterministic instead of racing the wall clock."""
    import datetime as real

    class Frozen(real.datetime):
        current = real.datetime(2026, 9, 27, 12, 0, 0)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr("engine.trades.convert.datetime", Frozen)
    return Frozen


def lead(**kw):
    kw.setdefault("business_name", "Ace Plumbing")
    kw.setdefault("trade", "plumbing")
    return TradeLead(**kw)


def rows(db_path, table):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]


# ── construction ───────────────────────────────────────────────────────────
def test_constructor_creates_the_database_and_its_tables(pipeline, tmp_path):
    db = tmp_path / "lead_gen.db"
    assert db.exists()
    with sqlite3.connect(db) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"trade_accounts", "trade_payments"} <= names, names


def test_constructor_creates_a_missing_data_directory(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    saved = Database.db_file
    try:
        ConversionPipeline(data_dir=str(nested))
        assert (nested / "lead_gen.db").exists()
    finally:
        Database.db_file = saved


def test_constructor_is_idempotent_on_an_existing_database(tmp_path):
    saved = Database.db_file
    try:
        ConversionPipeline(data_dir=str(tmp_path))
        p2 = ConversionPipeline(data_dir=str(tmp_path))  # must not raise
        assert p2.get_accounts() == []
    finally:
        Database.db_file = saved


# ── plan fees ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("plan,fee", [
    ("starter", 97), ("growth", 197), ("pro", 497), ("enterprise", 997),
])
def test_known_plan_fees(pipeline, plan, fee):
    assert pipeline._plan_fee(plan) == fee


@pytest.mark.parametrize("plan", ["", "free", "START", "premium", "none"])
def test_unknown_plan_falls_back_to_starter(pipeline, plan):
    assert pipeline._plan_fee(plan) == 97


# ── convert_to_account ─────────────────────────────────────────────────────
async def test_convert_to_account_returns_the_account_shape(pipeline):
    account = await pipeline.convert_to_account(lead(phone="555", email="a@b.com"), plan="pro")
    assert account["plan"] == "pro"
    assert account["monthly_fee"] == 497
    assert account["status"] == "active"
    assert account["leads_generated"] == 0
    assert account["conversions"] == 0
    assert account["business_name"] == "Ace Plumbing"
    assert account["phone"] == "555"
    assert account["email"] == "a@b.com"
    assert account["created_at"]


async def test_convert_to_account_id_is_derived_from_the_lead(pipeline):
    ld = lead()
    account = await pipeline.convert_to_account(ld)
    assert account["account_id"] == f"acc_{ld.id}"
    assert account["lead_id"] == ld.id


async def test_convert_to_account_mutates_the_lead(pipeline):
    ld = lead()
    assert ld.converted is False and ld.status == "new"
    account = await pipeline.convert_to_account(ld)
    assert ld.converted is True
    assert ld.status == "converted"
    assert ld.account_id == account["account_id"]


async def test_convert_to_account_persists_the_row(pipeline, tmp_path):
    ld = lead(address="1 Main St", website="http://ace.com", source="yelp")
    await pipeline.convert_to_account(ld, plan="growth")
    stored = rows(tmp_path / "lead_gen.db", "trade_accounts")
    assert len(stored) == 1
    row = stored[0]
    assert row["account_id"] == f"acc_{ld.id}"
    assert row["lead_id"] == ld.id
    assert row["business_name"] == "Ace Plumbing"
    assert row["address"] == "1 Main St"
    assert row["website"] == "http://ace.com"
    assert row["source"] == "yelp"
    assert row["trade"] == "plumbing"
    assert row["plan"] == "growth"
    assert row["monthly_fee"] == 197
    assert row["status"] == "active"
    assert row["leads_generated"] == 0
    assert row["conversions"] == 0


async def test_convert_to_account_defaults_to_starter(pipeline):
    assert (await pipeline.convert_to_account(lead()))["monthly_fee"] == 97


async def test_converting_the_same_lead_twice_replaces_rather_than_duplicates(pipeline, tmp_path):
    ld = lead()
    await pipeline.convert_to_account(ld, plan="starter")
    await pipeline.convert_to_account(ld, plan="enterprise")
    stored = rows(tmp_path / "lead_gen.db", "trade_accounts")
    assert len(stored) == 1, "INSERT OR REPLACE on a PK account_id must not duplicate"
    assert stored[0]["plan"] == "enterprise"
    assert stored[0]["monthly_fee"] == 997


async def test_distinct_leads_produce_distinct_accounts(pipeline):
    a = await pipeline.convert_to_account(lead(business_name="A"))
    b = await pipeline.convert_to_account(lead(business_name="B"))
    assert a["account_id"] != b["account_id"]
    assert len(pipeline.get_accounts()) == 2


async def test_conversion_survives_a_database_failure(pipeline, monkeypatch, caplog):
    """A dead DB must not lose the lead: the account is still returned and the
    lead is still marked converted."""
    def boom():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Database, "get_connection", staticmethod(boom))
    ld = lead()
    with caplog.at_level("ERROR", logger="engine.trades.convert"):
        account = await pipeline.convert_to_account(ld)
    assert account["account_id"] == f"acc_{ld.id}"
    assert ld.converted is True and ld.status == "converted"
    assert any("Failed to save trade account" in r.message for r in caplog.records), caplog.records


async def test_conversion_failure_is_logged_not_raised(pipeline, monkeypatch):
    monkeypatch.setattr(Database, "get_connection",
                        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("nope"))))
    assert (await pipeline.convert_to_account(lead()))["status"] == "active"


async def test_get_accounts_reflects_a_failed_conversion(pipeline, monkeypatch):
    monkeypatch.setattr(Database, "get_connection",
                        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("nope"))))
    await pipeline.convert_to_account(lead())
    assert pipeline.get_accounts() == []


# ── record_payment ─────────────────────────────────────────────────────────
async def test_record_payment_returns_the_payment_shape(pipeline):
    pay = await pipeline.record_payment("acc_1", 197.0)
    assert pay["payment_id"].startswith("pay_acc_1_")
    assert pay["account_id"] == "acc_1"
    assert pay["amount"] == 197.0
    assert pay["method"] == "stripe"
    assert pay["status"] == "completed"
    assert pay["timestamp"]


async def test_record_payment_accepts_a_custom_method(pipeline, tmp_path):
    await pipeline.record_payment("acc_1", 50.0, method="manual")
    assert rows(tmp_path / "lead_gen.db", "trade_payments")[0]["method"] == "manual"


async def test_record_payment_persists_the_row(pipeline, tmp_path):
    pay = await pipeline.record_payment("acc_7", 99.5, method="stripe")
    stored = rows(tmp_path / "lead_gen.db", "trade_payments")
    assert len(stored) == 1
    assert stored[0]["payment_id"] == pay["payment_id"]
    assert stored[0]["account_id"] == "acc_7"
    assert stored[0]["amount"] == 99.5
    assert stored[0]["status"] == "completed"


async def test_record_payment_accepts_a_zero_amount(pipeline):
    assert (await pipeline.record_payment("acc_1", 0.0))["amount"] == 0.0


async def test_record_payment_accepts_a_negative_refund(pipeline):
    """No validation on amount — a refund is representable."""
    assert (await pipeline.record_payment("acc_1", -50.0))["amount"] == -50.0


async def test_payments_within_the_same_second_share_a_payment_id(pipeline, frozen_clock):
    """payment_id has 1-second granularity, so a burst collides. INSERT OR
    REPLACE means the second write overwrites the first. Real collision
    behaviour, pinned rather than papered over."""
    frozen_clock.current = frozen_clock.current.replace(second=30)
    a = await pipeline.record_payment("acc_1", 10.0)
    b = await pipeline.record_payment("acc_1", 20.0)
    assert a["payment_id"] == b["payment_id"]
    assert len(pipeline.get_payments()) == 1
    assert pipeline.get_payments()[0]["amount"] == 20.0


async def test_payments_for_different_accounts_do_not_collide(pipeline):
    a = await pipeline.record_payment("acc_1", 10.0)
    b = await pipeline.record_payment("acc_2", 20.0)
    assert a["payment_id"] != b["payment_id"]
    assert len(pipeline.get_payments()) == 2


async def test_record_payment_survives_a_database_failure(pipeline, monkeypatch, caplog):
    monkeypatch.setattr(Database, "get_connection",
                        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("nope"))))
    with caplog.at_level("ERROR", logger="engine.trades.convert"):
        pay = await pipeline.record_payment("acc_1", 97.0)
    assert pay["status"] == "completed"
    assert any("Failed to save trade payment" in r.message for r in caplog.records), caplog.records


# ── create_subscription ────────────────────────────────────────────────────
async def test_create_subscription_returns_the_expected_shape(pipeline, frozen_clock):
    sub = await pipeline.create_subscription("acc_1", plan="pro")
    assert sub["subscription_id"] == "sub_acc_1"
    assert sub["account_id"] == "acc_1"
    assert sub["plan"] == "pro"
    assert sub["monthly_fee"] == 497
    assert sub["status"] == "active"
    # Two separate datetime.now() reads, so they can differ by microseconds.
    assert sub["started_at"].startswith("2026-09-27T12:00:00")
    assert sub["next_billing"].startswith("2026-09-27T12:00:00")
    assert sub["started_at"] <= sub["next_billing"], "next_billing must not precede start"


async def test_create_subscription_defaults_to_starter(pipeline):
    assert (await pipeline.create_subscription("acc_1"))["monthly_fee"] == 97


async def test_create_subscription_for_unknown_plan_uses_starter_fee(pipeline):
    sub = await pipeline.create_subscription("acc_1", plan="gold")
    assert sub["plan"] == "gold"
    assert sub["monthly_fee"] == 97


async def test_create_subscription_is_not_persisted(pipeline):
    """Subscriptions are in-memory only — the pipeline never writes a table."""
    before = len(pipeline.get_accounts())
    await pipeline.create_subscription("acc_1")
    assert len(pipeline.get_accounts()) == before


async def test_create_subscription_is_repeatable_and_deterministic(pipeline):
    a = await pipeline.create_subscription("acc_1")
    b = await pipeline.create_subscription("acc_1")
    assert a["subscription_id"] == b["subscription_id"]


# ── getters ────────────────────────────────────────────────────────────────
def test_get_accounts_and_payments_start_empty(pipeline):
    assert pipeline.get_accounts() == []
    assert pipeline.get_payments() == []


def test_get_accounts_returns_dicts(pipeline):
    assert pipeline.get_accounts() == []


async def test_get_accounts_returns_all_rows(pipeline):
    await pipeline.convert_to_account(lead(business_name="A"))
    await pipeline.convert_to_account(lead(business_name="B"))
    accounts = pipeline.get_accounts()
    assert len(accounts) == 2
    assert {a["business_name"] for a in accounts} == {"A", "B"}


async def test_get_payments_returns_all_rows(pipeline):
    await pipeline.record_payment("acc_1", 10.0)
    await pipeline.record_payment("acc_2", 20.0)
    assert {p["amount"] for p in pipeline.get_payments()} == {10.0, 20.0}


def test_get_accounts_survives_a_database_failure(pipeline, monkeypatch, caplog):
    monkeypatch.setattr(Database, "get_connection",
                        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("nope"))))
    with caplog.at_level("ERROR", logger="engine.trades.convert"):
        assert pipeline.get_accounts() == []
    assert any("Failed to read trade accounts" in r.message for r in caplog.records), caplog.records


def test_get_payments_survives_a_database_failure(pipeline, monkeypatch, caplog):
    monkeypatch.setattr(Database, "get_connection",
                        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("nope"))))
    with caplog.at_level("ERROR", logger="engine.trades.convert"):
        assert pipeline.get_payments() == []
    assert any("Failed to read trade payments" in r.message for r in caplog.records), caplog.records


def test_get_accounts_on_a_missing_table_returns_empty(pipeline):
    with sqlite3.connect(Database.db_file) as conn:
        conn.execute("DROP TABLE trade_accounts")
    assert pipeline.get_accounts() == []


# ── get_revenue_stats ──────────────────────────────────────────────────────
def test_revenue_stats_on_an_empty_pipeline(pipeline):
    assert pipeline.get_revenue_stats() == {
        "total_accounts": 0,
        "active_accounts": 0,
        "total_payments": 0,
        "total_revenue": 0,
        "monthly_recurring_revenue": 0,
        "average_revenue_per_account": 0,
    }


def test_revenue_stats_average_is_zero_not_a_division_error(pipeline):
    assert pipeline.get_revenue_stats()["average_revenue_per_account"] == 0


async def test_revenue_stats_sums_revenue_and_counts(pipeline):
    await pipeline.convert_to_account(lead(), plan="growth")
    await pipeline.record_payment("acc_a", 100.0)
    await pipeline.record_payment("acc_b", 50.0)
    stats = pipeline.get_revenue_stats()
    assert stats["total_revenue"] == 150.0
    assert stats["total_payments"] == 2
    assert stats["total_accounts"] == 1
    assert stats["active_accounts"] == 1
    assert stats["monthly_recurring_revenue"] == 197
    assert stats["average_revenue_per_account"] == 150.0


async def test_monthly_recurring_revenue_sums_each_active_plan(pipeline):
    await pipeline.convert_to_account(lead(business_name="A"), plan="starter")
    await pipeline.convert_to_account(lead(business_name="B"), plan="pro")
    stats = pipeline.get_revenue_stats()
    assert stats["monthly_recurring_revenue"] == 97 + 497
    assert stats["average_revenue_per_account"] == 0.0


async def test_monthly_recurring_revenue_excludes_inactive_accounts(pipeline, tmp_path):
    await pipeline.convert_to_account(lead(business_name="A"), plan="pro")
    with sqlite3.connect(tmp_path / "lead_gen.db") as conn:
        conn.execute("UPDATE trade_accounts SET status='cancelled'")
        conn.commit()
    stats = pipeline.get_revenue_stats()
    assert stats["total_accounts"] == 1
    assert stats["active_accounts"] == 0
    assert stats["monthly_recurring_revenue"] == 0


async def test_average_revenue_per_account_is_rounded_to_two_places(pipeline):
    await pipeline.convert_to_account(lead(business_name="A"))
    await pipeline.convert_to_account(lead(business_name="B"))
    await pipeline.convert_to_account(lead(business_name="C"))
    await pipeline.record_payment("acc_1", 100.0)
    assert pipeline.get_revenue_stats()["average_revenue_per_account"] == 33.33


async def test_revenue_stats_with_accounts_but_no_payments(pipeline):
    await pipeline.convert_to_account(lead(), plan="enterprise")
    stats = pipeline.get_revenue_stats()
    assert stats["total_payments"] == 0
    assert stats["total_revenue"] == 0
    assert stats["average_revenue_per_account"] == 0
    assert stats["monthly_recurring_revenue"] == 997


async def test_revenue_stats_with_payments_but_no_accounts(pipeline):
    await pipeline.record_payment("acc_ghost", 500.0)
    stats = pipeline.get_revenue_stats()
    assert stats["total_payments"] == 1
    assert stats["total_revenue"] == 500.0
    assert stats["total_accounts"] == 0
    assert stats["average_revenue_per_account"] == 0


def test_revenue_stats_degrades_gracefully_on_a_broken_database(pipeline, monkeypatch):
    monkeypatch.setattr(Database, "get_connection",
                        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("nope"))))
    stats = pipeline.get_revenue_stats()
    assert stats["total_accounts"] == 0
    assert stats["total_payments"] == 0
    assert stats["average_revenue_per_account"] == 0


# ── end-to-end pipeline ────────────────────────────────────────────────────
async def test_full_lead_to_subscription_flow(pipeline):
    ld = lead(business_name="Ace", phone="555", email="a@b.com", trade="roofing")
    account = await pipeline.convert_to_account(ld, plan="growth")
    payment = await pipeline.record_payment(account["account_id"], 197.0)
    sub = await pipeline.create_subscription(account["account_id"], plan="growth")

    assert account["status"] == "active"
    assert payment["status"] == "completed"
    assert sub["status"] == "active"
    stats = pipeline.get_revenue_stats()
    assert stats == {
        "total_accounts": 1,
        "active_accounts": 1,
        "total_payments": 1,
        "total_revenue": 197.0,
        "monthly_recurring_revenue": 197,
        "average_revenue_per_account": 197.0,
    }


async def test_two_renewals_in_a_month_accumulate_revenue(pipeline, frozen_clock):
    """Distinct payment_ids (different second) must both be counted."""
    account = await pipeline.convert_to_account(lead(), plan="starter")
    first = await pipeline.record_payment(account["account_id"], 97.0)
    frozen_clock.current = frozen_clock.current.replace(second=1)
    second = await pipeline.record_payment(account["account_id"], 97.0)
    assert first["payment_id"] != second["payment_id"]
    stats = pipeline.get_revenue_stats()
    assert stats["total_payments"] == 2
    assert stats["total_revenue"] == 194.0


async def test_two_pipelines_on_one_db_share_state(pipeline, tmp_path):
    """Database.db_file is global, so a second pipeline in the same data_dir
    sees the first one's rows."""
    await pipeline.convert_to_account(lead(), plan="starter")
    p2 = ConversionPipeline(data_dir=str(tmp_path))
    assert len(p2.get_accounts()) == 1
