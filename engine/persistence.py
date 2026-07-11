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
                            id, title, url, snippet, industry, location, source, score, found_at, email, phone, notes, score_breakdown
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(d.get("score_breakdown") or d.get("score_breakdown", {}))
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
