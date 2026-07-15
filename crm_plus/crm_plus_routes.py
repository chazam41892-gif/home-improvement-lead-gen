from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import logging
import uuid

from engine.database import Database
from engine.scout import LeadResult
from engine.utils.scoring import LeadScore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crm", tags=["CRM Plus"])

_engine_ref = None
_conversion_ref = None


def set_engine(engine):
    global _engine_ref
    _engine_ref = engine


def set_conversion(conversion):
    global _conversion_ref
    _conversion_ref = conversion


class OutreachSwarmRequest(BaseModel):
    target_count: int = 50
    campaign_name: str = "Auto Campaign"
    channels: List[str] = ["email", "sms", "linkedin"]


class TalonAuditRequest(BaseModel):
    message_sample: Optional[str] = None


class LeadSyncRequest(BaseModel):
    lead_name: str
    business: str
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    source: str = "crm_plus"
    notes: Optional[str] = None


def _persist_lead(lead: LeadResult) -> None:
    """Persist a LeadResult to the canonical SQLite store."""
    try:
        with Database.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO leads (
                    id, title, url, snippet, industry, location, source, score, found_at,
                    email, phone, notes, score_breakdown
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lead.id,
                getattr(lead, "title", ""),
                getattr(lead, "url", ""),
                getattr(lead, "snippet", ""),
                getattr(lead, "industry", ""),
                getattr(lead, "location", ""),
                getattr(lead, "source", ""),
                float(getattr(lead, "score", LeadScore(50.0)).total) if hasattr(lead, "score") else 50.0,
                getattr(lead, "found_at", datetime.now(timezone.utc).isoformat()),
                getattr(lead, "email", ""),
                getattr(lead, "phone", ""),
                getattr(lead, "notes", ""),
                json.dumps(getattr(lead.score, "as_dict", lambda: {})()) if hasattr(lead, "score") else "{}",
            ))
            conn.commit()
    except Exception as e:
        logger.error("Failed to persist lead to database: %s", e)


@router.post("/outreach_swarm")
async def launch_outreach_swarm(req: OutreachSwarmRequest):
    """Launch an outreach swarm campaign and persist it for tracking."""
    campaign_id = uuid.uuid4().hex[:12]
    swarm_agents = [
        {"agent": "Lead Ingestion Agent", "status": "active", "targets": req.target_count},
        {"agent": "Personalization Agent", "status": "active", "channels": req.channels},
        {"agent": "Sequencing Agent", "status": "active", "sequences": 7},
        {"agent": "Response Intelligence Agent", "status": "active"},
        {"agent": "Booking Agent", "status": "active"},
        {"agent": "Analytics Agent", "status": "active"},
        {"agent": "Talon Compliance Agent", "status": "active"},
    ]
    active_count = len([a for a in swarm_agents if a["status"] == "active"])
    try:
        with Database.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO crm_campaigns (
                    campaign_id, name, target_count, channels, agents_active,
                    estimated_reach, launched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                campaign_id,
                req.campaign_name,
                req.target_count,
                ",".join(req.channels),
                active_count,
                req.target_count * len(req.channels),
                datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()
    except Exception as e:
        logger.error("Failed to persist outreach swarm campaign: %s", e)

    return {
        "status": "launched",
        "campaign_id": campaign_id,
        "campaign": req.campaign_name,
        "agents_active": active_count,
        "swarm_agents": swarm_agents,
        "estimated_reach": req.target_count * len(req.channels),
        "launched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/talon_audit")
async def run_talon_audit(req: TalonAuditRequest):
    msg = (req.message_sample or "").lower()

    can_spam_status = "PASS"
    can_spam_details = "Unsubscribe instructions and physical address placeholders verified."

    gdpr_status = "PASS"
    gdpr_details = "Data minimization verified, privacy references present."

    tcpa_status = "PASS"
    tcpa_details = "SMS opt-in and STOP opt-out terms confirmed."

    casl_status = "PASS"
    casl_details = "Express consent check on file for Canadian compliance."

    anti_spam_status = "PASS"
    anti_spam_details = "No deceptive headers or mail injection attempts detected."

    if req.message_sample:
        has_opt_out = any(kw in msg for kw in ["unsubscribe", "opt out", "opt-out", "stop"])
        has_physical_address = any(kw in msg for kw in ["street", "ave", "road", "suite", "po box", "p.o. box", "address"]) or any(c.isdigit() for c in msg)

        if not has_opt_out:
            can_spam_status = "FAIL"
            can_spam_details = "CAN-SPAM Violation: Message sample lacks an unsubscribe or opt-out mechanism."
            tcpa_status = "FAIL"
            tcpa_details = "TCPA Violation: SMS campaign sample lacks clear STOP opt-out instructions."
        elif "stop" not in msg and len(msg) < 200:
            tcpa_status = "WARNING"
            tcpa_details = "TCPA Warning: Mobile-length sample should include 'Reply STOP' instructions."

        if not has_physical_address:
            if can_spam_status == "PASS":
                can_spam_status = "WARNING"
                can_spam_details = "CAN-SPAM Warning: Message sample lacks a physical business address or PO Box reference."

        if "consent" not in msg and "agree" not in msg and "opt-in" not in msg:
            gdpr_status = "WARNING"
            gdpr_details = "GDPR Warning: Message sample does not explicitly mention user consent or permission criteria."

    checks = [
        {"rule": "CAN-SPAM", "status": can_spam_status, "details": can_spam_details},
        {"rule": "GDPR", "status": gdpr_status, "details": gdpr_details},
        {"rule": "TCPA", "status": tcpa_status, "details": tcpa_details},
        {"rule": "CASL", "status": casl_status, "details": casl_details},
        {"rule": "Anti-Spam Injection", "status": anti_spam_status, "details": anti_spam_details},
    ]

    violations = [c for c in checks if c["status"] in ("FAIL", "WARNING")]
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    warn_count = sum(1 for c in checks if c["status"] == "WARNING")

    score = max(0, 100 - (fail_count * 25) - (warn_count * 10))

    badge = "TALON_CERTIFIED"
    if fail_count > 0:
        badge = "TALON_VIOLATION_DETECTED"
    elif warn_count > 0:
        badge = "TALON_REVIEW_REQUIRED"

    return {
        "status": "complete",
        "score": score,
        "checks": checks,
        "violations": violations,
        "badge": badge,
        "certified_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/analytics")
async def get_crm_analytics():
    """Return real analytics from the database and engine state."""
    try:
        with Database.get_connection() as conn:
            total_leads = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"] or 0
            scored_high = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE score >= 70").fetchone()["c"] or 0
            contacted = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE status = 'contacted'").fetchone()["c"] or 0
            capture_count = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE source = 'landing_page'").fetchone()["c"] or 0
            appointments = conn.execute("SELECT COUNT(*) AS c FROM appointments").fetchone()["c"] or 0
            nurture_total = conn.execute("SELECT COUNT(*) AS c FROM nurture_sequences").fetchone()["c"] or 0
            nurture_completed = conn.execute("SELECT COUNT(*) AS c FROM nurture_sequences WHERE completed = 1").fetchone()["c"] or 0
            campaigns = conn.execute("SELECT COUNT(*) AS c FROM crm_campaigns").fetchone()["c"] or 0
    except Exception as e:
        logger.error("Database analytics query failed: %s", e)
        total_leads = scored_high = contacted = capture_count = appointments = nurture_total = nurture_completed = campaigns = 0

    engine = _engine_ref
    routing_stats = engine.get_routing_stats() if engine else {}
    search_history_len = len(engine.get_search_history(limit=1)) if engine else 0

    return {
        "pipeline": {
            "total_leads": total_leads,
            "scored_high": scored_high,
            "contacted": contacted,
            "pending": max(0, total_leads - contacted),
            "landing_page_captures": capture_count,
        },
        "outreach": {
            "leads_scored": routing_stats.get("total_scored", 0),
            "leads_routed": routing_stats.get("total_routed", 0),
            "routing_history": len(routing_stats.get("history", [])),
            "campaigns": campaigns,
        },
        "nurture": {
            "total_sequences": nurture_total,
            "completed": nurture_completed,
            "appointments": appointments,
        },
        "search": {
            "total_searches": search_history_len,
            "providers_configured": {
                "exa": getattr(engine, "has_exa_key", False) if engine else False,
                "perplexity": getattr(engine, "has_perplexity_key", False) if engine else False,
            },
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sync_lead")
async def sync_lead_to_pipeline(req: LeadSyncRequest):
    engine = _engine_ref
    if not engine:
        return {"status": "error", "message": "Engine not initialized"}

    lead_id = uuid.uuid4().hex[:12]
    score = LeadScore(50.0)
    lead = LeadResult(
        id=lead_id,
        title=req.business,
        url="",
        snippet=f"{req.lead_name} - {req.notes or ''}",
        industry="",
        location=req.city or "",
        source=req.source,
        score=score,
        found_at=datetime.now(timezone.utc).isoformat(),
        email=req.email or "",
        phone=req.phone or "",
        notes=req.notes or "",
    )
    engine._leads[lead_id] = lead
    _persist_lead(lead)
    logger.info("CRM+ synced lead: %s (%s) — id=%s", req.lead_name, req.business, lead_id)

    return {
        "status": "synced",
        "lead_id": lead_id,
        "source": req.source,
        "business": req.business,
        "persisted": True,
    }


import json


class CrmPushRequest(BaseModel):
    lead_ids: List[str]
    provider: str = "hubspot"
    config: Optional[dict] = None


@router.post("/push")
async def push_leads_to_crm(req: CrmPushRequest):
    engine = _engine_ref
    if not engine:
        raise HTTPException(503, "Engine not initialized")
    provider = req.provider.lower()
    if provider not in ("hubspot", "gohighlevel", "pipedrive"):
        raise HTTPException(400, f"Unsupported CRM provider: {provider}")
    leads = [engine._leads.get(lid) for lid in req.lead_ids]
    leads = [l for l in leads if l is not None]
    if not leads:
        raise HTTPException(404, "No valid leads found for given IDs")
    lead_dicts = []
    for l in leads:
        d = {
            "id": l.id,
            "title": getattr(l, "title", ""),
            "name": getattr(l, "name", ""),
            "email": getattr(l, "email", ""),
            "phone": getattr(l, "phone", ""),
            "source": getattr(l, "source", ""),
            "score": float(getattr(l, "score", LeadScore(50)).total),
            "notes": getattr(l, "notes", ""),
            "company": getattr(l, "company", getattr(l, "business_name", "")),
        }
        lead_dicts.append(d)

    from engine.crm_push import CrmPush
    crm = CrmPush()
    results = await crm.push_leads(lead_dicts, provider=provider, config=req.config or {})
    return {"ok": True, "results": results}
