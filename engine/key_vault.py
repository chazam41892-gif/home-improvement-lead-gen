from __future__ import annotations

import os
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

VAULT_FILE = os.environ.get("VAULT_FILE", "data/key_vault.json")

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
    _entries: Dict[str, List[VaultEntry]] = {}
    _loaded = False

    @classmethod
    def load(cls):
        if cls._loaded:
            return
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
                for svc, keys_list in data.items():
                    for entry in keys_list:
                        cls._entries.setdefault(svc, []).append(
                            VaultEntry(service=svc, key=entry["key"], label=entry.get("label", "user"), source="vault")
                        )
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        cls._loaded = True
        logger.info("KeyVault loaded — %d services configured", len(cls._entries))

    @classmethod
    def _save(cls):
        vault_path = os.path.join(os.path.dirname(__file__) or ".", "..", VAULT_FILE)
        os.makedirs(os.path.dirname(vault_path), exist_ok=True)
        data = {}
        for svc, entries in cls._entries.items():
            user_entries = [e for e in entries if e.source == "vault"]
            if user_entries:
                data[svc] = [{"key": e.key, "label": e.label} for e in user_entries]
        with open(vault_path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def get(cls, service: str) -> Optional[str]:
        cls.load()
        entries = cls._entries.get(service, [])
        if entries:
            return entries[0].key
        return None

    @classmethod
    def list(cls) -> Dict[str, list]:
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
