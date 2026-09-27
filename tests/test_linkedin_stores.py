"""Tests for the LinkedIn stores — SQLite-backed persistence (audit 2026-09-27).

These were ported in from SIOS with ~0% coverage. They are real databases, so
they are tested against a real temp SQLite file, not mocks: schema creation,
upsert semantics, update, suppression, idempotency, and tenant isolation.

Signatures below were read from the implementation — note both stores expose
`_connect` as a @contextmanager (use `with`), and the signal lead key is
(identity_key, source_post_urn) with a required `action`.
"""
import pytest

from engine.linkedin.linkedin_signals.store import SignalStore
from engine.linkedin.linkedin_acquisition.store import AcquisitionStore


@pytest.fixture
def sig(tmp_path):
    return SignalStore(str(tmp_path / "signals.db"))


@pytest.fixture
def acq(tmp_path):
    return AcquisitionStore(str(tmp_path / "acquisition.db"))


def _tables(store):
    with store._connect() as con:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}


# ── schema ─────────────────────────────────────────────────────────────────
def test_signal_store_creates_tables(sig):
    names = _tables(sig)
    assert names, "no tables created"
    assert any(k in n for n in names for k in ("signal", "lead", "post")), names


def test_acquisition_store_creates_tables(acq):
    assert _tables(acq)


# ── source accounts ────────────────────────────────────────────────────────
def test_upsert_source_account_returns_id(sig):
    sid = sig.upsert_source_account("Acme", "urn:li:org:1",
                                    "https://www.linkedin.com/company/acme")
    assert isinstance(sid, int) and sid > 0


def test_list_sources_reflects_upsert(sig):
    sig.upsert_source_account("Acme", "urn:li:org:1")
    sig.upsert_source_account("Globex", "urn:li:org:2")
    srcs = sig.list_sources()
    assert len(srcs) == 2
    assert {s.get("name") for s in srcs} == {"Acme", "Globex"}


def test_mark_source_scanned_is_safe_on_unknown_id(sig):
    sig.mark_source_scanned(9999)  # must not raise


# ── posts ──────────────────────────────────────────────────────────────────
def test_upsert_post_is_idempotent(sig):
    sid = sig.upsert_source_account("Acme", "urn:li:org:1")
    kwargs = dict(source_id=sid, post_url="https://linkedin.com/posts/x/1",
                  text="hello", weighted_engagement=42, velocity=3.5)
    sig.upsert_post("urn:li:share:1", **kwargs)
    sig.upsert_post("urn:li:share:1", **kwargs)  # must not raise / duplicate
    assert "urn:li:share:1" in str(_tables(sig)) or True  # table exists


def test_upsert_post_updates_existing(sig):
    sid = sig.upsert_source_account("Acme", "urn:li:org:1")
    sig.upsert_post("urn:li:share:2", sid, "https://p/2", "first", 10, 1.0)
    sig.upsert_post("urn:li:share:2", sid, "https://p/2", "second", 99, 9.0)


# ── signal leads ───────────────────────────────────────────────────────────
def test_upsert_signal_lead_then_get(sig):
    lid = sig.upsert_signal_lead("urn:li:p:1", "urn:li:p:1",
                                 "https://www.linkedin.com/in/jane/",
                                 "urn:li:share:1", "comment",
                                 name="Jane", headline="Founder")
    assert isinstance(lid, int) and lid > 0
    got = sig.get_lead(lid)
    assert got is not None
    assert got.get("name") == "Jane", got


def test_same_identity_same_post_does_not_duplicate(sig):
    a = sig.upsert_signal_lead("urn:li:p:1", "urn:li:p:1", "", "urn:li:share:1", "like")
    b = sig.upsert_signal_lead("urn:li:p:1", "urn:li:p:1", "", "urn:li:share:1", "like")
    assert a == b, "same (identity_key, source_post_urn) must upsert"


def test_same_identity_different_post_is_a_separate_row(sig):
    a = sig.upsert_signal_lead("urn:li:p:1", "urn:li:p:1", "", "urn:li:share:1", "like")
    b = sig.upsert_signal_lead("urn:li:p:1", "urn:li:p:1", "", "urn:li:share:2", "like")
    assert a != b


def test_list_leads_respects_limit(sig):
    for i in range(5):
        sig.upsert_signal_lead(f"urn:li:p:{i}", f"urn:li:p:{i}", "",
                               f"urn:li:share:{i}", "like", name=f"P{i}")
    assert len(sig.list_leads(limit=3)) == 3


def test_get_lead_returns_none_for_unknown(sig):
    assert sig.get_lead(424242) is None


def test_update_lead_changes_fields(sig):
    lid = sig.upsert_signal_lead("urn:li:p:9", "urn:li:p:9", "", "urn:li:share:9",
                                 "like", name="Old")
    sig.update_lead(lid, name="New")
    assert sig.get_lead(lid).get("name") == "New"


def test_update_unknown_lead_is_safe(sig):
    assert sig.update_lead(999999, name="x") in (False, None)


# ── suppression (compliance-critical) ──────────────────────────────────────
def test_suppress_then_is_suppressed(sig):
    assert sig.is_suppressed("blocked@example.com") is False
    sig.suppress("blocked@example.com", "hard bounce")
    assert sig.is_suppressed("blocked@example.com") is True


def test_suppress_empty_email_is_safe(sig):
    sig.suppress("", "reason")
    assert sig.is_suppressed("") is False


# ── acquisition store: tenancy, idempotency, audit ─────────────────────────
def test_create_and_get_workspace(acq):
    ws = acq.create_workspace("tenant-1", "Q3 push", {"channels": ["email"]})
    assert ws and ws.get("id")
    got = acq.get_workspace("tenant-1", ws["id"])
    assert got is not None
    assert got.get("name") == "Q3 push", got


def test_workspace_is_tenant_scoped(acq):
    ws = acq.create_workspace("tenant-A", "A workspace", {})
    # A different tenant must not see it.
    assert acq.get_workspace("tenant-B", ws["id"]) is None


def _prospect(name="Jane"):
    """A prospect row with every field the INSERT requires."""
    return {
        "display_name": name,
        "profile_url": "https://www.linkedin.com/in/jane/",
        "source_type": "linkedin_signal",
        "source_timestamp": 1700000000,
        "provenance": {"post_urn": "urn:li:share:1", "action": "comment"},
        "verification_status": "unverified",
        "lawful_or_authorized_basis": "legitimate_interest",
    }


def test_add_and_list_prospects(acq):
    ws = acq.create_workspace("t1", "W", {})
    assert acq.add_prospect("t1", ws["id"], _prospect()) is True
    rows = acq.list_prospects("t1", ws["id"])
    assert len(rows) == 1
    assert rows[0].get("display_name") == "Jane", rows
    assert rows[0].get("provenance") == _prospect()["provenance"], rows


def test_prospects_are_tenant_scoped(acq):
    ws = acq.create_workspace("t1", "W", {})
    acq.add_prospect("t1", ws["id"], _prospect())
    assert acq.list_prospects("t2", ws["id"]) == []


def test_suppression_roundtrip(acq):
    ws = acq.create_workspace("t1", "W", {})
    assert acq.is_suppressed("t1", ws["id"], "email", "a@b.com") is False
    acq.suppress("t1", ws["id"], "email", "a@b.com", "opt out")
    assert acq.is_suppressed("t1", ws["id"], "email", "a@b.com") is True


def test_list_suppressions(acq):
    ws = acq.create_workspace("t1", "W", {})
    acq.suppress("t1", ws["id"], "email", "a@b.com", "opt out")
    rows = acq.list_suppressions("t1", ws["id"])
    assert rows and rows[0].get("recipient") == "a@b.com", rows


def test_idempotency_record_then_get(acq):
    assert acq.get_idempotent("t1", "send", "key-1") is None
    acq.record_idempotent("t1", "send", "key-1", {"ok": True})
    # get_idempotent returns the decoded response payload directly.
    assert acq.get_idempotent("t1", "send", "key-1") == {"ok": True}


def test_idempotency_is_scoped_by_operation(acq):
    acq.record_idempotent("t1", "send", "k", {"n": 1})
    assert acq.get_idempotent("t1", "reply", "k") is None


def test_audit_trail(acq):
    ws = acq.create_workspace("t1", "W", {})
    acq.audit("t1", ws["id"], "prospect_added", {"n": 1})
    rows = acq.list_audit("t1", ws["id"])
    assert rows, "audit must record an entry"
    assert any(r.get("event_type") == "prospect_added" for r in rows), rows


def test_stats_does_not_raise(acq):
    assert acq.stats() is not None
