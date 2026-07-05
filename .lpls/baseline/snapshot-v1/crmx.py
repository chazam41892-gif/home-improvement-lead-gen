import os
import httpx
from typing import Dict, Any

def _headers():
    token = os.getenv("CRMX_API_KEY", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Version": "2021-07-28",
    }

async def upsert_contact(lead: Dict[str, Any]) -> Dict[str, Any]:
    base = os.getenv("CRMX_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
    location_id = os.getenv("CRMX_LOCATION_ID", "")
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
