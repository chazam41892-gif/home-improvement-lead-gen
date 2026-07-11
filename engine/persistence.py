from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def save_leads(leads: dict) -> int:
    from engine.database import Database
    if not leads:
        return 0
    count = 0
    try:
        with Database.get_connection() as conn:
            for lid, lead in leads.items():
                try:
                    d = lead.as_dict() if hasattr(lead, "as_dict") else lead
                    score_val = d.get("score", 0.0)
                    if isinstance(score_val, dict):
                        score_val = score_val.get("total", 0.0)
                    conn.execute("""
                        INSERT OR REPLACE INTO leads (
                            id, title, url, snippet, industry, location, source, score, found_at, email, phone, notes, score_breakdown,
                            status, first_name, last_name, address, project_description,
                            utm_source, utm_medium, utm_campaign,
                            sms_consent, email_consent, call_consent, consent_source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        lid,
                        d.get("title", ""),
                        d.get("url", ""),
                        d.get("snippet", ""),
                        d.get("industry", ""),
                        d.get("location", ""),
                        d.get("source", ""),
                        score_val,
                        d.get("found_at", ""),
                        d.get("email", ""),
                        d.get("phone", ""),
                        d.get("notes", ""),
                        json.dumps(d.get("score_breakdown") or d.get("score_breakdown", {})),
                        d.get("status", "new"),
                        d.get("first_name", ""),
                        d.get("last_name", ""),
                        d.get("address", ""),
                        d.get("project_description", ""),
                        d.get("utm_source", ""),
                        d.get("utm_medium", ""),
                        d.get("utm_campaign", ""),
                        1 if d.get("sms_consent") else 0,
                        1 if d.get("email_consent") else 0,
                        1 if d.get("call_consent") else 0,
                        d.get("consent_source", ""),
                    ))
                    count += 1
                except Exception as e:
                    logger.warning("Failed to serialize lead %s: %s", lid, e)
            conn.commit()
    except Exception as e:
        logger.error("Failed to save leads to SQLite: %s", e)
    logger.info("Persisted %d leads to SQLite", count)
    return count


def load_leads(engine=None) -> dict:
    from engine.database import Database
    leads = {}
    try:
        with Database.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM leads")
            rows = cursor.fetchall()
            for r in rows:
                lid = r["id"]
                if engine:
                    from engine.scout import LeadResult
                    from engine.utils.scoring import LeadScore

                    score = LeadScore(total=r["score"])
                    lead = LeadResult(
                        id=lid,
                        title=r["title"],
                        url=r["url"],
                        snippet=r["snippet"],
                        industry=r["industry"],
                        location=r["location"],
                        source=r["source"],
                        score=score,
                        found_at=r["found_at"] or datetime.now().isoformat(),
                        email=r["email"],
                        phone=r["phone"],
                        notes=r["notes"],
                    )
                    # Restore newer columns as attributes
                    lead.status = r["status"]
                    lead.first_name = r["first_name"]
                    lead.last_name = r["last_name"]
                    lead.address = r["address"]
                    lead.project_description = r["project_description"]
                    lead.utm_source = r["utm_source"]
                    lead.utm_medium = r["utm_medium"]
                    lead.utm_campaign = r["utm_campaign"]
                    lead.sms_consent = bool(r["sms_consent"])
                    lead.email_consent = bool(r["email_consent"])
                    lead.call_consent = bool(r["call_consent"])
                    lead.consent_source = r["consent_source"]
                    leads[lid] = lead
                else:
                    d = {
                        "id": lid,
                        "title": r["title"],
                        "url": r["url"],
                        "snippet": r["snippet"],
                        "industry": r["industry"],
                        "location": r["location"],
                        "source": r["source"],
                        "score": r["score"],
                        "found_at": r["found_at"],
                        "email": r["email"],
                        "phone": r["phone"],
                        "notes": r["notes"],
                        "status": r["status"],
                        "first_name": r["first_name"],
                        "last_name": r["last_name"],
                        "address": r["address"],
                        "project_description": r["project_description"],
                        "utm_source": r["utm_source"],
                        "utm_medium": r["utm_medium"],
                        "utm_campaign": r["utm_campaign"],
                        "sms_consent": bool(r["sms_consent"]),
                        "email_consent": bool(r["email_consent"]),
                        "call_consent": bool(r["call_consent"]),
                        "consent_source": r["consent_source"],
                    }
                    try:
                        d["score_breakdown"] = json.loads(r["score_breakdown"]) if r["score_breakdown"] else {}
                    except Exception:
                        d["score_breakdown"] = {}
                    leads[lid] = d
    except Exception as e:
        logger.warning("Failed to load leads from SQLite: %s", e)
    logger.info("Loaded %d leads from SQLite", len(leads))
    return leads
