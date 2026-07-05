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

    async def push_leads(
        self, leads: list[dict], provider: str = "hubspot", config: dict | None = None
    ) -> list[dict]:
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

            elif provider == "gohighlevel":
                api_key = self._env.get("GOHIGHLEVEL_API_KEY")
                if not api_key:
                    logger.warning("GOHIGHLEVEL_API_KEY not configured — skipping push for %s", lead.get("id", ""))
                    continue
                logger.info("GoHighLevel push: sending payload for lead %s", lead.get("id", ""))

            elif provider == "pipedrive":
                api_key = self._env.get("PIPEDRIVE_API_KEY")
                if not api_key:
                    logger.warning("PIPEDRIVE_API_KEY not configured — skipping push for %s", lead.get("id", ""))
                    continue
                logger.info("Pipedrive push: sending payload for lead %s", lead.get("id", ""))

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
