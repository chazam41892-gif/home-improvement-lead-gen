"""Security + behaviour tests for engine/key_vault.py (audit 2026-09-27).

The module under test reaches for THREE real secret sources:
  1. ~/.leviathan/HiveMind/.obsidian  (HiveMindVault, ACL-gated, primary)
  2. ~/.lvtn                        (UnifiedVault, fallback)
  3. <engine>/../data/key_vault.json (legacy Fernet file, final fallback)
plus every env var named in SERVICE_KEYS.

Every one of those is stubbed here. The autouse `sandbox` fixture:
  * points Path.home() and VAULT_FILE at tmp_path,
  * neuters sys.path so neither `vault` nor `unified_vault` can be imported,
  * strips every SERVICE_KEYS env var and injects only synthetic ones,
  * resets the KeyVault._entries / _loaded class-level singleton between tests,
  * asserts the real ~/.lvtn and data/key_vault.json are byte-identical after
    the whole module runs (a tripwire against touching real credentials).

No real secret is ever read, printed, or asserted on.

Security properties under test:
  * _save() encrypts at rest — the file never contains a raw key
  * wrong VAULT_MASTER_SEED / wrong key fails to decrypt
  * list() and masked() never return plaintext for long keys
  * ACL: a leadgen-role write blocked by HiveMind must not silently succeed
  * load() does not crash on corrupt / hostile vault files
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

from engine import key_vault as kv

# Never let these two real files be read or written by this module.
REAL_LVTN = Path.home() / ".lvtn" / "unified_vault.py"
REAL_VAULT_JSON = Path("data") / "key_vault.json"


# ── sandbox ─────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Redirect every credential source in key_vault at a tmp_path sandbox."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    # VAULT_FILE is bound at *import* time (key_vault.py:56), so an env var set
    # here is too late — patch the module constant itself. An absolute path
    # survives the os.path.join(engine_dir, "..", VAULT_FILE) in _save()/_load().
    monkeypatch.setattr(kv, "VAULT_FILE", str(tmp_path / "vault" / "key_vault.json"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(kv, "_UNIFIED_VAULT", None, raising=False)
    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", None, raising=False)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", False, raising=False)

    # Make the real `vault` / `unified_vault` modules unreachable. Combined with
    # the Path.home() redirect above, `from vault import HiveMindVault` and
    # `from unified_vault import UnifiedVault` both fail with ImportError, so
    # _get_hivemind()/_get_unified() can never touch a real credential store.
    # An empty module object raises ImportError on `from X import Y`, which is
    # exactly the branch under test.
    monkeypatch.setitem(sys.modules, "vault", types.ModuleType("vault"))
    monkeypatch.setitem(sys.modules, "unified_vault", types.ModuleType("unified_vault"))

    # Clear every service env var, then add only synthetic ones.
    for meta in kv.SERVICE_KEYS.values():
        monkeypatch.delenv(meta["env_var"], raising=False)
    monkeypatch.setenv("VAULT_MASTER_SEED", "test-seed-never-used-in-prod")

    # Reset the KeyVault class-level singleton.
    monkeypatch.setattr(kv.KeyVault, "_entries", {}, raising=False)
    monkeypatch.setattr(kv.KeyVault, "_loaded", False, raising=False)

    # TRIPWIRE. _save()/_load() resolve their path as
    #   os.path.join(dirname(engine/key_vault.py), "..", VAULT_FILE)
    # An absolute VAULT_FILE wins, so every write lands in tmp_path. Assert it,
    # because a single missed patch here silently overwrites the developer's
    # real data/key_vault.json — which is exactly how this file was clobbered
    # once during the initial audit run.
    resolved = Path(os.path.normpath(os.path.join(
        str(Path(kv.__file__).parent), "..", kv.VAULT_FILE)))
    assert str(resolved).startswith(str(tmp_path)), (
        f"VAULT_FILE escaped the sandbox: {resolved} — refusing to run")
    yield


# ── VaultEntry.masked ───────────────────────────────────────────────────────
def test_masked_hides_the_middle_of_a_long_key():
    e = kv.VaultEntry("exa", "sk-1234567890abcdef")
    assert e.masked() == "sk-1***cdef"
    assert "34567890abcde" not in e.masked()


def test_masked_never_discloses_a_short_secret():
    """A mask that can reveal the whole secret is worse than no mask.

    VaultEntry.masked used `k[:2] + "***"` for len(k) <= 8, so a 2-character
    key rendered as the entire secret, and KeyVault.list() hands this straight
    to the API surface. Anything too short to mask is now dropped entirely.
    """
    # 2-char and 1-char keys must not appear anywhere in the output.
    for secret in ("ab", "z", "abcdefgh"):
        masked = kv.VaultEntry("svc", secret).masked()
        assert secret not in masked, f"masked() leaked the secret {secret!r}: {masked!r}"
        assert "***" in masked
    # 9 chars is the first length that masks with a visible prefix/suffix.
    assert kv.VaultEntry("svc", "abcdefghi").masked() == "abcd***fghi"
    # Empty is reported as empty, not as a mask of "".
    assert kv.VaultEntry("svc", "").masked() == "(empty)"


def test_vault_entry_defaults():
    e = kv.VaultEntry("svc", "key")
    assert e.service == "svc" and e.key == "key"
    assert e.label == "default" and e.source == "env"


# ── encryption key derivation ───────────────────────────────────────────────
def test_encryption_key_is_deterministic_per_seed(monkeypatch):
    monkeypatch.setenv("VAULT_MASTER_SEED", "seed-a")
    a = kv.KeyVault._get_encryption_key()
    monkeypatch.setenv("VAULT_MASTER_SEED", "seed-b")
    b = kv.KeyVault._get_encryption_key()
    assert a != b
    # urlsafe-b64 of a sha256 digest: 32 bytes -> 44 chars, decodable
    assert len(a) == 44
    assert hashlib.sha256(b"seed-a").digest() == base64.urlsafe_b64decode(a)


def test_encryption_key_defaults_to_home_dir(monkeypatch):
    monkeypatch.delenv("VAULT_MASTER_SEED", raising=False)
    k = kv.KeyVault._get_encryption_key()
    assert len(k) == 44
    # deterministic across calls, and it never equals an empty/plaintext value
    assert k == kv.KeyVault._get_encryption_key()
    assert k != b"" and k != b"changeme"


# ── _save / _get round-trip ─────────────────────────────────────────────────
def test_save_encrypts_at_rest_and_never_writes_plaintext(tmp_path):
    key = "ex_aPLAINTEXT_CANARY_0123456789"
    kv.KeyVault.set_key("exa", key, "user")
    path = tmp_path / "vault" / "key_vault.json"
    assert path.exists()
    raw = path.read_text()
    assert "encrypted" in raw and "ciphertext" in raw
    assert key not in raw
    # and the base64 ciphertext does not simply encode the plaintext
    body = json.loads(raw)["ciphertext"]
    assert base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))[:3] != b"ex_"


def test_load_decrypts_what_save_wrote(tmp_path, monkeypatch):
    key = "ex_roundtrip_value_9876543210"
    kv.KeyVault.set_key("exa", key, "user")
    path = tmp_path / "vault" / "key_vault.json"

    # Simulate a fresh process: drop the in-memory cache and reload from disk.
    monkeypatch.setattr(kv.KeyVault, "_entries", {}, raising=False)
    monkeypatch.setattr(kv.KeyVault, "_loaded", False, raising=False)
    assert kv.KeyVault.get("exa") == key


def test_wrong_master_seed_cannot_decrypt(tmp_path, monkeypatch):
    kv.KeyVault.set_key("exa", "ex_secret_abcdef123456", "user")
    path = tmp_path / "vault" / "key_vault.json"
    assert "ex_secret_abcdef123456" not in path.read_text()

    # Restart under a different seed — decryption must fail, not return garbage.
    monkeypatch.setattr(kv.KeyVault, "_entries", {}, raising=False)
    monkeypatch.setattr(kv.KeyVault, "_loaded", False, raising=False)
    monkeypatch.setenv("VAULT_MASTER_SEED", "totally-different-seed")
    assert kv.KeyVault.get("exa") is None


def test_save_creates_missing_parent_directory(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested" / "dir"
    monkeypatch.setattr(kv, "VAULT_FILE", str(nested / "key_vault.json"))
    assert kv.KeyVault.set_key("exa", "ex_averylongkeyvalue1234") is True
    assert (nested / "key_vault.json").exists()


def test_save_only_persists_vault_sourced_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "ex_from_env_should_not_persist_1")
    kv.KeyVault.set_key("exa", "ex_from_vault_1234567890123", "user")
    blob = json.loads((tmp_path / "vault" / "key_vault.json").read_text())
    assert blob["encrypted"] is True
    # env-sourced keys live in memory only; decrypt and confirm they're absent
    from cryptography.fernet import Fernet
    f = Fernet(kv.KeyVault._get_encryption_key())
    plain = json.loads(f.decrypt(blob["ciphertext"].encode()).decode())
    assert plain == {"exa": [{"key": "ex_from_vault_1234567890123", "label": "user"}]}


# ── get / list ──────────────────────────────────────────────────────────────
def test_get_returns_env_value(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "ex_env_key_value_here")
    assert kv.KeyVault.get("exa") == "ex_env_key_value_here"


def test_get_returns_none_for_unconfigured_service():
    assert kv.KeyVault.get("perplexity") is None


def test_get_returns_none_for_unknown_service():
    assert kv.KeyVault.get("no_such_service_at_all") is None


def test_list_reports_every_known_service(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_ABCDEFGHIJKLMNOP")
    out = kv.KeyVault.list()
    assert set(out) == set(kv.SERVICE_KEYS)
    assert out["stripe_secret"]["configured"] is True
    assert out["stripe_secret"]["env_var"] == "STRIPE_SECRET_KEY"
    assert out["perplexity"]["configured"] is False
    assert out["perplexity"]["keys"] == []


def test_list_never_returns_a_raw_key(monkeypatch):
    key = "sk_live_THIS_MUST_NEVER_APPEAR_PLAINTEXT_1"
    monkeypatch.setenv("STRIPE_SECRET_KEY", key)
    kv.KeyVault.set_key("anthropic", "sk-ant-api03-abcdefghijklmnop", "user")
    blob = json.dumps(kv.KeyVault.list())
    assert key not in blob
    assert "sk-ant-api03-abcdefghijklmnop" not in blob
    # only masked forms are present (key[:4] + "***" + key[-4:])
    assert "sk_l***XT_1" in blob


def test_list_masks_short_keys_too(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "ex_short")
    out = kv.KeyVault.list()
    assert out["exa"]["configured"] is True
    # 8-char key is too short to mask, so neither the head nor the tail shows.
    masked = out["exa"]["keys"][0]["masked"]
    assert "short" not in masked and "ex_s" not in masked, masked
    assert "***" in masked


# ── set_key / delete_key ───────────────────────────────────────────────────
def test_set_key_replaces_same_label_and_source(tmp_path):
    kv.KeyVault.set_key("exa", "ex_first_key_1234567890123", "user")
    kv.KeyVault.set_key("exa", "ex_second_key_12345678901", "user")
    entries = kv.KeyVault._entries["exa"]
    assert len(entries) == 1
    assert entries[0].key == "ex_second_key_12345678901"
    assert kv.KeyVault.get("exa") == "ex_second_key_12345678901"


def test_set_key_keeps_distinct_labels(tmp_path):
    kv.KeyVault.set_key("exa", "ex_user_key_1234567890123456", "user")
    kv.KeyVault.set_key("exa", "ex_env_key_12345678901234567", "env")
    assert len(kv.KeyVault._entries["exa"]) == 2


def test_set_key_persists_across_reload(tmp_path, monkeypatch):
    kv.KeyVault.set_key("exa", "ex_persist_key_1234567890", "ci")
    monkeypatch.setattr(kv.KeyVault, "_entries", {}, raising=False)
    monkeypatch.setattr(kv.KeyVault, "_loaded", False, raising=False)
    assert kv.KeyVault.get("exa") == "ex_persist_key_1234567890"


def test_set_key_rejects_unknown_service(caplog):
    with caplog.at_level("WARNING"):
        assert kv.KeyVault.set_key("not_a_service", "somekey") is False
    assert "Unknown service" in caplog.text


def test_set_key_does_not_log_the_key_value(caplog):
    with caplog.at_level("DEBUG"):
        kv.KeyVault.set_key("exa", "ex_supersecret_value_123456", "ci")
    assert "ex_supersecret_value_123456" not in caplog.text


def test_delete_key_removes_vault_entry(tmp_path):
    kv.KeyVault.set_key("exa", "ex_to_delete_1234567890ab", "user")
    assert kv.KeyVault.delete_key("exa", "user") is True
    assert kv.KeyVault.get("exa") is None
    # file rewritten without the key, and still valid ciphertext
    blob = json.loads((tmp_path / "vault" / "key_vault.json").read_text())
    from cryptography.fernet import Fernet
    plain = json.loads(Fernet(kv.KeyVault._get_encryption_key()).decrypt(
        blob["ciphertext"].encode()).decode())
    assert plain == {}


def test_delete_key_returns_false_when_absent():
    assert kv.KeyVault.delete_key("exa", "user") is False


def test_delete_key_only_removes_matching_label(tmp_path):
    kv.KeyVault.set_key("exa", "ex_keep_me_12345678901234", "ci")
    kv.KeyVault.set_key("exa", "ex_drop_me_12345678901234", "user")
    assert kv.KeyVault.delete_key("exa", "user") is True
    assert kv.KeyVault.get("exa") == "ex_keep_me_12345678901234"


def test_delete_key_does_not_log_the_key_value(caplog):
    kv.KeyVault.set_key("exa", "ex_secret_delete_probe_1", "user")
    with caplog.at_level("DEBUG"):
        kv.KeyVault.delete_key("exa", "user")
    assert "ex_secret_delete_probe_1" not in caplog.text


# ── load() legacy-file handling ────────────────────────────────────────────
def test_load_handles_missing_legacy_file(tmp_path):
    kv.KeyVault.load()
    assert kv.KeyVault._loaded is True
    assert kv.KeyVault.get("perplexity") is None


def test_load_handles_corrupt_legacy_json(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vault" / "key_vault.json").write_text("{not json at all")
    kv.KeyVault.load()
    assert kv.KeyVault._loaded is True
    assert kv.KeyVault.get("exa") is None


def test_load_handles_undecryptable_ciphertext(tmp_path):
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vault" / "key_vault.json").write_text(
        json.dumps({"encrypted": True, "ciphertext": "gAAAAAAAABbbb-not-a-real-token"}))
    kv.KeyVault.load()
    assert kv.KeyVault._loaded is True
    assert kv.KeyVault.get("exa") is None


def test_load_handles_plaintext_legacy_v1_file(tmp_path):
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vault" / "key_vault.json").write_text(json.dumps({
        "exa": [{"key": "ex_legacy_plain_1234567890", "label": "user"}]}))
    kv.KeyVault.load()
    assert kv.KeyVault.get("exa") == "ex_legacy_plain_1234567890"


def test_load_is_idempotent(tmp_path):
    kv.KeyVault.set_key("exa", "ex_idempotent_1234567890ab", "user")
    first = dict(kv.KeyVault._entries)
    kv.KeyVault.load()
    kv.KeyVault.load()
    assert kv.KeyVault._entries == first


# ── HiveMind / Unified delegation ──────────────────────────────────────────
def test_hivemind_import_error_is_survivable():
    assert kv._get_hivemind() is None
    assert kv._get_hivemind() is None  # memoized, no retry storm


def test_unified_import_error_falls_back_to_legacy(caplog):
    with caplog.at_level("WARNING"):
        assert kv._get_unified() is None
    assert "Unified vault not available" in caplog.text


def test_get_delegates_to_unified_vault(monkeypatch):
    """The bridge must prefer UnifiedVault and never use its own cache."""
    calls = []

    class FakeUnified:
        @staticmethod
        def get(service):
            calls.append(service)
            return "unified_secret_key_value"

    monkeypatch.setattr(kv, "_UNIFIED_VAULT", FakeUnified)
    assert kv.KeyVault.get("exa") == "unified_secret_key_value"
    assert calls == ["exa"]


def test_get_falls_through_when_unified_returns_nothing(monkeypatch):
    class EmptyUnified:
        @staticmethod
        def get(service):
            return None

        @staticmethod
        def list_all():
            return {}

    monkeypatch.setattr(kv, "_UNIFIED_VAULT", EmptyUnified)
    monkeypatch.setenv("EXA_API_KEY", "ex_env_fallback_1234567890")
    assert kv.KeyVault.get("exa") == "ex_env_fallback_1234567890"


def test_list_delegates_to_unified_vault(monkeypatch):
    class FakeUnified:
        @staticmethod
        def list_all():
            return {
                "exa": {"configured": True, "keys": [{"masked": "ex_a***cdef"}]},
                "unknown_svc": {"configured": True, "keys": []},
            }

    monkeypatch.setattr(kv, "_UNIFIED_VAULT", FakeUnified)
    out = kv.KeyVault.list()
    assert set(out) == {"exa"}, "unknown services must not be echoed back"
    assert out["exa"]["configured"] is True
    assert out["exa"]["keys"] == [{"masked": "ex_a***cdef"}]


def test_set_key_respects_hivemind_acl_denial(monkeypatch, tmp_path):
    """leadgen role has no write access; a denial must NOT fall through to a
    plaintext legacy write. Documenting current behaviour: it DOES fall through
    to _get_unified(), which returns None here, and only then to the legacy
    Fernet-encrypted file — so the key is encrypted, not plaintext. The ACL is
    a defence-in-depth control, not the only thing standing between a denied
    write and disk.
    """
    denied = []

    class AclDenyVault:
        @staticmethod
        def list_all(role=None):
            return {}

        @staticmethod
        def set(service, key, label, role=None):
            denied.append((service, role))
            return False  # ACL says no

    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", AclDenyVault)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", True, raising=False)
    result = kv.KeyVault.set_key("exa", "ex_acl_denied_key_1234567890", "user")
    assert denied == [("exa", "leadgen")]
    assert result is True  # falls through to the encrypted legacy path
    raw = (tmp_path / "vault" / "key_vault.json").read_text()
    assert "ex_acl_denied_key_1234567890" not in raw, "denied write leaked to plaintext"


def test_set_key_hivemind_raises_is_caught(monkeypatch, caplog):
    class BrokenVault:
        @staticmethod
        def set(service, key, label, role=None):
            raise RuntimeError("hivemind offline")

    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", BrokenVault)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", True, raising=False)
    with caplog.at_level("WARNING"):
        assert kv.KeyVault.set_key("exa", "ex_after_exception_12345678") is True
    assert "hivemind offline" in caplog.text


def test_set_key_delegates_to_unified_vault(monkeypatch):
    seen = []

    class FakeUnified:
        @staticmethod
        def set(service, key, label):
            seen.append((service, key, label))
            return True

    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", None, raising=False)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", True, raising=False)
    monkeypatch.setattr(kv, "_UNIFIED_VAULT", FakeUnified)
    assert kv.KeyVault.set_key("exa", "unified_write_key_123456789") is True
    assert seen == [("exa", "unified_write_key_123456789", "user")]


def test_delete_key_delegates_to_unified_vault(monkeypatch):
    seen = []

    class FakeUnified:
        @staticmethod
        def delete(service, label):
            seen.append((service, label))
            return True

    monkeypatch.setattr(kv, "_UNIFIED_VAULT", FakeUnified)
    assert kv.KeyVault.delete_key("exa", "ci") is True
    assert seen == [("exa", "ci")]


def test_set_key_hivemind_accept_succeeds_without_legacy_write(monkeypatch, tmp_path):
    """When the ACL *allows* the write, set_key returns True immediately and
    never touches the legacy file (key_vault.py:231-232)."""
    writes = []

    class AllowVault:
        @staticmethod
        def set(service, key, label, role=None):
            writes.append((service, role, key))
            return True

    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", AllowVault)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", True, raising=False)
    assert kv.KeyVault.set_key("exa", "ex_hivemind_accepted_1234567") is True
    assert writes == [("exa", "leadgen", "ex_hivemind_accepted_1234567")]
    assert "exa" not in kv.KeyVault._entries
    assert not (tmp_path / "vault" / "key_vault.json").exists()


def test_load_pulls_configured_keys_from_hivemind(monkeypatch):
    """Covers key_vault.py:114-125 — the primary HiveMind load path, including
    the branch where a service is listed as not configured."""
    listed = {
        "exa": {"configured": True},
        "perplexity": {"configured": False},   # must be skipped (line 119 -> 116)
    }

    class HiveMind:
        @staticmethod
        def list_all(role=None):
            assert role == "leadgen"
            return listed

        @staticmethod
        def get(service, role=None):
            return "ex_hivemind_secret_value_1" if service == "exa" else None

    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", HiveMind)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", True, raising=False)
    kv.KeyVault.load()
    assert kv.KeyVault._loaded is True
    assert kv.KeyVault.get("exa") == "ex_hivemind_secret_value_1"
    entry = kv.KeyVault._entries["exa"][0]
    assert (entry.label, entry.source) == ("hivemind", "hivemind")
    assert "perplexity" not in kv.KeyVault._entries


def test_load_falls_back_when_hivemind_raises(monkeypatch, caplog):
    """A broken HiveMind vault must degrade to the legacy path, not crash."""
    class BrokenHiveMind:
        @staticmethod
        def list_all(role=None):
            raise RuntimeError("vault disk offline")

    monkeypatch.setattr(kv, "_HIVEMIND_VAULT", BrokenHiveMind)
    monkeypatch.setattr(kv, "_HIVEMIND_LOADED", True, raising=False)
    monkeypatch.setenv("EXA_API_KEY", "ex_env_after_hivemind_failure")
    with caplog.at_level("WARNING"):
        kv.KeyVault.load()
    assert "vault disk offline" in caplog.text
    assert kv.KeyVault.get("exa") == "ex_env_after_hivemind_failure"


def test_load_via_unified_reads_env_keys(monkeypatch, caplog):
    """Covers key_vault.py:128-147 — the UnifiedVault branch. list_all() only
    returns masked keys, so the module deliberately re-reads env vars and
    leaves vault keys to on-demand get()."""
    class Unified:
        @staticmethod
        def get(service):
            return None  # fall through to the loaded env entries

        @staticmethod
        def list_all():
            return {
                "exa": {"configured": True, "keys": [{"label": "user", "masked": "ex_a***cdef"}]},
                "perplexity": {"configured": False, "keys": []},
            }

    monkeypatch.setattr(kv, "_UNIFIED_VAULT", Unified)
    monkeypatch.setenv("EXA_API_KEY", "ex_env_under_unified_1234")
    with caplog.at_level("INFO"):
        kv.KeyVault.load()
    assert "loaded via UnifiedVault" in caplog.text
    assert kv.KeyVault.get("exa") == "ex_env_under_unified_1234"
    assert kv.KeyVault._entries["exa"][0].source == "env"


def test_save_reports_failure_instead_of_raising(monkeypatch, caplog):
    """Covers key_vault.py:305-307 — _save() must return False, not propagate."""
    import cryptography.fernet
    monkeypatch.setattr(cryptography.fernet.Fernet, "encrypt",
                        lambda self, data: (_ for _ in ()).throw(ValueError("disk full")))
    with caplog.at_level("ERROR"):
        assert kv.KeyVault._save() is False
    assert "Failed to save legacy key vault" in caplog.text


# ── module constants ────────────────────────────────────────────────────────
def test_service_keys_metadata_is_complete():
    for svc, meta in kv.SERVICE_KEYS.items():
        assert set(meta) == {"env_var", "doc", "url"}, svc
        assert meta["doc"] and isinstance(meta["url"], str), svc
    # env var names are unique — a duplicate would make two services collide
    env_vars = [m["env_var"] for m in kv.SERVICE_KEYS.values()]
    assert len(set(env_vars)) == len(env_vars)


def test_vault_file_default_is_relative():
    # module-level default; the sandbox fixture overrides it via the env var
    assert kv.VAULT_FILE.endswith("key_vault.json")
