import os
import httpx
from typing import Dict, Any

from engine.key_vault import KeyVault

def _headers():
    token = KeyVault.get("crmx_api_key") or ""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Version": "2021-07-28",
    }

async def upsert_contact(lead: Dict[str, Any]) -> Dict[str, Any]:
    base = (KeyVault.get("crmx_base_url") or "https://services.leadconnectorhq.com").rstrip("/")
    location_id = KeyVault.get("crmx_location_id") or ""
    url = f"{base}/contacts/"  # placeholder; replace with your tenant's endpoint

    payload = {
        "locationId": location_id,
        "firstName": lead.get("first_name",""),
        "lastName": lead.get("last_name",""),
        "email": lead.get("email",""),
        "phone": lead.get("phone",""),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload, headers=_headers())
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "body": r.text}
        return {"ok": True, "status": r.status_code, "body": r.json()}
