#!/usr/bin/env python3
"""
Enrichment utilities – fetch additional contact & company data
from third‑party services (Clearbit, Hunter, optional LinkedIn).

All keys are read from `config.yaml` (or .env as a fallback) so
no secrets are hard‑coded.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Any, Optional

import httpx

# ----------------------------------------------------------------------
# Helper – load config (simple yaml parser, no extra deps)
# ----------------------------------------------------------------------
def _load_yaml(path: str = "config.yaml") -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:  # pragma: no cover
        raise RuntimeError("PyYAML is required for config.yaml parsing")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

_CFG = _load_yaml()

# ----------------------------------------------------------------------
# Clearbit enrichment
# ----------------------------------------------------------------------
CLEARBIT_URL = "https://person.clearbit.com/v2/people/find"
CLEARBIT_KEY = os.getenv("CLEARBIT_API_KEY", _CFG.get("clearbit", {}).get("api_key"))

async def enrich_clearbit(email: str) -> Dict[str, Any]:
    if not CLEARBIT_KEY:
        return {}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(CLEARBIT_URL, params={"email": email},
                               headers={"Authorization": f"Bearer {CLEARBIT_KEY}"})
        if resp.status_code != 200:
            return {}
        return resp.json()


# ----------------------------------------------------------------------
# Hunter enrichment (email verification & discovery)
# ----------------------------------------------------------------------
HUNTER_URL = "https://api.hunter.io/v2/email-finder"
HUNTER_KEY = os.getenv("HUNTER_API_KEY", _CFG.get("hunter", {}).get("api_key"))

async def enrich_hunter(domain: str, first_name: str, last_name: str) -> Dict[str, Any]:
    if not HUNTER_KEY:
        return {}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            HUNTER_URL,
            params={
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": HUNTER_KEY,
            },
        )
        if resp.status_code != 200:
            return {}
        return resp.json()


# ----------------------------------------------------------------------
# Public façade – combine the services
# ----------------------------------------------------------------------
async def enrich_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a lead dict in‑place and return the updated dict.
    Expected keys: `email`, `website`, `contact_first_name`, `contact_last_name`.
    """
    enriched = lead.copy()

    # 1️⃣ Clearbit – best for person data
    if lead.get("email"):
        clearbit_data = await enrich_clearbit(lead["email"])
        enriched.update(clearbit_data)

    # 2️⃣ Hunter – fallback if we have a domain but no email
    if not lead.get("email") and lead.get("website"):
        domain = lead["website"].split("//")[-1].split("/")[0]
        hunter_data = await enrich_hunter(
            domain,
            lead.get("contact_first_name", ""),
            lead.get("contact_last_name", ""),
        )
        # Hunter nests the result under `data`
        if hunter_data.get("data"):
            enriched["email"] = hunter_data["data"].get("email")
            enriched["first_name"] = hunter_data["data"].get("first_name")
            enriched["last_name"] = hunter_data["data"].get("last_name")

    # Add a quick flag for downstream scoring
    enriched["enrichment_done"] = True
    return enriched