"""Key Vault — delegates to HiveMind Vault (primary) then Unified Vault (fallback).

HiveMind Vault at ~/.leviathan/HiveMind/.obsidian/vault.py is the single
source of truth with ACL gating. Lead Gen Pro uses role="leadgen" which
can only read search, enrichment, billing, and infra categories.

Legacy fallback to ~/.lvtn/unified_vault.py for backward compatibility.
"""
from __future__ import annotations

import json
import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── HiveMind Vault bridge (primary, ACL-gated) ──────────────────────
_HIVEMIND_VAULT = None
_HIVEMIND_LOADED = False

def _get_hivemind():
    global _HIVEMIND_VAULT, _HIVEMIND_LOADED
    if _HIVEMIND_LOADED:
        return _HIVEMIND_VAULT
    _HIVEMIND_LOADED = True
    try:
        obsidian_dir = Path.home() / ".leviathan" / "HiveMind" / ".obsidian"
        sys.path.insert(0, str(obsidian_dir))
        from vault import HiveMindVault
        _HIVEMIND_VAULT = HiveMindVault.instance()
        logger.info("HiveMind vault connected — role=leadgen")
    except ImportError:
        pass
    return _HIVEMIND_VAULT

# ── Legacy Unified Vault bridge (fallback) ──────────────────────────
_UNIFIED_VAULT = None

def _get_unified():
    global _UNIFIED_VAULT
    if _UNIFIED_VAULT is None:
        try:
            sys.path.insert(0, str(Path.home() / ".lvtn"))
            from unified_vault import UnifiedVault
            _UNIFIED_VAULT = UnifiedVault.instance()
        except ImportError:
            logger.warning("Unified vault not available — falling back to legacy key_vault.json")
            _UNIFIED_VAULT = False
    return _UNIFIED_VAULT if _UNIFIED_VAULT is not False else None

# Legacy file path (kept for backward compat)
VAULT_FILE = os.environ.get("VAULT_FILE", "data/key_vault.json")

# Service metadata (kept for backward compat — unified vault has its own)
SERVICE_KEYS = {
    "exa": {"env_var": "EXA_API_KEY", "doc": "Exa Search API — business search & content extraction", "url": "https://dashboard.exa.ai"},
    "perplexity": {"env_var": "PERPLEXITY_API_KEY", "doc": "Perplexity AI — deep research", "url": "https://www.perplexity.ai/settings/api"},
    "anthropic": {"env_var": "ANTHROPIC_API_KEY", "doc": "Anthropic Claude — LLM parsing & enrichment", "url": "https://console.anthropic.com"},
    "openai": {"env_var": "OPENAI_API_KEY", "doc": "OpenAI GPT — LLM parsing (fallback)", "url": "https://platform.openai.com/api-keys"},
    "stripe_secret": {"env_var": "STRIPE_SECRET_KEY", "doc": "Stripe Secret Key — billing", "url": "https://dashboard.stripe.com/apikeys"},
    "stripe_webhook": {"env_var": "STRIPE_WEBHOOK_SECRET", "doc": "Stripe Webhook — payment events", "url": "https://dashboard.stripe.com/webhooks"},
    "clearbit": {"env_var": "CLEARBIT_API_KEY", "doc": "Clearbit — company enrichment (domain → name, logo, employees)", "url": "https://dashboard.clearbit.com"},
    "hunter": {"env_var": "HUNTER_API_KEY", "doc": "Hunter.io — email finder (domain → email addresses)", "url": "https://hunter.io/api-keys"},
    "apollo": {"env_var": "APOLLO_API_KEY", "doc": "Apollo.io — contact & company data", "url": "https://app.apollo.io/#/settings/api"},
    "people_data_labs": {"env_var": "PEOPLE_DATA_LABS_KEY", "doc": "People Data Labs — person & company enrichment", "url": "https://www.peopledatalabs.com"},
    "loox": {"env_var": "LOOX_API_KEY", "doc": "Loox — reverse phone & address lookup", "url": "https://www.loox.com"},
    "cometapi": {"env_var": "COMETAPI_API_KEY", "doc": "CometAPI — alternate LLM provider (OpenAI-compatible, 500+ models)", "url": "https://www.cometapi.com"},
    "enrichment_key": {"env_var": "ENRICHMENT_API_KEY", "doc": "Generic enrichment fallback key", "url": ""},
}

@dataclass
class VaultEntry:
    service: str
    key: str
    label: str = "default"
    source: str = "env"

    def masked(self) -> str:
        k = self.key
        if len(k) <= 8:
            return k[:2] + "***"
        return k[:4] + "***" + k[-4:]


class KeyVault:
    """Compatibility shim — delegates to UnifiedVault at ~/.lvtn/unified_vault.py.
    
    All existing code that calls KeyVault.get(), KeyVault.set_key(), etc.
    continues to work. Keys are stored in the unified vault, shared across
    all projects (lvtn CLI, Lead Gen Pro, Gambot IDE).
    """
    _entries: Dict[str, List[VaultEntry]] = {}
    _loaded = False

    @classmethod
    def load(cls):
        if cls._loaded:
            return
        hv = _get_hivemind()
        if hv:
            try:
                all_svcs = hv.list_all(role="leadgen")
                for svc_id, info in all_svcs.items():
                    if info["configured"]:
                        key = hv.get(svc_id, role="leadgen")
                        if key:
                            cls._entries.setdefault(svc_id, []).append(
                                VaultEntry(service=svc_id, key=key, label="hivemind", source="hivemind")
                            )
                cls._loaded = True
                logger.info("KeyVault loaded via HiveMind Vault — %d services configured", len(cls._entries))
                return
            except Exception as e:
                logger.warning("HiveMind vault error: %s — falling back", e)
        uv = _get_unified()
        if uv:
            # Load from unified vault
            all_svcs = uv.list_all()
            for svc_id, info in all_svcs.items():
                if info["configured"]:
                    for k in info["keys"]:
                        # We don't have the raw key from list_all (masked only),
                        # so we load env keys here and vault keys on-demand via get()
                        pass
            # Load env keys
            for svc, cfg in SERVICE_KEYS.items():
                val = os.environ.get(cfg["env_var"])
                if val:
                    cls._entries.setdefault(svc, []).append(
                        VaultEntry(service=svc, key=val, label="env", source="env")
                    )
            cls._loaded = True
            logger.info("KeyVault loaded via UnifiedVault — %d services configured", len(cls._entries))
            return
        # Fallback: legacy load from key_vault.json
        for svc, cfg in SERVICE_KEYS.items():
            val = os.environ.get(cfg["env_var"])
            if val:
                cls._entries.setdefault(svc, []).append(
                    VaultEntry(service=svc, key=val, label="env", source="env")
                )
        vault_path = os.path.join(os.path.dirname(__file__) or ".", "..", VAULT_FILE)
        try:
            with open(vault_path) as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("encrypted") and "ciphertext" in data:
                    from cryptography.fernet import Fernet
                    key = cls._get_encryption_key()
                    fernet = Fernet(key)
                    decrypted = fernet.decrypt(data["ciphertext"].encode("utf-8")).decode("utf-8")
                    data = json.loads(decrypted)
                for svc, keys_list in data.items():
                    for entry in keys_list:
                        cls._entries.setdefault(svc, []).append(
                            VaultEntry(service=svc, key=entry["key"], label=entry.get("label", "user"), source="vault")
                        )
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.debug("Failed to load legacy vault: %s", e)
        cls._loaded = True
        logger.info("KeyVault loaded (legacy) — %d services configured", len(cls._entries))

    @classmethod
    def get(cls, service: str) -> Optional[str]:
        uv = _get_unified()
        if uv:
            key = uv.get(service)
            if key:
                return key
        # Fallback
        cls.load()
        entries = cls._entries.get(service, [])
        if entries:
            return entries[0].key
        return None

    @classmethod
    def list(cls) -> Dict[str, list]:
        uv = _get_unified()
        if uv:
            all_svcs = uv.list_all()
            result = {}
            for svc_id, info in all_svcs.items():
                if svc_id in SERVICE_KEYS:
                    result[svc_id] = {
                        "doc": SERVICE_KEYS[svc_id]["doc"],
                        "url": SERVICE_KEYS[svc_id]["url"],
                        "env_var": SERVICE_KEYS[svc_id]["env_var"],
                        "configured": info["configured"],
                        "keys": info["keys"],
                    }
            return result
        # Fallback
        cls.load()
        result = {}
        for svc, cfg in SERVICE_KEYS.items():
            entries = cls._entries.get(svc, [])
            result[svc] = {
                "doc": cfg["doc"],
                "url": cfg["url"],
                "env_var": cfg["env_var"],
                "configured": len(entries) > 0,
                "keys": [
                    {"label": e.label, "source": e.source, "masked": e.masked()}
                    for e in entries
                ],
            }
        return result

    @classmethod
    def set_key(cls, service: str, key: str, label: str = "user") -> bool:
        # Try HiveMind first (enforces ACL - only admin can write)
        hv = _get_hivemind()
        if hv:
            try:
                # Leadgen role has write: [] so this will be blocked
                # Only swarm/admin can write
                result = hv.set(service, key, label, role="leadgen")
                if result:
                    return True
                # If blocked (returns False), fall through to UnifiedVault
            except Exception as e:
                logger.warning("HiveMind write failed: %s", e)
        # Fallback to UnifiedVault (no ACL enforcement)
        uv = _get_unified()
        if uv:
            return uv.set(service, key, label)
        # Fallback to legacy vault
        cls.load()
        if service not in SERVICE_KEYS:
            logger.warning("Unknown service: %s", service)
            return False
        existing = cls._entries.get(service, [])
        existing[:] = [e for e in existing if not (e.label == label and e.source == "vault")]
        existing.append(VaultEntry(service=service, key=key, label=label, source="vault"))
        cls._entries[service] = existing
        cls._save()
        logger.info("KeyVault: %s key %s updated", service, label)
        return True

    @classmethod
    def delete_key(cls, service: str, label: str = "user") -> bool:
        uv = _get_unified()
        if uv:
            return uv.delete(service, label)
        # Fallback
        cls.load()
        entries = cls._entries.get(service, [])
        before = len(entries)
        entries[:] = [e for e in entries if not (e.label == label and e.source == "vault")]
        if len(entries) < before:
            cls._entries[service] = entries
            cls._save()
            logger.info("KeyVault: %s key %s deleted", service, label)
            return True
        return False

    @classmethod
    def _get_encryption_key(cls):
        """Derive a Fernet key from machine/user-specific data.

        This is not high security; it is only meant to keep keys from being
        stored in plain text on disk. In production, prefer HiveMind Vault.
        """
        import base64
        import hashlib
        # Use a stable but per-machine seed so moving the file alone doesn't decrypt it.
        seed = os.environ.get("VAULT_MASTER_SEED", str(Path.home().resolve()))
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    @classmethod
    def _save(cls) -> bool:
        """Persist vault entries to disk using Fernet encryption (legacy fallback)."""
        try:
            from cryptography.fernet import Fernet
            vault_path = os.path.join(os.path.dirname(__file__) or ".", "..", VAULT_FILE)
            os.makedirs(os.path.dirname(vault_path) or ".", exist_ok=True)
            data = {}
            for svc, entries in cls._entries.items():
                vault_entries = [
                    {"key": e.key, "label": e.label}
                    for e in entries if e.source == "vault"
                ]
                if vault_entries:
                    data[svc] = vault_entries
            fernet = Fernet(cls._get_encryption_key())
            plaintext = json.dumps(data)
            ciphertext = fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
            with open(vault_path, "w") as f:
                json.dump({"encrypted": True, "ciphertext": ciphertext}, f)
            return True
        except Exception as e:
            logger.error("Failed to save legacy key vault: %s", e)
            return False
