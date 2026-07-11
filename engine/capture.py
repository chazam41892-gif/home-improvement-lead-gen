from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from engine.database import Database

logger = logging.getLogger(__name__)


class _SimpleScore:
    def __init__(self, total: float = 50.0) -> None:
        self.total = total
        self.contact_completeness = 50.0
        self.business_presence = 50.0
        self.industry_relevance = 50.0
        self.location_match = 50.0
        self.enrichment_potential = 50.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "contact_completeness": round(self.contact_completeness, 1),
            "business_presence": round(self.business_presence, 1),
            "industry_relevance": round(self.industry_relevance, 1),
            "location_match": round(self.location_match, 1),
            "enrichment_potential": round(self.enrichment_potential, 1),
        }


class _CaptureLead:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.id = data["id"]
        self.title = data["title"]
        self.url = data.get("url", "")
        self.snippet = data.get("snippet", "")
        self.industry = data.get("industry", "home improvement")
        self.location = data.get("location", "")
        self.source = data.get("source", "landing_page")
        self.score = data.get("_score_obj", _SimpleScore(data.get("score", 50.0)))
        self.found_at = data.get("found_at", "")
        self.email = data.get("email", "")
        self.phone = data.get("phone", "")
        self.notes = data.get("notes", "")
        self.first_name = data.get("first_name", "")
        self.last_name = data.get("last_name", "")
        self.address = data.get("address", "")
        self.project_description = data.get("project_description", "")
        self.utm_source = data.get("utm_source", "")
        self.utm_medium = data.get("utm_medium", "")
        self.utm_campaign = data.get("utm_campaign", "")
        self.status = data.get("status", "new")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet[:300],
            "industry": self.industry,
            "location": self.location,
            "source": self.source,
            "score": self.score.total,
            "contact_score": self.score.contact_completeness,
            "business_score": self.score.business_presence,
            "industry_score": self.score.industry_relevance,
            "location_score": self.score.location_match,
            "enrichment_score": self.score.enrichment_potential,
            "score_breakdown": self.score.as_dict(),
            "found_at": self.found_at,
            "email": self.email,
            "phone": self.phone,
            "notes": self.notes,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "address": self.address,
            "project_description": self.project_description,
            "utm_source": self.utm_source,
            "utm_medium": self.utm_medium,
            "utm_campaign": self.utm_campaign,
            "status": self.status,
            "_capture_source": getattr(self, "_capture_source", ""),
        }


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_PHONE_DIGITS_RE = re.compile(r"\d")


def _extract_location(address: str) -> str:
    if not address:
        return ""
    lines = [l.strip() for l in address.strip().split("\n") if l.strip()]
    if len(lines) >= 2:
        return lines[-1]
    parts = address.split(",")
    if len(parts) >= 2:
        return parts[-1].strip()
    return address


def _truncate(text: str, max_len: int = 300) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


class LeadCaptureProcessor:
    def __init__(self, engine: Any, landing_pages: Optional[Dict[str, Any]] = None) -> None:
        self._engine = engine
        self._landing_pages = landing_pages or {}

    def process_submission(self, data: Dict[str, Any], source_page_id: str = "") -> Dict[str, Any]:
        name = (data.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "Name is required"}

        email = (data.get("email") or "").strip()
        if email and not _EMAIL_RE.match(email):
            return {"ok": False, "error": "Invalid email format"}

        phone = (data.get("phone") or "").strip()
        if phone:
            digits = _PHONE_DIGITS_RE.findall(phone)
            if len(digits) < 10:
                return {"ok": False, "error": "Phone number must have at least 10 digits"}

        address = (data.get("address") or "").strip()
        project_description = (data.get("project_description") or "").strip()

        name = name.strip().title()
        email = email.lower().strip() if email else ""
        phone = phone.strip()
        address = address.strip()
        project_description = project_description.strip()

        location = _extract_location(address) if address else ""
        industry = self._resolve_industry(source_page_id)
        lead_id = uuid.uuid4().hex[:12]

        score = _SimpleScore(50.0)

        first_name = name.split(" ", 1)[0] if name else ""
        last_name = name.split(" ", 1)[1] if " " in name else ""
        lead_data = {
            "id": lead_id,
            "title": name,
            "url": "",
            "snippet": _truncate(project_description, 300),
            "industry": industry,
            "location": location,
            "source": "landing_page",
            "score": 50.0,
            "_score_obj": score,
            "found_at": datetime.now().isoformat(),
            "email": email,
            "phone": phone,
            "notes": project_description,
            "first_name": first_name,
            "last_name": last_name,
            "address": address,
            "project_description": project_description,
            "utm_source": data.get("utm_source", ""),
            "utm_medium": data.get("utm_medium", ""),
            "utm_campaign": data.get("utm_campaign", ""),
            "status": "new",
            "_capture_source": source_page_id,
        }

        lead_obj = _CaptureLead(lead_data)
        self._engine._leads[lead_id] = lead_obj
        self._persist_capture(lead_obj)

        lead_dict = lead_obj.as_dict()

        try:
            steps = self._engine._router._steps
            has_enabled = any(s.enabled for s in steps.values()) if steps else False
            if has_enabled:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                        task = asyncio.create_task(self._engine._router.route_leads([lead_dict]))
                        task.add_done_callback(
                            lambda t: logger.error("Routing task failed: %s", t.exception())
                            if t.exception() else None
                        )
                except RuntimeError:
                    pass
        except Exception as e:
            logger.error("Lead routing error: %s", e, exc_info=True)

        return {
            "ok": True,
            "lead_id": lead_id,
            "score": lead_dict["score"],
        }

    def _resolve_industry(self, source_page_id: str) -> str:
        if not source_page_id:
            return "home improvement"
        try:
            pages = getattr(self, "_landing_pages", {})
            if pages and source_page_id in pages:
                return "home improvement"
        except Exception:
            pass
        return "home improvement"

    def _persist_capture(self, lead_obj: _CaptureLead) -> None:
        """Persist captured lead to the canonical database."""
        try:
            with Database.get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO leads (
                        id, title, url, snippet, industry, location, source, score, found_at,
                        email, phone, notes, score_breakdown, status,
                        first_name, last_name, address, project_description,
                        utm_source, utm_medium, utm_campaign
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lead_obj.id,
                    lead_obj.title,
                    lead_obj.url,
                    lead_obj.snippet,
                    lead_obj.industry,
                    lead_obj.location,
                    lead_obj.source,
                    lead_obj.score.total,
                    lead_obj.found_at,
                    lead_obj.email,
                    lead_obj.phone,
                    lead_obj.notes,
                    json.dumps(lead_obj.score.as_dict()),
                    lead_obj.status,
                    lead_obj.first_name,
                    lead_obj.last_name,
                    lead_obj.address,
                    lead_obj.project_description,
                    lead_obj.utm_source,
                    lead_obj.utm_medium,
                    lead_obj.utm_campaign,
                ))
                conn.commit()
        except Exception as e:
            logger.error("Failed to persist captured lead: %s", e)

    def get_submissions(self, limit: int = 50) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for lead in self._engine._leads.values():
            if hasattr(lead, "source") and lead.source == "landing_page":
                results.append(lead.as_dict() if hasattr(lead, "as_dict") else lead)
        return results[:limit]

    def get_submission_stats(self) -> Dict[str, Any]:
        submissions = self.get_submissions(limit=100000)
        total = len(submissions)
        if total == 0:
            return {"total": 0, "avg_score": 0, "max_score": 0, "min_score": 0}
        scores = [s.get("score", 50) for s in submissions]
        return {
            "total": total,
            "avg_score": round(sum(scores) / len(scores), 1),
            "max_score": round(max(scores), 1),
            "min_score": round(min(scores), 1),
        }
