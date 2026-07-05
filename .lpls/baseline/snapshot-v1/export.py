from __future__ import annotations

import csv
import json
import io
from datetime import datetime
from typing import Any, Dict, List


def export_to_csv(leads: List[Dict[str, Any]]) -> str:
    if not leads:
        return ""

    output = io.StringIO()
    fieldnames = [
        "id", "title", "url", "snippet", "industry",
        "location", "score", "contact_score", "business_score",
        "industry_score", "location_score", "enrichment_score",
        "source", "found_at", "email", "phone",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for lead in leads:
        row = {
            "id": lead.get("id", ""),
            "title": lead.get("title", ""),
            "url": lead.get("url", ""),
            "snippet": lead.get("snippet", "")[:200],
            "industry": lead.get("industry", ""),
            "location": lead.get("location", ""),
            "score": lead.get("score", 0),
            "contact_score": lead.get("contact_score", 0),
            "business_score": lead.get("business_score", 0),
            "industry_score": lead.get("industry_score", 0),
            "location_score": lead.get("location_score", 0),
            "enrichment_score": lead.get("enrichment_score", 0),
            "source": lead.get("source", ""),
            "found_at": lead.get("found_at", ""),
            "email": lead.get("email", ""),
            "phone": lead.get("phone", ""),
        }
        writer.writerow(row)

    return output.getvalue()


def export_to_json(leads: List[Dict[str, Any]]) -> str:
    clean = []
    for lead in leads:
        clean.append({
            k: v for k, v in lead.items()
            if v is not None and v != ""
        })
    return json.dumps(clean, indent=2, default=str)


def export_timestamped_filename(prefix: str = "leads", ext: str = "csv") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.{ext}"
