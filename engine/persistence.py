from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_LEADS_FILE = "data/leads.jsonl"


def save_leads(leads: dict) -> int:
    if not leads:
        return 0
    os.makedirs("data", exist_ok=True)
    count = 0
    with open(_LEADS_FILE, "w", encoding="utf-8") as f:
        for lid, lead in leads.items():
            try:
                d = lead.as_dict() if hasattr(lead, "as_dict") else lead
                f.write(json.dumps(d, default=str) + "\n")
                count += 1
            except Exception as e:
                logger.warning("Failed to serialize lead %s: %s", lid, e)
    logger.info("Persisted %d leads to %s", count, _LEADS_FILE)
    return count


def load_leads(engine=None) -> dict:
    if not os.path.exists(_LEADS_FILE):
        logger.info("No leads file found at %s", _LEADS_FILE)
        return {}
    leads = {}
    with open(_LEADS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                lid = d.get("id", "")
                if lid:
                    if engine:
                        from engine.scout import LeadResult
                        from engine.utils.scoring import LeadScore

                        score = LeadScore(total=d.get("score", 0))
                        lead = LeadResult(
                            id=lid,
                            title=d.get("title", ""),
                            url=d.get("url", ""),
                            snippet=d.get("snippet", ""),
                            industry=d.get("industry", ""),
                            location=d.get("location", ""),
                            source=d.get("source", ""),
                            score=score,
                            found_at=d.get("found_at", "") or datetime.now().isoformat(),
                            email=d.get("email", ""),
                            phone=d.get("phone", ""),
                            notes=d.get("notes", ""),
                        )
                        leads[lid] = lead
                    else:
                        leads[lid] = d
            except json.JSONDecodeError as e:
                logger.warning("Skipping malformed lead record: %s", e)
    logger.info("Loaded %d leads from %s", len(leads), _LEADS_FILE)
    return leads
