from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class CrmPush:
    def __init__(self) -> None:
        self._history: list[dict] = []

    def set_env(self, env: dict) -> None:
        # Kept for compatibility; keys now read via KeyVault
        pass

    def _get_key(self, service: str, env_var: str) -> str | None:
        from engine.key_vault import KeyVault
        key = KeyVault.get(service)
        if key:
            return key
        return env_val if (env_val := __import__("os").getenv(env_var)) else None

    async def push_lead(self, lead: dict, provider: str = "hubspot", config: dict | None = None) -> dict:
        results = await self.push_leads([lead], provider=provider, config=config)
        return results[0] if results else {"ok": False, "provider": provider, "lead_id": lead.get("id", ""), "error": "No leads pushed"}

    async def push_leads(
        self, leads: list[dict], provider: str = "hubspot", config: dict | None = None
    ) -> list[dict]:
        import httpx
        cfg = config or {}
        min_score = cfg.get("min_score", 70)
        results: list[dict] = []

        for lead in leads:
            lead_id = lead.get("id", "")
            if lead.get("score", 0) < min_score:
                results.append({"ok": False, "provider": provider, "lead_id": lead_id, "error": "Below min score", "skipped": True})
                continue

            result: Dict[str, Any] = {"ok": False, "provider": provider, "lead_id": lead_id}

            if provider == "hubspot":
                api_key = self._get_key("hubspot", "HUBSPOT_API_KEY")
                if not api_key:
                    result["error"] = "HUBSPOT_API_KEY not configured"
                    logger.warning(result["error"])
                    results.append(result)
                    continue
                payload = {"properties": self._build_hubspot_properties(lead)}
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            "https://api.hubapi.com/crm/v3/objects/contacts",
                            json=payload,
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        )
                    if resp.status_code >= 400:
                        result["error"] = resp.text[:300]
                        logger.error("HubSpot push failed: %s", resp.text)
                    else:
                        data = resp.json()
                        result["ok"] = True
                        result["remote_id"] = data.get("id")
                        logger.info("HubSpot push succeeded for lead %s", lead_id)
                except Exception as e:
                    result["error"] = str(e)
                    logger.error("HubSpot request failed: %s", e)

            elif provider == "gohighlevel":
                try:
                    from crm_plus.crmx import upsert_contact
                    res = await upsert_contact(lead)
                    if res.get("ok"):
                        result["ok"] = True
                        result["remote_id"] = res.get("id")
                        logger.info("GoHighLevel push succeeded for lead %s", lead_id)
                    else:
                        result["error"] = res.get("body", "GoHighLevel error")
                        logger.error("GoHighLevel push failed: %s", result["error"])
                except Exception as e:
                    result["error"] = str(e)
                    logger.error("GoHighLevel request failed: %s", e)

            elif provider == "pipedrive":
                api_key = self._get_key("pipedrive", "PIPEDRIVE_API_KEY")
                if not api_key:
                    result["error"] = "PIPEDRIVE_API_KEY not configured"
                    logger.warning(result["error"])
                    results.append(result)
                    continue
                payload = self._build_pipedrive_payload(lead)
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            f"https://api.pipedrive.com/v1/persons?api_token={api_key}",
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        )
                    if resp.status_code >= 400:
                        result["error"] = resp.text[:300]
                        logger.error("Pipedrive push failed: %s", resp.text)
                    else:
                        data = resp.json()
                        result["ok"] = True
                        result["remote_id"] = data.get("data", {}).get("id")
                        logger.info("Pipedrive push succeeded for lead %s", lead_id)
                except Exception as e:
                    result["error"] = str(e)
                    logger.error("Pipedrive request failed: %s", e)
            else:
                result["error"] = f"Unknown CRM provider: {provider}"

            self._history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": provider,
                "lead_id": lead_id,
                "ok": result.get("ok", False),
                "error": result.get("error"),
            })
            results.append(result)

        return results

    def get_history(self, limit: int = 20) -> list[dict]:
        return self._history[-limit:]

    def get_stats(self) -> dict:
        total = len(self._history)
        successful = sum(1 for h in self._history if h.get("ok"))
        last = self._history[-1] if self._history else None
        return {
            "total_pushes": total,
            "successful_pushes": successful,
            "failed_pushes": total - successful,
            "last_push": last["timestamp"] if last else None,
        }

    @staticmethod
    def _build_hubspot_properties(lead: dict) -> dict:
        name = lead.get("title") or lead.get("name", "")
        parts = name.split(" ", 1)
        return {
            "firstname": lead.get("first_name") or parts[0],
            "lastname": lead.get("last_name") or (parts[1] if len(parts) > 1 else ""),
            "phone": lead.get("phone", ""),
            "email": lead.get("email", ""),
            "company": lead.get("company", lead.get("business_name", "")),
            "lead_source": lead.get("source", "web"),
            "hs_lead_status": "NEW",
            "notes": lead.get("notes", ""),
        }

    @staticmethod
    def _build_pipedrive_payload(lead: dict) -> dict:
        name = lead.get("title") or lead.get("name") or "Contact"
        return {
            "name": name,
            "email": [{"value": lead.get("email", ""), "primary": True}] if lead.get("email") else [],
            "phone": [{"value": lead.get("phone", ""), "primary": True}] if lead.get("phone") else [],
            "add_time": datetime.now(timezone.utc).isoformat(),
        }
