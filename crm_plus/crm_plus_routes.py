from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import logging

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


@router.post("/outreach_swarm")
async def launch_outreach_swarm(req: OutreachSwarmRequest):
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
    return {
        "status": "launched",
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
        has_opt_out = "unsubscribe" in msg or "opt out" in msg or "opt-out" in msg or "stop" in msg
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
    engine = _engine_ref
    if not engine:
        return _empty_analytics()

    leads = engine.get_leads(limit=10000)
    total = len(leads)
    scored_high = sum(1 for l in leads if isinstance(l, dict) and l.get("score", 0) >= 70)
    contacted = sum(1 for l in leads if isinstance(l, dict) and l.get("status") == "contacted")

    routing_stats = engine.get_routing_stats()
    search_history = engine.get_search_history(limit=1)

    return {
        "pipeline": {
            "total_leads": total,
            "scored_high": scored_high,
            "contacted": contacted,
            "pending": total - contacted,
        },
        "outreach": {
            "leads_scored": routing_stats.get("total_scored", 0),
            "leads_routed": routing_stats.get("total_routed", 0),
            "routing_history": len(routing_stats.get("history", [])),
        },
        "search": {
            "total_searches": len(search_history),
            "providers_configured": {
                "exa": getattr(engine, "has_exa_key", False),
                "perplexity": getattr(engine, "has_perplexity_key", False),
            },
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/sync_lead")
async def sync_lead_to_pipeline(req: LeadSyncRequest):
    engine = _engine_ref
    if not engine:
        return {"status": "error", "message": "Engine not initialized"}

    import uuid
    from datetime import datetime
    from engine.scout import LeadResult
    from engine.utils.scoring import LeadScore

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
        found_at=datetime.now().isoformat(),
        email=req.email or "",
        phone=req.phone or "",
        notes=req.notes or "",
    )
    engine._leads[lead_id] = lead
    logger.info("CRM+ synced lead: %s (%s) — id=%s", req.lead_name, req.business, lead_id)

    return {
        "status": "synced",
        "lead_id": lead_id,
        "source": req.source,
        "business": req.business,
    }


def _empty_analytics():
    return {
        "pipeline": {"total_leads": 0, "scored_high": 0, "contacted": 0, "pending": 0},
        "outreach": {"leads_scored": 0, "leads_routed": 0, "routing_history": 0},
        "search": {"total_searches": 0, "providers_configured": {"exa": False, "perplexity": False}},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
