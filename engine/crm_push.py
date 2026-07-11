from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CrmPush:
    def __init__(self) -> None:
        self._history: list[dict] = []
        self._env: dict = {}

    def set_env(self, env: dict) -> None:
        self._env = env

    async def push_lead(self, lead: dict, provider: str = "hubspot", config: dict | None = None) -> dict:
        result = await self.push_leads([lead], provider=provider, config=config)
        return {"ok": True, "provider": provider, "lead_id": lead.get("lead_id", lead.get("id", ""))}

    async def push_leads(
        self, leads: list[dict], provider: str = "hubspot", config: dict | None = None
    ) -> list[dict]:
        import httpx
        cfg = config or {}
        min_score = cfg.get("min_score", 70)

        for lead in leads:
            if lead.get("score", 0) < min_score:
                continue

            payload = self._build_payload(lead, provider)

            if provider == "hubspot":
                api_key = self._env.get("HUBSPOT_API_KEY")
                if not api_key:
                    logger.warning("HUBSPOT_API_KEY not configured — skipping push for %s", lead.get("id", ""))
                    continue
                logger.info("HubSpot push: sending payload for lead %s", lead.get("id", ""))
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            "https://api.hubapi.com/crm/v3/objects/contacts",
                            json=payload,
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"
                            }
                        )
                        if resp.status_code >= 400:
                            logger.error("HubSpot CRM push failed: %s", resp.text)
                        else:
                            logger.info("HubSpot CRM push succeeded for lead %s", lead.get("id"))
                except Exception as e:
                    logger.error("HubSpot request failed: %s", e)

            elif provider == "gohighlevel":
                logger.info("GoHighLevel push: sending payload for lead %s", lead.get("id", ""))
                try:
                    from crm_plus.crmx import upsert_contact
                    res = await upsert_contact(lead)
                    if not res.get("ok"):
                        logger.error("GoHighLevel CRM push failed: %s", res.get("body"))
                    else:
                        logger.info("GoHighLevel CRM push succeeded for lead %s", lead.get("id"))
                except Exception as e:
                    logger.error("GoHighLevel request failed: %s", e)

            elif provider == "pipedrive":
                api_key = self._env.get("PIPEDRIVE_API_KEY")
                if not api_key:
                    logger.warning("PIPEDRIVE_API_KEY not configured — skipping push for %s", lead.get("id", ""))
                    continue
                logger.info("Pipedrive push: sending payload for lead %s", lead.get("id", ""))
                try:
                    pd_payload = {
                        "name": lead.get("title") or lead.get("name") or "Contact",
                        "email": [lead.get("email")] if lead.get("email") else [],
                        "phone": [lead.get("phone")] if lead.get("phone") else [],
                    }
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            f"https://api.pipedrive.com/v1/persons?api_token={api_key}",
                            json=pd_payload,
                            headers={"Content-Type": "application/json"}
                        )
                        if resp.status_code >= 400:
                            logger.error("Pipedrive CRM push failed: %s", resp.text)
                        else:
                            logger.info("Pipedrive CRM push succeeded for lead %s", lead.get("id"))
                except Exception as e:
                    logger.error("Pipedrive request failed: %s", e)

            self._history.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": provider,
                    "lead_id": lead.get("id", ""),
                    "payload": payload,
                }
            )

        return leads

    def get_history(self, limit: int = 20) -> list[dict]:
        return self._history[-limit:]

    def get_stats(self) -> dict:
        total_pushes = len(self._history)
        total_leads_pushed = total_pushes
        last_push = (
            self._history[-1]["timestamp"]
            if self._history
            else None
        )
        return {
            "total_pushes": total_pushes,
            "total_leads_pushed": total_leads_pushed,
            "last_push": last_push,
        }

    @staticmethod
    def _build_payload(lead: dict, provider: str) -> dict:
        properties = {
            "firstname": lead.get("first_name") or lead.get("name", "").split(" ", 1)[0],
            "lastname": lead.get("last_name")
            or (
                lead.get("name", "").split(" ", 1)[1]
                if " " in lead.get("name", "")
                else ""
            ),
            "phone": lead.get("phone", ""),
            "email": lead.get("email", ""),
            "company": lead.get("company", ""),
            "lead_source": lead.get("source", "web"),
            "hs_lead_status": "NEW",
        }

        if provider == "pipedrive":
            return {
                "properties": properties,
                "note": lead.get("notes", ""),
            }

        return {
            "properties": properties,
        }
