"""Tests for the schema migration runner (audit 2026-09-27).

A migration runner that has never been tested is a deployment incident waiting
for a version bump. These cover the three properties that matter: it is
idempotent, a failure rolls back cleanly, and mutating an already-applied
migration is caught instead of silently ignored.
"""
import sqlite3

import pytest

from engine import migrations


@pytest.fixture
def fresh_db(tmp_path):
    """A database with the base `leads` table but no migration history."""
    path = tmp_path / "m.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE leads (id TEXT PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()
    return str(path)


def test_fresh_database_is_at_version_zero(fresh_db):
    assert migrations.current_version(fresh_db) == 0


def test_apply_migrations_adds_the_columns_persistence_reads(fresh_db):
    """The columns engine/persistence.py attaches on load must exist."""
    assert migrations.apply_migrations(fresh_db) == 1

    cols = {r[1] for r in sqlite3.connect(fresh_db).execute("PRAGMA table_info(leads)")}
    for expected in ("status", "first_name", "last_name", "address",
                     "project_description", "sms_consent", "email_consent",
                     "call_consent", "consent_source"):
        assert expected in cols, f"{expected} missing after migration"


def test_apply_migrations_is_idempotent(fresh_db):
    """Running it on every boot must not re-apply or fail."""
    assert migrations.apply_migrations(fresh_db) == 1
    assert migrations.apply_migrations(fresh_db) == 0
    assert migrations.apply_migrations(fresh_db) == 0
    assert migrations.current_version(fresh_db) == migrations.SCHEMA_VERSION


def test_version_is_recorded_with_a_checksum(fresh_db):
    migrations.apply_migrations(fresh_db)
    rows = sqlite3.connect(fresh_db).execute(
        "SELECT version, name, checksum, applied_at FROM schema_migrations").fetchall()
    assert len(rows) == 1
    version, name, checksum, applied_at = rows[0]
    assert version == 1
    assert name == "align_leads_with_persistence"
    assert checksum and isinstance(checksum, str)
    assert applied_at > 0


def test_editing_an_applied_migration_is_rejected(fresh_db, monkeypatch):
    """The checksum guard: a changed applied migration must raise, not re-run."""
    migrations.apply_migrations(fresh_db)

    def changed(conn):
        conn.execute("ALTER TABLE leads ADD COLUMN something_new TEXT")

    monkeypatch.setattr(migrations, "CHAIN",
                        [(1, "align_leads_with_persistence", [changed])])
    with pytest.raises(RuntimeError, match="already applied"):
        migrations.apply_migrations(fresh_db)


def test_a_failing_migration_rolls_back_and_leaves_no_record(fresh_db, monkeypatch):
    """A half-applied migration is worse than none -- it must roll back."""
    def half_done(conn):
        conn.execute("ALTER TABLE leads ADD COLUMN added_first TEXT")
        raise RuntimeError("boom")

    monkeypatch.setattr(migrations, "CHAIN", [(99, "doomed", [half_done])])
    with pytest.raises(RuntimeError, match="boom"):
        migrations.apply_migrations(fresh_db)

    conn = sqlite3.connect(fresh_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)")}
    recorded = conn.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=99").fetchone()[0]
    conn.close()

    assert "added_first" not in cols, "partial migration was left behind"
    assert recorded == 0, "a failed migration must not be recorded as applied"


def test_multiple_migrations_apply_in_version_order(fresh_db, monkeypatch):
    order: list[int] = []

    def make(v):
        def step(conn):
            order.append(v)
            conn.execute(f"ALTER TABLE leads ADD COLUMN col_{v} TEXT")
        return step

    monkeypatch.setattr(migrations, "CHAIN",
                        [(3, "third", [make(3)]), (1, "first", [make(1)]),
                         (2, "second", [make(2)])])
    assert migrations.apply_migrations(fresh_db) == 3
    assert order == [1, 2, 3], f"applied out of order: {order}"


def test_apply_migrations_creates_a_missing_parent_directory(tmp_path):
    """apply_migrations must mkdir the parent, because it is called on a path
    that may not exist yet on a fresh install."""
    target = tmp_path / "brand" / "new" / "y.db"
    assert not target.parent.exists()

    assert migrations.apply_migrations(str(target)) == 1
    assert target.exists(), "apply_migrations did not create the database file"

    cols = {r[1] for r in sqlite3.connect(target).execute("PRAGMA table_info(leads)")}
    # The base table is created by Database.initialize(), not by a migration,
    # so on a truly fresh path there is nothing to alter. The assertion is that
    # the call SUCCEEDED and recorded its version rather than raising.
    assert migrations.current_version(str(target)) == migrations.SCHEMA_VERSION
