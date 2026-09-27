import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SignalStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    linkedin_urn TEXT NOT NULL UNIQUE,
                    profile_url TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    last_scanned_at REAL
                );
                CREATE TABLE IF NOT EXISTS posts (
                    post_urn TEXT PRIMARY KEY,
                    source_id INTEGER,
                    post_url TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    weighted_engagement INTEGER NOT NULL DEFAULT 0,
                    velocity REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    discovered_at REAL NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES source_accounts(id)
                );
                CREATE TABLE IF NOT EXISTS signal_leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity_key TEXT NOT NULL,
                    actor_urn TEXT NOT NULL DEFAULT '',
                    profile_url TEXT NOT NULL DEFAULT '',
                    source_post_urn TEXT NOT NULL,
                    action TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    company TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    headline TEXT NOT NULL DEFAULT '',
                    comment_text TEXT NOT NULL DEFAULT '',
                    qualification_json TEXT NOT NULL DEFAULT '{}',
                    offer_json TEXT NOT NULL DEFAULT '{}',
                    outreach_json TEXT NOT NULL DEFAULT '{}',
                    compliance_json TEXT NOT NULL DEFAULT '{}',
                    enrichment_source TEXT NOT NULL DEFAULT '',
                    verification_status TEXT NOT NULL DEFAULT '',
                    crm_lead_id TEXT NOT NULL DEFAULT '',
                    outreach_status TEXT NOT NULL DEFAULT 'new',
                    approved_at REAL,
                    rejection_reason TEXT NOT NULL DEFAULT '',
                    provider_lead_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(identity_key, source_post_urn)
                );
                CREATE TABLE IF NOT EXISTS suppressions (
                    email TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job_locks (
                    name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    provider_event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(provider, provider_event_id)
                );
                CREATE TABLE IF NOT EXISTS content_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    insights_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    angle TEXT NOT NULL DEFAULT '',
                    hook TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL,
                    cta TEXT NOT NULL DEFAULT '',
                    claims_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'awaiting_approval',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    published_post_urn TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(asset_id) REFERENCES content_assets(id)
                );
                """
            )
            existing = {row[1] for row in connection.execute("PRAGMA table_info(signal_leads)").fetchall()}
            additions = {
                "headline": "TEXT NOT NULL DEFAULT ''",
                "comment_text": "TEXT NOT NULL DEFAULT ''",
                "offer_json": "TEXT NOT NULL DEFAULT '{}'",
                "outreach_json": "TEXT NOT NULL DEFAULT '{}'",
                "compliance_json": "TEXT NOT NULL DEFAULT '{}'",
                "approved_at": "REAL",
                "rejection_reason": "TEXT NOT NULL DEFAULT ''",
                "provider_lead_id": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in additions.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE signal_leads ADD COLUMN {column} {definition}")
            content_columns = {row[1] for row in connection.execute("PRAGMA table_info(content_drafts)").fetchall()}
            if "published_post_urn" not in content_columns:
                connection.execute("ALTER TABLE content_drafts ADD COLUMN published_post_urn TEXT NOT NULL DEFAULT ''")

    def upsert_source_account(self, name: str, linkedin_urn: str, profile_url: str = "", enabled: bool = True) -> int:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO source_accounts(name, linkedin_urn, profile_url, enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(linkedin_urn) DO UPDATE SET
                    name=excluded.name, profile_url=excluded.profile_url, enabled=excluded.enabled""",
                (name, linkedin_urn, profile_url, int(enabled), now),
            )
            row = connection.execute("SELECT id FROM source_accounts WHERE linkedin_urn = ?", (linkedin_urn,)).fetchone()
            return int(row["id"])

    def list_sources(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM source_accounts ORDER BY id").fetchall()
            return [dict(row) for row in rows]

    def mark_source_scanned(self, source_id: int):
        with self._connect() as connection:
            connection.execute("UPDATE source_accounts SET last_scanned_at = ? WHERE id = ?", (time.time(), source_id))

    def upsert_post(self, post_urn: str, source_id: int | None, post_url: str, text: str,
                    weighted_engagement: int, velocity: float, raw: dict[str, Any] | None = None):
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO posts(post_urn, source_id, post_url, text, weighted_engagement, velocity, raw_json, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_urn) DO UPDATE SET
                    source_id=excluded.source_id, post_url=excluded.post_url, text=excluded.text,
                    weighted_engagement=excluded.weighted_engagement, velocity=excluded.velocity,
                    raw_json=excluded.raw_json""",
                (post_urn, source_id, post_url, text, weighted_engagement, velocity,
                 json.dumps(raw or {}, separators=(",", ":")), time.time()),
            )

    def upsert_signal_lead(self, identity_key: str, actor_urn: str, profile_url: str,
                           source_post_urn: str, action: str, name: str = "",
                           headline: str = "", comment_text: str = "") -> int:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO signal_leads(identity_key, actor_urn, profile_url, source_post_urn, action, name, headline, comment_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(identity_key, source_post_urn) DO UPDATE SET
                    actor_urn=excluded.actor_urn, profile_url=excluded.profile_url,
                    action=excluded.action,
                    name=CASE WHEN excluded.name != '' THEN excluded.name ELSE signal_leads.name END,
                    headline=CASE WHEN excluded.headline != '' THEN excluded.headline ELSE signal_leads.headline END,
                    comment_text=CASE WHEN excluded.comment_text != '' THEN excluded.comment_text ELSE signal_leads.comment_text END,
                    updated_at=excluded.updated_at""",
                (identity_key, actor_urn, profile_url, source_post_urn, action, name, headline, comment_text, now, now),
            )
            row = connection.execute(
                "SELECT id FROM signal_leads WHERE identity_key = ? AND source_post_urn = ?",
                (identity_key, source_post_urn),
            ).fetchone()
            return int(row["id"])

    def update_lead(self, lead_id: int, **fields):
        allowed = {
            "name", "email", "phone", "company", "title", "qualification_json",
            "headline", "comment_text", "offer_json", "outreach_json", "compliance_json",
            "enrichment_source", "verification_status", "crm_lead_id", "outreach_status",
            "approved_at", "rejection_reason", "provider_lead_id",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = time.time()
        clause = ", ".join(f"{key} = ?" for key in updates)
        values = [*updates.values(), lead_id]
        with self._connect() as connection:
            connection.execute(f"UPDATE signal_leads SET {clause} WHERE id = ?", values)

    def get_lead(self, lead_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM signal_leads WHERE id = ?", (lead_id,)).fetchone()
            return dict(row) if row else None

    def list_leads(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM signal_leads ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 5000)),)
            ).fetchall()
            return [dict(row) for row in rows]

    def suppress(self, email: str, reason: str):
        normalized = email.strip().lower()
        if not normalized:
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO suppressions(email, reason, created_at) VALUES (?, ?, ?) ON CONFLICT(email) DO UPDATE SET reason=excluded.reason",
                (normalized, reason, time.time()),
            )

    def is_suppressed(self, email: str) -> bool:
        normalized = email.strip().lower()
        if not normalized:
            return False
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM suppressions WHERE email = ?", (normalized,)).fetchone()
            return row is not None

    def record_run(self, source: str, status: str, stats: dict[str, Any], error: str = "") -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO runs(source, status, stats_json, error, created_at) VALUES (?, ?, ?, ?, ?)",
                (source, status, json.dumps(stats, separators=(",", ":")), error, time.time()),
            )
            return int(cursor.lastrowid)

    def try_acquire_lock(self, name: str, owner: str, ttl_seconds: int) -> bool:
        now = time.time()
        with self._connect() as connection:
            connection.execute("DELETE FROM job_locks WHERE expires_at <= ?", (now,))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO job_locks(name, owner, expires_at) VALUES (?, ?, ?)",
                (name, owner, now + max(1, ttl_seconds)),
            )
            return cursor.rowcount == 1

    def release_lock(self, name: str, owner: str):
        with self._connect() as connection:
            connection.execute("DELETE FROM job_locks WHERE name = ? AND owner = ?", (name, owner))

    def create_oauth_state(self, state: str, ttl_seconds: int = 600):
        now = time.time()
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT OR REPLACE INTO oauth_states(state, expires_at) VALUES (?, ?)",
                (state, now + max(60, ttl_seconds)),
            )

    def consume_oauth_state(self, state: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM oauth_states WHERE state = ? AND expires_at > ?",
                (state, now),
            )
            connection.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now,))
            return cursor.rowcount == 1

    def record_event(self, provider: str, provider_event_id: str, event_type: str,
                     email: str, payload: dict[str, Any]) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO provider_events(
                    provider, provider_event_id, event_type, email, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    provider,
                    provider_event_id,
                    event_type,
                    email.strip().lower(),
                    json.dumps(payload, separators=(",", ":")),
                    time.time(),
                ),
            )
            return cursor.rowcount == 1

    def create_content_asset(self, source_type: str, source_text: str,
                             metadata: dict[str, Any], insights: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO content_assets(source_type, source_text, metadata_json, insights_json, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    source_type,
                    source_text,
                    json.dumps(metadata, separators=(",", ":")),
                    json.dumps(insights, separators=(",", ":")),
                    time.time(),
                ),
            )
            return int(cursor.lastrowid)

    def create_content_draft(self, asset_id: int, draft: dict[str, Any]) -> int:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO content_drafts(
                    asset_id, angle, hook, body, cta, claims_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'awaiting_approval', ?, ?)""",
                (
                    asset_id,
                    str(draft.get("angle", "")),
                    str(draft.get("hook", "")),
                    str(draft.get("body", "")),
                    str(draft.get("cta", "")),
                    json.dumps(draft.get("claims_to_verify", []), separators=(",", ":")),
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def list_content_drafts(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM content_drafts ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_content_draft(self, draft_id: int, status: str | None = None,
                             metrics: dict[str, Any] | None = None,
                             published_post_urn: str | None = None) -> dict[str, Any] | None:
        # values binds heterogeneous SQLite parameters (str, int, float),
        # so it is a list[Any] rather than a list[str].
        fields: list[str] = []
        values: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if metrics is not None:
            fields.append("metrics_json = ?")
            values.append(json.dumps(metrics, separators=(",", ":")))
        if published_post_urn is not None:
            fields.append("published_post_urn = ?")
            values.append(published_post_urn)
        if fields:
            fields.append("updated_at = ?")
            values.append(time.time())
            values.append(draft_id)
            with self._connect() as connection:
                connection.execute(f"UPDATE content_drafts SET {', '.join(fields)} WHERE id = ?", values)
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM content_drafts WHERE id = ?", (draft_id,)).fetchone()
            return dict(row) if row else None

    def get_content_draft(self, draft_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM content_drafts WHERE id = ?", (draft_id,)).fetchone()
            return dict(row) if row else None

    def latest_run(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "sources": connection.execute("SELECT COUNT(*) FROM source_accounts").fetchone()[0],
                "posts": connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
                "leads": connection.execute("SELECT COUNT(*) FROM signal_leads").fetchone()[0],
                "awaiting_approval": connection.execute(
                    "SELECT COUNT(*) FROM signal_leads WHERE outreach_status = 'awaiting_approval'"
                ).fetchone()[0],
                "suppressed": connection.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0],
            }
