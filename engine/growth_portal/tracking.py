"""Conversion tracking — UTM capture, pixel endpoints, attribution storage."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/track", tags=["tracking"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_table():
    with Database.get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS utm_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                lead_id TEXT,
                utm_source TEXT,
                utm_medium TEXT,
                utm_campaign TEXT,
                utm_term TEXT,
                utm_content TEXT,
                page_path TEXT,
                referrer TEXT,
                user_agent TEXT,
                ip TEXT,
                timestamp TEXT NOT NULL,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_utm_lead ON utm_events(lead_id);
            CREATE INDEX IF NOT EXISTS idx_utm_campaign ON utm_events(utm_campaign);
        """)
        conn.commit()


_ensure_table()


@router.get("/pixel.gif")
async def tracking_pixel(
    request: Request,
    lead_id: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    utm_term: Optional[str] = None,
    utm_content: Optional[str] = None,
    event_type: str = "page_view",
):
    """1x1 transparent pixel for conversion tracking in emails/lander."""
    _record_event(request, {
        "event_type": event_type,
        "lead_id": lead_id,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "utm_term": utm_term,
        "utm_content": utm_content,
    })
    # Return 1x1 transparent GIF
    return Response(
        content=b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
        media_type="image/gif",
    )


@router.post("/event")
async def track_event(request: Request):
    """POST a conversion/attribution event."""
    body = await request.json()
    body.setdefault("event_type", "conversion")
    _record_event(request, body)
    return {"ok": True}


@router.get("/attribution/{lead_id}")
async def get_attribution(lead_id: str):
    with Database.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM utm_events WHERE lead_id = ? ORDER BY timestamp",
            (lead_id,),
        ).fetchall()
        return {
            "lead_id": lead_id,
            "events": [dict(r) for r in rows],
            "first_touch": dict(rows[0]) if rows else None,
            "last_touch": dict(rows[-1]) if rows else None,
        }


def _record_event(request: Request, data: Dict[str, Any]):
    event_id = uuid.uuid4().hex[:12]
    headers = request.headers
    with Database.get_connection() as conn:
        conn.execute("""
            INSERT INTO utm_events (
                id, event_type, lead_id, utm_source, utm_medium, utm_campaign,
                utm_term, utm_content, page_path, referrer, user_agent, ip, timestamp, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            data.get("event_type", "event"),
            data.get("lead_id"),
            data.get("utm_source"),
            data.get("utm_medium"),
            data.get("utm_campaign"),
            data.get("utm_term"),
            data.get("utm_content"),
            str(request.url.path),
            headers.get("referer"),
            headers.get("user-agent"),
            request.client.host if request.client else None,
            _now(),
            json.dumps({k: v for k, v in data.items() if k not in {
                "event_type", "lead_id", "utm_source", "utm_medium",
                "utm_campaign", "utm_term", "utm_content",
            }}),
        ))
        conn.commit()
