"""Minimal, dependency-free schema migration runner.

Why this exists: `engine/database.py` did schema evolution with
`CREATE TABLE IF NOT EXISTS` plus a loop of `ALTER TABLE ... ADD COLUMN`
guarded by `PRAGMA table_info`. That is fine on a fresh checkout and wrong in
production for three reasons:

  1. There is no version. You cannot tell what a given database has been
     through, and you cannot refuse to open a database from the future.
  2. The ALTER loop is not transactional. A crash mid-loop leaves the
     schema partially migrated with no way to know where it stopped.
  3. A column rename or a backfill is impossible to express.

This gives the project a real numbered-migration chain with an applied-state
table, one transaction per migration, and a checksum so an already-applied
migration that later changes is caught rather than silently ignored.

Design constraints:
  - No new dependency. The product is self-hosted BYOK; adding a migration
    library to get this is not worth the supply chain.
  - Never destructive. No migration drops a column or a table. Anything that
    needs that is a deliberate, manual operation.
  - The existing ad-hoc ALTERs in database.py keep working. This layer is
    additive: it runs the numbered chain, and database.initialize() still
    ensures base tables exist. Do not remove initialize() -- a brand new
    database has no schema for the migrations to alter.

Usage:
    from engine.migrations import apply_migrations
    apply_migrations()   # idempotent; safe to call on every boot
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Bump when the chain below changes in a way that requires coordination.
SCHEMA_VERSION = 1

_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  REAL NOT NULL
)
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE)
    conn.commit()


def _applied(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    rows = conn.execute("SELECT version, name, checksum FROM schema_migrations").fetchall()
    return {int(r[0]): (r[1], r[2]) for r in rows}


def _checksum(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


# ── the chain ──────────────────────────────────────────────────────────────
# Each entry is (version, name, callables). Each callable receives an open
# connection and must do its own DDL; the runner wraps the whole entry in one
# transaction so a failure rolls the migration back cleanly.
Migration = tuple[int, str, list[Callable[[sqlite3.Connection], None]]]


def _m001_align_leads_with_persistence(conn: sqlite3.Connection) -> None:
    """Ensure every column engine/persistence.py reads exists on `leads`.

    persistence.py attaches these as dynamic attributes on load and reads them
    from the row, so a database missing any of them raises KeyError on the
    first lead read -- long after the deploy that caused the drift.

    No-op when `leads` does not exist: the base tables are created by
    Database.initialize(), not by a migration. On a fresh install the migration
    chain has nothing to alter, and ALTERing a missing table would abort the
    whole chain.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "leads" not in tables:
        logger.info("no `leads` table yet; migration 001 is a no-op")
        return

    existing = {r[1] for r in conn.execute("PRAGMA table_info(leads)")}
    required = {
        "status": "TEXT DEFAULT 'new'",
        "first_name": "TEXT",
        "last_name": "TEXT",
        "address": "TEXT",
        "project_description": "TEXT",
        "utm_source": "TEXT",
        "utm_medium": "TEXT",
        "utm_campaign": "TEXT",
        "sms_consent": "INTEGER DEFAULT 0",
        "email_consent": "INTEGER DEFAULT 0",
        "call_consent": "INTEGER DEFAULT 0",
        "consent_source": "TEXT",
    }
    for col, ddl in required.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {ddl}")


CHAIN: list[Migration] = [
    (1, "align_leads_with_persistence", [_m001_align_leads_with_persistence]),
]


def apply_migrations(db_path: str | Path | None = None) -> int:
    """Apply every pending migration. Returns the number applied.

    Idempotent: running it twice applies nothing the second time. Raises
    RuntimeError if a migration already applied has since been edited, which
    is the signal that a new migration is required rather than an old one
    being mutated.
    """
    if db_path is None:
        from engine.database import Database

        db_path = Database.db_file

    db_path = str(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_table(conn)
        done = _applied(conn)
        applied = 0

        for version, name, steps in sorted(CHAIN, key=lambda m: m[0]):
            src = "".join(
                (s.__doc__ or "") for s in steps
            ) + repr([getattr(s, "__name__", "") for s in steps])
            digest = _checksum(src)
            if version in done:
                if done[version][1] != digest:
                    raise RuntimeError(
                        f"migration {version} ({name}) was already applied but its "
                        f"content changed (checksum {done[version][1]} -> {digest}). "
                        "Add a NEW migration instead of editing an applied one."
                    )
                continue

            logger.info("applying migration %s: %s", version, name)
            # Explicit BEGIN, not `with conn:`. sqlite3's context manager only
            # rolls back the *implicit* transaction it opened, and DDL such as
            # ALTER TABLE forces an implicit commit -- so a migration that
            # added a column and then raised would leave that column behind
            # with no record of it. Owning the transaction means the rollback
            # is real.
            try:
                conn.execute("BEGIN")
                for step in steps:
                    step(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (version, name, digest, time.time()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("migration %s (%s) failed and was rolled back",
                                 version, name)
                raise
            applied += 1

        if applied:
            logger.info("applied %s migration(s); schema is now at v%s",
                        applied, SCHEMA_VERSION)
        return applied
    finally:
        conn.close()


def current_version(db_path: str | Path | None = None) -> int:
    """Highest applied migration version, or 0 on a fresh database."""
    if db_path is None:
        from engine.database import Database

        db_path = Database.db_file
    # A database that does not exist yet is simply at version 0 -- do not
    # create a file just to read its (empty) version.
    if not Path(str(db_path)).exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_table(conn)
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
