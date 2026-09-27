import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now():
    return datetime.now(UTC).isoformat()


class AcquisitionStore:
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
                CREATE TABLE IF NOT EXISTS acquisition_workspaces (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_workspaces_tenant
                    ON acquisition_workspaces(tenant_id);
                CREATE TABLE IF NOT EXISTS prospects (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    company TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    profile_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    lawful_or_authorized_basis TEXT NOT NULL,
                    suppression_status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES acquisition_workspaces(id) ON DELETE CASCADE,
                    UNIQUE(tenant_id, workspace_id, profile_url)
                );
                CREATE TABLE IF NOT EXISTS suppression_records (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    normalized_recipient TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES acquisition_workspaces(id) ON DELETE CASCADE,
                    UNIQUE(tenant_id, workspace_id, channel, normalized_recipient)
                );
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    tenant_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, operation, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_audit_scope
                    ON audit_events(tenant_id, workspace_id, created_at);
                """
            )

    def get_idempotent(self, tenant_id: str, operation: str, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM idempotency_records WHERE tenant_id=? AND operation=? AND idempotency_key=?",
                (tenant_id, operation, key),
            ).fetchone()
            return json.loads(row["response_json"]) if row else None

    def record_idempotent(self, tenant_id: str, operation: str, key: str, response: dict[str, Any]):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO idempotency_records VALUES (?, ?, ?, ?, ?)",
                (tenant_id, operation, key, json.dumps(response, separators=(",", ":")), _now()),
            )

    def create_workspace(self, tenant_id: str, name: str, settings: dict[str, Any]) -> dict[str, Any]:
        workspace = {
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "name": name.strip(),
            "settings": settings,
            "created_at": _now(),
        }
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO acquisition_workspaces VALUES (?, ?, ?, ?, ?, ?)",
                (workspace["id"], tenant_id, workspace["name"], json.dumps(settings, separators=(",", ":")), workspace["created_at"], workspace["created_at"]),
            )
        return workspace

    def get_workspace(self, tenant_id: str, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM acquisition_workspaces WHERE tenant_id=? AND id=?", (tenant_id, workspace_id)
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["settings"] = json.loads(item.pop("settings_json"))
            return item

    def add_prospect(self, tenant_id: str, workspace_id: str, prospect: dict[str, Any]) -> bool:
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO prospects
                (id, tenant_id, workspace_id, display_name, company, role, profile_url, source_type,
                 source_timestamp, provenance_json, verification_status, lawful_or_authorized_basis,
                 suppression_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (uuid.uuid4().hex, tenant_id, workspace_id, prospect["display_name"], prospect.get("company", ""),
                 prospect.get("role", ""), prospect["profile_url"], prospect["source_type"], prospect["source_timestamp"],
                 json.dumps(prospect["provenance"], separators=(",", ":")), prospect["verification_status"],
                 prospect["lawful_or_authorized_basis"], now, now),
            )
            return cursor.rowcount == 1

    def list_prospects(self, tenant_id: str, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM prospects WHERE tenant_id=? AND workspace_id=? ORDER BY created_at, id",
                (tenant_id, workspace_id),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["provenance"] = json.loads(item.pop("provenance_json"))
                result.append(item)
            return result

    def suppress(self, tenant_id: str, workspace_id: str, channel: str, recipient: str, reason: str) -> dict[str, Any]:
        record = {"id": uuid.uuid4().hex, "channel": channel, "recipient": recipient, "reason": reason, "created_at": _now()}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO suppression_records VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, workspace_id, channel, normalized_recipient)
                DO UPDATE SET reason=excluded.reason""",
                (record["id"], tenant_id, workspace_id, channel, recipient, reason, record["created_at"]),
            )
        return record

    def is_suppressed(self, tenant_id: str, workspace_id: str, channel: str, recipient: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM suppression_records
                WHERE tenant_id=? AND workspace_id=? AND normalized_recipient=? AND channel IN (?, 'all')""",
                (tenant_id, workspace_id, recipient, channel),
            ).fetchone()
            return row is not None

    def list_suppressions(self, tenant_id: str, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, channel, normalized_recipient AS recipient, reason, created_at
                FROM suppression_records WHERE tenant_id=? AND workspace_id=? ORDER BY created_at, id""",
                (tenant_id, workspace_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def audit(self, tenant_id: str, workspace_id: str, event_type: str, payload: dict[str, Any]):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, tenant_id, workspace_id, event_type, json.dumps(payload, separators=(",", ":")), _now()),
            )

    def list_audit(self, tenant_id: str, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE tenant_id=? AND workspace_id=? ORDER BY created_at, id",
                (tenant_id, workspace_id),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item.pop("payload_json"))
                result.append(item)
            return result

    def stats(self):
        with self._connect() as connection:
            return {
                "workspaces": connection.execute("SELECT COUNT(*) FROM acquisition_workspaces").fetchone()[0],
                "prospects": connection.execute("SELECT COUNT(*) FROM prospects").fetchone()[0],
                "suppressions": connection.execute("SELECT COUNT(*) FROM suppression_records").fetchone()[0],
            }
