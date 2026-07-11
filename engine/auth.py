from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import bcrypt
import jwt as pyjwt

from .database import Database

logger = logging.getLogger(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = 86400 * 7  # 7 days

if not JWT_SECRET:
    JWT_SECRET = hashlib.sha256(os.urandom(64)).hexdigest()
    logger.warning("JWT_SECRET not set — using ephemeral key. Sessions invalidate on restart.")


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _generate_api_key() -> str:
    return f"lgn_{secrets.token_hex(24)}"


def _hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class AuthManager:
    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        with Database.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS orgs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    stripe_customer_id TEXT,
                    plan TEXT DEFAULT 'free',
                    created_at TEXT NOT NULL,
                    settings TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (org_id) REFERENCES orgs(id)
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    org_id TEXT NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL,
                    name TEXT DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    last_used TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (org_id) REFERENCES orgs(id)
                );
                CREATE TABLE IF NOT EXISTS org_verticals (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    config TEXT DEFAULT '{}',
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (org_id) REFERENCES orgs(id),
                    UNIQUE(org_id, slug)
                );
            """)
            conn.commit()

    def register(self, email: str, password: str, name: str, org_name: str) -> Dict[str, Any]:
        email = email.strip().lower()
        with Database.get_connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                raise ValueError("Email already registered")

            org_id = uuid.uuid4().hex[:16]
            slug = org_name.lower().replace(" ", "-").replace("_", "-")[:50]
            slug = slug or f"org-{org_id[:8]}"
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO orgs (id, name, slug, created_at) VALUES (?, ?, ?, ?)",
                (org_id, org_name, slug, now),
            )

            user_id = uuid.uuid4().hex[:16]
            pw_hash = _hash_password(password)
            conn.execute(
                "INSERT INTO users (id, email, password_hash, name, org_id, role, created_at) VALUES (?, ?, ?, ?, ?, 'owner', ?)",
                (user_id, email, pw_hash, name, org_id, now),
            )

            api_key = _generate_api_key()
            key_hash = _hash_api_key(api_key)
            key_id = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO api_keys (id, user_id, org_id, key_hash, name, created_at) VALUES (?, ?, ?, ?, 'default', ?)",
                (key_id, user_id, org_id, key_hash, now),
            )

            self._seed_default_verticals(conn, org_id, now)

            conn.commit()

            token = self._create_jwt(user_id, org_id, email, "owner")
            return {
                "user": {"id": user_id, "email": email, "name": name, "org_id": org_id, "role": "owner"},
                "org": {"id": org_id, "name": org_name, "slug": slug, "plan": "free"},
                "api_key": api_key,
                "token": token,
            }

    def _seed_default_verticals(self, conn, org_id: str, now: str):
        defaults = [
            ("Home Improvement", "home_improvement", {
                "platforms": ["google_maps", "yelp", "facebook", "nextdoor"],
                "keywords": ["contractor", "services", "repair", "installation"],
                "avg_job_value": 8500,
                "lead_cpl_ceiling": 85,
                "urgency_triggers": ["emergency", "repair", "broken"],
                "best_platform": "google_maps",
                "conversion_rate": 0.10,
            }),
            ("Real Estate Investors", "real_estate_investors", {
                "platforms": ["google_maps", "facebook", "linkedin"],
                "keywords": ["real estate investor", "property investor", "land developer", "fix and flip", "wholesaler"],
                "avg_job_value": 50000,
                "lead_cpl_ceiling": 200,
                "urgency_triggers": ["closing", "funding", "deal"],
                "best_platform": "linkedin",
                "conversion_rate": 0.05,
            }),
            ("Software Buyers", "software_buyers", {
                "platforms": ["linkedin", "facebook", "google_maps"],
                "keywords": ["software", "SaaS", "tech buyer", "CTO", "IT director", "digital transformation"],
                "avg_job_value": 500,
                "lead_cpl_ceiling": 50,
                "urgency_triggers": ["migration", "upgrade", "compliance"],
                "best_platform": "linkedin",
                "conversion_rate": 0.08,
            }),
            ("Developers Looking for Land", "developers_land", {
                "platforms": ["google_maps", "facebook", "linkedin"],
                "keywords": ["land developer", "real estate developer", "construction developer", "property development"],
                "avg_job_value": 100000,
                "lead_cpl_ceiling": 500,
                "urgency_triggers": ["zoning", "permits", "closing"],
                "best_platform": "linkedin",
                "conversion_rate": 0.03,
            }),
        ]
        for name, slug, config in defaults:
            vid = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT OR IGNORE INTO org_verticals (id, org_id, name, slug, config, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (vid, org_id, name, slug, json.dumps(config), now),
            )

    def login(self, email: str, password: str) -> Dict[str, Any]:
        email = email.strip().lower()
        with Database.get_connection() as conn:
            row = conn.execute("SELECT id, email, password_hash, name, org_id, role FROM users WHERE email = ?", (email,)).fetchone()
            if not row:
                raise ValueError("Invalid email or password")
            if not _verify_password(password, row["password_hash"]):
                raise ValueError("Invalid email or password")

            org = conn.execute("SELECT id, name, slug, plan FROM orgs WHERE id = ?", (row["org_id"],)).fetchone()
            token = self._create_jwt(row["id"], row["org_id"], row["email"], row["role"])
            return {
                "user": {"id": row["id"], "email": row["email"], "name": row["name"], "org_id": row["org_id"], "role": row["role"]},
                "org": {"id": org["id"], "name": org["name"], "slug": org["slug"], "plan": org["plan"]},
                "token": token,
            }

    def _create_jwt(self, user_id: str, org_id: str, email: str, role: str) -> str:
        payload = {
            "sub": user_id,
            "org_id": org_id,
            "email": email,
            "role": role,
            "iat": int(time.time()),
            "exp": int(time.time()) + JWT_EXPIRY,
        }
        return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def verify_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError) as e:
            logger.debug("JWT verification failed: %s", e)
            return None

    def verify_api_key(self, key: str) -> Optional[Dict[str, Any]]:
        key_hash = _hash_api_key(key)
        with Database.get_connection() as conn:
            row = conn.execute("""
                SELECT ak.user_id, ak.org_id, u.role, o.plan
                FROM api_keys ak
                JOIN users u ON u.id = ak.user_id
                JOIN orgs o ON o.id = ak.org_id
                WHERE ak.key_hash = ?
            """, (key_hash,)).fetchone()
            if row:
                conn.execute("UPDATE api_keys SET last_used = ? WHERE key_hash = ?",
                             (datetime.now(timezone.utc).isoformat(), key_hash))
                conn.commit()
                return {"user_id": row["user_id"], "org_id": row["org_id"], "role": row["role"], "plan": row["plan"]}
            return None

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with Database.get_connection() as conn:
            row = conn.execute("SELECT id, email, name, org_id, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if row:
                return dict(row)
            return None

    def get_org(self, org_id: str) -> Optional[Dict[str, Any]]:
        with Database.get_connection() as conn:
            row = conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
            if row:
                return dict(row)
            return None

    def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        with Database.get_connection() as conn:
            rows = conn.execute("SELECT id, name, created_at, last_used FROM api_keys WHERE user_id = ?", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def create_api_key(self, user_id: str, org_id: str, name: str = "default") -> str:
        api_key = _generate_api_key()
        key_hash = _hash_api_key(api_key)
        key_id = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        with Database.get_connection() as conn:
            conn.execute(
                "INSERT INTO api_keys (id, user_id, org_id, key_hash, name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key_id, user_id, org_id, key_hash, name, now),
            )
            conn.commit()
        return api_key

    def delete_api_key(self, key_id: str, user_id: str) -> bool:
        with Database.get_connection() as conn:
            cursor = conn.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_org_verticals(self, org_id: str) -> List[Dict[str, Any]]:
        with Database.get_connection() as conn:
            rows = conn.execute("SELECT id, name, slug, config, enabled FROM org_verticals WHERE org_id = ? ORDER BY name", (org_id,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["config"] = json.loads(d["config"])
                except (json.JSONDecodeError, TypeError):
                    d["config"] = {}
                result.append(d)
            return result

    def add_vertical(self, org_id: str, name: str, slug: str, config: Dict[str, Any]) -> Dict[str, Any]:
        vid = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        with Database.get_connection() as conn:
            conn.execute(
                "INSERT INTO org_verticals (id, org_id, name, slug, config, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (vid, org_id, name, slug, json.dumps(config), now),
            )
            conn.commit()
        return {"id": vid, "name": name, "slug": slug, "config": config, "enabled": True}

    def update_vertical(self, vertical_id: str, org_id: str, data: Dict[str, Any]) -> bool:
        with Database.get_connection() as conn:
            fields = []
            values = []
            for key in ("name", "slug", "enabled"):
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(data[key])
            if "config" in data:
                fields.append("config = ?")
                values.append(json.dumps(data["config"]))
            if not fields:
                return False
            values.append(vertical_id)
            values.append(org_id)
            cursor = conn.execute(
                f"UPDATE org_verticals SET {', '.join(fields)} WHERE id = ? AND org_id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_vertical(self, vertical_id: str, org_id: str) -> bool:
        with Database.get_connection() as conn:
            cursor = conn.execute("DELETE FROM org_verticals WHERE id = ? AND org_id = ?", (vertical_id, org_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_user_by_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        info = self.verify_api_key(api_key)
        if info:
            return self.get_user(info["user_id"])
        return None


auth_manager = AuthManager()
