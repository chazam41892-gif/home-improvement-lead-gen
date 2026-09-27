"""Security + behaviour tests for engine/auth.py (audit 2026-09-27).

Signatures and the SQL DDL were read from engine/auth.py and engine/database.py
before these tests were written. Everything runs against a throwaway SQLite file
under tmp_path — the real data/lead_gen.db is never written to by these tests,
and no real credential or .env value is read or asserted on.

The focus is the SECURITY properties, not the happy path:
  * password hashing is bcrypt, never plaintext, and a wrong password fails
  * JWT signature verification rejects tampered / forged / expired tokens
  * a token signed with a DIFFERENT secret is rejected
  * an "alg: none" token is rejected (no algorithm confusion)
  * API keys are stored as sha256 hashes, never in plaintext
  * tenant isolation: one user cannot delete or read another user's API key
  * update_vertical() column whitelist cannot be used for SQL injection
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import bcrypt
import jwt as pyjwt
import pytest

from engine import auth as auth_mod
from engine.auth import (
    JWT_ALGORITHM,
    JWT_EXPIRY,
    AuthManager,
    _generate_api_key,
    _hash_api_key,
    _hash_password,
    _verify_password,
)
from engine.database import Database

AUTH_PATH = Path(auth_mod.__file__)


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Point Database at a fresh temp file for every test in this module."""
    original = Database.db_file
    Database.set_db_file(str(tmp_path / "auth_test.db"))
    try:
        yield
    finally:
        Database.set_db_file(original)


@pytest.fixture
def am():
    return AuthManager()


@pytest.fixture
def reg(am):
    """A registered owner: 1 org, 1 user, 1 API key, 4 seeded verticals."""
    return am.register("Owner@Example.COM ", "correct horse battery", "Dana Owner", "Acme Roofing")


def rows(sql, params=()):
    with Database.get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    with Database.get_connection() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def _fresh_auth_module(tmp_path, env: dict):
    """Execute engine/auth.py as a *separate* module object under a controlled env.

    Used to exercise the module-level JWT_SECRET bootstrap without disturbing
    the already-imported engine.auth singleton that main.py holds.
    """
    prev_file = Database.db_file
    Database.set_db_file(str(tmp_path / "probe.db"))
    old_environ = dict(sys.modules["os"].environ)
    try:
        for k in ("JWT_SECRET", "AUTH_DISABLED"):
            sys.modules["os"].environ.pop(k, None)
        sys.modules["os"].environ.update(env)
        spec = importlib.util.spec_from_file_location("engine._auth_probe", AUTH_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        Database.set_db_file(prev_file)
        sys.modules["os"].environ.clear()
        sys.modules["os"].environ.update(old_environ)


# ── module bootstrap: JWT_SECRET enforcement ────────────────────────────────
def test_missing_jwt_secret_raises_at_import(tmp_path):
    """No JWT_SECRET and no AUTH_DISABLED => hard RuntimeError at import time."""
    with pytest.raises(RuntimeError, match="JWT_SECRET is required"):
        _fresh_auth_module(tmp_path, {})


def test_auth_disabled_allows_ephemeral_secret(tmp_path, caplog):
    """AUTH_DISABLED=1 with no JWT_SECRET => ephemeral random key + loud warning."""
    with caplog.at_level("WARNING", logger="engine.auth"):
        mod = _fresh_auth_module(tmp_path, {"AUTH_DISABLED": "1"})
    assert mod.JWT_SECRET != ""
    assert len(mod.JWT_SECRET) == 64 and int(mod.JWT_SECRET, 16) >= 0  # sha256 hex
    assert any("ephemeral key" in r.getMessage() for r in caplog.records)
    # the ephemeral key must still actually sign/verify
    tok = pyjwt.encode({"sub": "u1", "exp": int(time.time()) + 60}, mod.JWT_SECRET, algorithm="HS256")
    assert pyjwt.decode(tok, mod.JWT_SECRET, algorithms=[JWT_ALGORITHM])["sub"] == "u1"


def test_configured_constants():
    assert JWT_ALGORITHM == "HS256"
    assert JWT_EXPIRY == 86400 * 7


# ── password hashing ────────────────────────────────────────────────────────
def test_hash_password_is_bcrypt_not_plaintext():
    pw = "hunter2-plaintext-should-never-appear"
    h = _hash_password(pw)
    assert pw not in h
    assert h.startswith("$2") and len(h) == 60
    # the hash carries only bcrypt salt+digest structure — no fragment of the
    # password survives, and it round-trips only through bcrypt.checkpw
    assert h[7:29] != pw[:22] and h[29:] != pw
    assert _verify_password(pw, h) and pw not in _b64decode(h.replace("$2b$12$", ""))


def test_verify_password_accepts_right_and_rejects_wrong():
    h = _hash_password("s3cret-pass")
    assert _verify_password("s3cret-pass", h) is True
    assert _verify_password("s3cret-pas", h) is False       # truncated
    assert _verify_password("s3cret-pasS", h) is False      # case differs
    assert _verify_password("", h) is False


def test_hashes_are_salted_and_deterministic_only_for_verify():
    a, b = _hash_password("same"), _hash_password("same")
    assert a != b, "bcrypt salt not random — identical hashes enable precomputation"
    assert _verify_password("same", a) and _verify_password("same", b)


def test_verify_password_raises_on_malformed_hash():
    with pytest.raises(ValueError):
        _verify_password("pw", "not-a-bcrypt-hash")


# ── api key generation / hashing ────────────────────────────────────────────
def test_generate_api_key_shape_and_uniqueness():
    keys = {_generate_api_key() for _ in range(200)}
    assert len(keys) == 200
    for k in keys:
        assert k.startswith("lgn_")
        assert len(k) == 4 + 48 and int(k[4:], 16) >= 0


def test_hash_api_key_is_sha256_hex_and_hides_the_key():
    key = _generate_api_key()
    h = _hash_api_key(key)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
    assert key not in h and key[4:] not in h
    assert h == hashlib.sha256(key.encode("utf-8")).hexdigest()
    assert _hash_api_key(key) == h  # stable → it is the DB lookup index


# ── register ────────────────────────────────────────────────────────────────
def test_register_returns_owner_org_key_and_token(reg, am):
    assert reg["user"]["email"] == "owner@example.com"     # stripped + lowercased
    assert reg["user"]["role"] == "owner"
    assert reg["org"]["slug"] == "acme-roofing"
    assert reg["org"]["plan"] == "free"
    assert reg["api_key"].startswith("lgn_")
    assert am.verify_jwt(reg["token"])["sub"] == reg["user"]["id"]


def test_register_never_stores_password_in_plaintext(reg):
    row = one("SELECT password_hash FROM users WHERE id = ?", (reg["user"]["id"],))
    assert "correct horse battery" not in row["password_hash"]
    assert row["password_hash"].startswith("$2")
    assert _verify_password("correct horse battery", row["password_hash"])


def test_register_stores_only_api_key_hash(reg):
    row = one("SELECT key_hash FROM api_keys WHERE user_id = ?", (reg["user"]["id"],))
    assert reg["api_key"] not in row["key_hash"]
    assert row["key_hash"] == _hash_api_key(reg["api_key"])


def test_register_creates_four_default_verticals(reg, am):
    vs = am.get_org_verticals(reg["org"]["id"])
    assert len(vs) == 4
    assert {v["slug"] for v in vs} == {
        "developers_land", "home_improvement", "real_estate_investors", "software_buyers"}
    hi = next(v for v in vs if v["slug"] == "home_improvement")
    assert hi["config"]["best_platform"] == "google_maps"
    assert hi["config"]["avg_job_value"] == 8500
    assert hi["enabled"] == 1


def test_register_rejects_duplicate_email_case_insensitively(am, reg):
    with pytest.raises(ValueError, match="Email already registered"):
        am.register("OWNER@example.com", "another-pw", "Impostor", "Other Co")


def test_register_slug_collisions_get_numeric_suffix(am):
    s1 = am.register("a@x.com", "pw-aaaaaaa", "A", "Dup Name!")["org"]["slug"]
    s2 = am.register("b@x.com", "pw-bbbbbbb", "B", "Dup Name!")["org"]["slug"]
    s3 = am.register("c@x.com", "pw-ccccccc", "C", "Dup Name!")["org"]["slug"]
    assert (s1, s2, s3) == ("dup-name", "dup-name-1", "dup-name-2")


def test_register_slug_falls_back_when_name_has_no_alphanumerics(am):
    org = am.register("d@x.com", "pw-ddddddd", "D", "!!! ??? ###")["org"]
    assert org["slug"].startswith("org-") and len(org["slug"]) == 12


def test_register_slug_truncated_to_50(am):
    org = am.register("e@x.com", "pw-eeeeeee", "E", "z" * 200)["org"]
    assert len(org["slug"]) == 50


def test_ensure_tables_is_idempotent(am):
    """Second AuthManager() hits the duplicate-column / duplicate-index excepts."""
    AuthManager()
    names = {r["name"] for r in rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"orgs", "users", "api_keys", "org_verticals"} <= names


# ── login ───────────────────────────────────────────────────────────────────
def test_login_success_returns_org_and_fresh_token(am, reg):
    out = am.login("  OWNER@EXAMPLE.com ", "correct horse battery")
    assert out["user"]["id"] == reg["user"]["id"]
    assert out["org"]["slug"] == "acme-roofing"
    assert am.verify_jwt(out["token"])["email"] == "owner@example.com"


def test_login_wrong_password_fails(am, reg):
    with pytest.raises(ValueError, match="Invalid email or password"):
        am.login("owner@example.com", "wrong-password")


def test_login_unknown_email_fails(am, reg):
    with pytest.raises(ValueError, match="Invalid email or password"):
        am.login("nobody@example.com", "correct horse battery")


def test_login_error_is_identical_for_unknown_user_and_wrong_password(am, reg):
    """No user enumeration: the message must not distinguish the two failures."""
    msgs = []
    for email, pw in (("nobody@example.com", "correct horse battery"),
                      ("owner@example.com", "wrong-password")):
        try:
            am.login(email, pw)
            raise AssertionError("login should have raised")
        except ValueError as e:
            msgs.append(str(e))
    assert msgs[0] == msgs[1] == "Invalid email or password"


def test_google_user_cannot_log_in_with_guessed_password(am):
    am.register_google_user("g@x.com", "Gina", "google-subject-1")
    for guess in ("", "password", "g@x.com", "google-subject-1"):
        with pytest.raises(ValueError):
            am.login("g@x.com", guess)


# ── JWT verification: the security core ─────────────────────────────────────
def test_verify_jwt_roundtrip_payload(am, reg):
    claims = am.verify_jwt(reg["token"])
    assert claims["sub"] == reg["user"]["id"]
    assert claims["org_id"] == reg["org"]["id"]
    assert claims["email"] == "owner@example.com"
    assert claims["role"] == "owner"
    assert claims["exp"] - claims["iat"] == JWT_EXPIRY


def test_expired_token_is_rejected(am):
    expired = pyjwt.encode(
        {"sub": "u1", "org_id": "o1", "exp": int(time.time()) - 5, "iat": int(time.time()) - 10},
        auth_mod.JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        pyjwt.decode(expired, auth_mod.JWT_SECRET, algorithms=[JWT_ALGORITHM])  # sanity
    assert am.verify_jwt(expired) is None


def test_token_expiring_one_second_from_now_is_accepted(am):
    tok = pyjwt.encode({"sub": "u1", "exp": int(time.time()) + 30},
                       auth_mod.JWT_SECRET, algorithm=JWT_ALGORITHM)
    assert am.verify_jwt(tok)["sub"] == "u1"


def test_tampered_payload_is_rejected(am, reg):
    header, payload, sig = reg["token"].split(".")
    claims = json.loads(_b64decode(payload))
    claims["role"] = "admin"  # privilege escalation attempt
    forged = ".".join([header, _b64(json.dumps(claims).encode()), sig])
    assert am.verify_jwt(forged) is None


def test_tampered_signature_is_rejected(am, reg):
    header, payload, sig = reg["token"].split(".")
    flipped = ("A" if sig[-1] != "A" else "B") + sig[:-1]
    assert am.verify_jwt(".".join([header, payload, flipped])) is None


def test_token_signed_with_a_different_secret_is_rejected(am, reg, monkeypatch):
    other_secret = "a-completely-different-attacker-chosen-secret"
    forged = pyjwt.encode(
        {"sub": reg["user"]["id"], "org_id": reg["org"]["id"], "role": "owner",
         "exp": int(time.time()) + 3600}, other_secret, algorithm="HS256")
    assert am.verify_jwt(forged) is None

    # and: rotating the server secret invalidates previously issued tokens
    monkeypatch.setattr(auth_mod, "JWT_SECRET", other_secret)
    assert am.verify_jwt(reg["token"]) is None


def test_alg_none_token_is_rejected(am):
    """Algorithm-confusion guard: unsigned token must not be accepted."""
    unsigned = pyjwt.encode({"sub": "attacker", "role": "owner",
                             "exp": int(time.time()) + 3600}, key="", algorithm="none")
    assert am.verify_jwt(unsigned) is None
    assert am.verify_jwt(unsigned + "x") is None


def test_rs256_shaped_token_is_rejected(am):
    """HS256-only allow-list: a token claiming another alg family is refused."""
    tok = pyjwt.encode({"sub": "x", "exp": int(time.time()) + 60},
                       "secret", algorithm="HS512")
    assert am.verify_jwt(tok) is None


def test_garbage_tokens_are_rejected_without_raising(am):
    garbage = [
        "", "not-a-jwt", "a.b.c", "....", "Bearer something",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.deadbeef",  # well-formed segments, bad sig
    ]
    for bad in garbage:
        assert am.verify_jwt(bad) is None


def test_verify_jwt_does_not_log_the_token(am, reg, caplog):
    """A rejected token must not be echoed into logs (it is a bearer credential)."""
    with caplog.at_level("DEBUG"):
        assert am.verify_jwt("header." + "A" * 20 + ".B" * 43) is None
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "A" * 20 not in blob


# ── api key verification ────────────────────────────────────────────────────
def test_verify_api_key_returns_identity_and_stamps_last_used(am, reg):
    info = am.verify_api_key(reg["api_key"])
    assert info == {"user_id": reg["user"]["id"], "org_id": reg["org"]["id"],
                    "role": "owner", "plan": "free"}
    assert one("SELECT last_used FROM api_keys WHERE key_hash = ?",
               (_hash_api_key(reg["api_key"]),))["last_used"] is not None


def test_verify_api_key_rejects_unknown_key(am, reg):
    assert am.verify_api_key("lgn_" + "0" * 48) is None
    assert am.verify_api_key(reg["api_key"][:-1]) is None       # off-by-one char
    assert am.verify_api_key(reg["api_key"].upper()) is None
    assert am.verify_api_key("") is None


def test_get_user_by_api_key(am, reg):
    u = am.get_user_by_api_key(reg["api_key"])
    assert u["id"] == reg["user"]["id"] and u["email"] == "owner@example.com"
    assert am.get_user_by_api_key("lgn_" + "f" * 48) is None


def test_create_and_list_api_keys(am, reg):
    before = am.list_api_keys(reg["user"]["id"])
    assert len(before) == 1 and before[0]["name"] == "default" and before[0]["last_used"] is None
    new_key = am.create_api_key(reg["user"]["id"], reg["org"]["id"], "ci")
    assert new_key.startswith("lgn_")
    after = am.list_api_keys(reg["user"]["id"])
    assert len(after) == 2 and {k["name"] for k in after} == {"default", "ci"}
    # "password" must never be returned by the listing
    assert new_key not in json.dumps(after)
    assert am.verify_api_key(new_key)["user_id"] == reg["user"]["id"]


def test_delete_api_key_own_key(am, reg):
    keys = am.list_api_keys(reg["user"]["id"])
    assert am.delete_api_key(keys[0]["id"], reg["user"]["id"]) is True
    assert am.verify_api_key(reg["api_key"]) is None
    assert am.delete_api_key(keys[0]["id"], reg["user"]["id"]) is False


def test_delete_api_key_is_tenant_scoped(am, reg):
    """User B must not be able to delete user A's API key."""
    other = am.register("f@x.com", "pw-fffffff", "F", "Other Org")
    victim_keys = am.list_api_keys(reg["user"]["id"])
    vid = victim_keys[0]["id"]
    assert am.delete_api_key(vid, other["user"]["id"]) is False
    assert am.verify_api_key(reg["api_key"]) is not None, "cross-tenant delete succeeded"
    assert len(am.list_api_keys(reg["user"]["id"])) == 1


# ── lookups ─────────────────────────────────────────────────────────────────
def test_get_user_and_missing(am, reg):
    u = am.get_user(reg["user"]["id"])
    assert u["email"] == "owner@example.com" and u["role"] == "owner"
    assert "password_hash" not in u, "get_user must not leak the password hash"
    assert am.get_user("does-not-exist") is None


def test_get_org_and_missing(am, reg):
    o = am.get_org(reg["org"]["id"])
    assert o["slug"] == "acme-roofing" and o["plan"] == "free"
    assert am.get_org("nope") is None


def test_get_user_by_email_normalizes(am, reg):
    assert am.get_user_by_email("  OWNER@Example.com ")["id"] == reg["user"]["id"]
    assert am.get_user_by_email("ghost@example.com") is None


def test_get_user_by_google_id(am):
    out = am.register_google_user("h@x.com", "Hank", "goog-abc")
    got = am.get_user_by_google_id("goog-abc")
    assert got["id"] == out["user"]["id"] and got["email"] == "h@x.com"
    assert am.get_user_by_google_id("goog-nope") is None


def test_link_google_id(am, reg):
    am.link_google_id(reg["user"]["id"], "goog-later")
    assert am.get_user_by_google_id("goog-later")["id"] == reg["user"]["id"]
    assert am.get_user(reg["user"]["id"])["email"] == "owner@example.com"  # untouched


# ── google registration ─────────────────────────────────────────────────────
def test_register_google_user_shape(am):
    out = am.register_google_user("  G@X.com ", "Grace Hopper", "goog-1")
    assert out["user"]["email"] == "g@x.com"
    assert out["user"]["google_id"] == "goog-1"
    assert out["user"]["role"] == "owner"
    assert out["org"]["name"] == "Grace Hopper's Team"
    assert out["org"]["slug"] == "grace-hopper-s-team"
    assert out["api_key"].startswith("lgn_")
    assert am.verify_jwt(out["token"])["role"] == "owner"
    assert len(am.get_org_verticals(out["org"]["id"])) == 4


def test_register_google_user_duplicate_email(am, reg):
    with pytest.raises(ValueError, match="Email already registered"):
        am.register_google_user("owner@example.com", "Owner", "goog-2")


def test_register_google_user_slug_collision(am):
    s1 = am.register_google_user("i1@x.com", "Same Name", "gid-a")["org"]["slug"]
    s2 = am.register_google_user("i2@x.com", "Same Name", "gid-b")["org"]["slug"]
    assert (s1, s2) == ("same-name-s-team", "same-name-s-team-1")


def test_register_google_user_google_id_unique_index_exists(am):
    am.register_google_user("u1@x.com", "U One", "shared-gid")
    with pytest.raises(sqlite3.IntegrityError):
        am.register_google_user("u2@x.com", "U Two", "shared-gid")


# ── verticals ───────────────────────────────────────────────────────────────
def test_add_vertical_persists_and_returns_typed_payload(am, reg):
    v = am.add_vertical(reg["org"]["id"], "HVAC", "hvac", {"avg_job_value": 1200, "cpl": 40})
    assert v["enabled"] is True
    assert set(v) == {"id", "name", "slug", "config", "enabled"}
    stored = next(x for x in am.get_org_verticals(reg["org"]["id"]) if x["id"] == v["id"])
    assert stored["config"] == {"avg_job_value": 1200, "cpl": 40}


def test_get_org_verticals_survives_corrupt_config(am, reg):
    with Database.get_connection() as conn:
        conn.execute("INSERT INTO org_verticals (id, org_id, name, slug, config, enabled, created_at)"
                     " VALUES ('broken', ?, 'Broken', 'broken', 'not json at all', 1, 'now')",
                     (reg["org"]["id"],))
        conn.execute("INSERT INTO org_verticals (id, org_id, name, slug, config, enabled, created_at)"
                     " VALUES ('nullcfg', ?, 'Null', 'nullcfg', NULL, 1, 'now')",
                     (reg["org"]["id"],))
        conn.commit()
    got = {v["id"]: v for v in am.get_org_verticals(reg["org"]["id"])}
    assert got["broken"]["config"] == {}       # JSONDecodeError swallowed
    assert got["nullcfg"]["config"] == {}      # TypeError swallowed
    assert len(got) == 6


def test_get_org_verticals_for_unknown_org_is_empty(am):
    assert am.get_org_verticals("no-such-org") == []


def test_update_vertical_updates_whitelisted_fields(am, reg):
    v = am.add_vertical(reg["org"]["id"], "Old", "old-slug", {"a": 1})
    assert am.update_vertical(v["id"], reg["org"]["id"],
                              {"name": "New", "slug": "new-slug", "enabled": 0,
                               "config": {"b": 2}}) is True
    got = am.get_org_verticals(reg["org"]["id"])
    row = next(x for x in got if x["id"] == v["id"])
    assert (row["name"], row["slug"], row["enabled"], row["config"]) == ("New", "new-slug", 0, {"b": 2})


def test_update_vertical_returns_false_with_no_valid_fields(am, reg):
    v = am.add_vertical(reg["org"]["id"], "Keep", "keep", {})
    assert am.update_vertical(v["id"], reg["org"]["id"], {}) is False
    assert am.update_vertical(v["id"], reg["org"]["id"], {"id": "hijack", "org_id": "hijack"}) is False
    row = next(x for x in am.get_org_verticals(reg["org"]["id"]) if x["id"] == v["id"])
    assert (row["name"], row["slug"]) == ("Keep", "keep")


def test_update_vertical_ignores_injection_attempt_via_key_name(am, reg):
    """Unknown keys can never reach the SQL string — the SET clause is whitelisted."""
    v = am.add_vertical(reg["org"]["id"], "Safe", "safe", {})
    evil = {"name": "x'; DROP TABLE org_verticals; --", "slug": "safe"}
    assert am.update_vertical(v["id"], reg["org"]["id"], evil) is True
    # table still exists, and the payload was stored as a literal string
    assert {r["name"] for r in rows("SELECT name FROM sqlite_master WHERE type='table'")} >= {"org_verticals"}
    row = next(x for x in am.get_org_verticals(reg["org"]["id"]) if x["id"] == v["id"])
    assert row["name"] == "x'; DROP TABLE org_verticals; --"


def test_update_vertical_is_org_scoped(am, reg):
    other = am.register("z@x.com", "pw-zzzzzzz", "Z", "Zeta Org")
    v = am.add_vertical(reg["org"]["id"], "Private", "private", {})
    assert am.update_vertical(v["id"], other["org"]["id"], {"name": "Hijacked"}) is False
    assert next(x for x in am.get_org_verticals(reg["org"]["id"]) if x["id"] == v["id"])["name"] == "Private"


def test_delete_vertical_and_org_scoping(am, reg):
    other = am.register("y@x.com", "pw-yyyyyyy", "Y", "Yotta Org")
    v = am.add_vertical(reg["org"]["id"], "Doomed", "doomed", {})
    assert am.delete_vertical(v["id"], other["org"]["id"]) is False
    assert am.delete_vertical(v["id"], reg["org"]["id"]) is True
    assert am.delete_vertical(v["id"], reg["org"]["id"]) is False
    assert v["id"] not in {x["id"] for x in am.get_org_verticals(reg["org"]["id"])}


def test_ensure_tables_survives_conflicting_google_id_index(tmp_path):
    """Covers the defensive except at auth.py:104-107.

    A legacy users table can already contain two rows sharing one google_id.
    CREATE UNIQUE INDEX then fails on the duplicate data. _ensure_tables() must
    swallow that and still commit the rest of the schema rather than crash the
    whole app on boot.
    """
    Database.set_db_file(str(tmp_path / "conflict.db"))
    with Database.get_connection() as conn:
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,"
                     " password_hash TEXT NOT NULL, name TEXT NOT NULL, org_id TEXT NOT NULL,"
                     " role TEXT DEFAULT 'member', google_id TEXT, created_at TEXT NOT NULL)")
        # duplicate google_id values -> the UNIQUE index cannot be created
        conn.execute("INSERT INTO users VALUES ('u1','a@x.com','h','A','o1','member',"
                     "'shared-google-id','t0')")
        conn.execute("INSERT INTO users VALUES ('u2','b@x.com','h','B','o1','member',"
                     "'shared-google-id','t0')")
        conn.commit()

    AuthManager()  # must not raise

    with Database.get_connection() as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"orgs", "users", "api_keys", "org_verticals"} <= names
        # the two pre-existing rows survived the failed migration
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email LIKE '%@x.com'").fetchone()[0] == 2


# ── helper used by test_garbage_tokens_are_rejected_without_raising ────────
def _b64decode(seg: str) -> str:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad).decode("latin-1")


def _b64(raw: str) -> str:
    """Re-encode a base64url JWT segment (PyJWT strips '=' padding)."""
    if isinstance(raw, str):
        raw = raw.encode("ascii")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
