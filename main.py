from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from engine.scout import LeadScoutEngine, SearchConfig, LeadResult
from engine.utils.scoring import score_lead, LeadScore
from engine.merger import merge_leads
from engine.scheduler import ScanScheduler
from engine.landing import LandingPageGenerator
from engine.capture import LeadCaptureProcessor
from engine.ads import AdCopyGenerator
from engine.nurture import NurtureEngine
from engine.business_config import BusinessConfig
from engine.crm_push import CrmPush
from engine.trades import TradeLeadDiscovery, ConversionPipeline
from engine.trades.trades import list_trades, get_trade_config
from engine.trades.base import TradeLead
from engine.stripe_integration import StripeIntegration
from engine import persistence
from engine.key_vault import KeyVault, SERVICE_KEYS
from engine.enrichment import enrich_lead, EnrichOrchestrator
from engine.enrichment.base import EnrichmentResult
from crm_plus.crm_plus_routes import router as crm_plus_router, set_engine as set_crm_engine, set_conversion as set_crm_conversion

load_dotenv()

# ─── Structured JSON Logging ────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)

_handler = logging.StreamHandler()
_handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler])
logger = logging.getLogger("leadgen")

# ─── Startup Configuration Validation ───────────────────────────────

_CONFIG_CHECKS = {
    "STRIPE_SECRET_KEY": {"required_for": ["billing"], "doc": "Stripe payment processing"},
    "STRIPE_WEBHOOK_SECRET": {"required_for": ["billing"], "doc": "Stripe webhook verification"},
    "EXA_API_KEY": {"required_for": ["search"], "doc": "Exa AI search provider"},
    "PERPLEXITY_API_KEY": {"required_for": ["perplexity"], "doc": "Perplexity AI search provider"},
}

_MISSING_CONFIG: list[str] = []
for var, info in _CONFIG_CHECKS.items():
    if not os.getenv(var):
        _MISSING_CONFIG.append(f"  {var}: {info['doc']} (required for {', '.join(info['required_for'])})")

if _MISSING_CONFIG:
    logger.warning("Startup with missing optional config:\n%s", "\n".join(_MISSING_CONFIG))

# ─── API Authentication ─────────────────────────────────────────────

_API_KEY = os.getenv("API_KEY", "")
_AUTH_ENABLED = bool(_API_KEY)

if _AUTH_ENABLED:
    logger.info("API authentication enabled (bearer token)")
else:
    logger.info("API authentication disabled (set API_KEY env var to enable)")

def verify_api_key(request: Request):
    if not _AUTH_ENABLED:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _API_KEY:
        return True
    raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing API key")

# ─── Rate Limiting (token bucket) ───────────────────────────────────

class TokenBucket:
    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last = time.monotonic()

    def consume(self, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last
        self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate)
        self.last = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

_buckets: dict[str, TokenBucket] = {}

def rate_limit(request: Request, tokens: float = 1.0, key: str = ""):
    if _AUTH_ENABLED:
        client_key = key or request.headers.get("Authorization", request.client.host if request.client else "unknown")
    else:
        client_key = key or (request.client.host if request.client else "unknown")
    bucket = _buckets.get(client_key)
    if not bucket:
        bucket = TokenBucket()
        _buckets[client_key] = bucket
    if not bucket.consume(tokens):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a moment.")

# ─── Engine Initialization ──────────────────────────────────────────

engine = LeadScoutEngine(
    exa_api_key=os.getenv("EXA_API_KEY"),
    perplexity_api_key=os.getenv("PERPLEXITY_API_KEY"),
)

scheduler = ScanScheduler()

async def _scheduler_search(query, num_results, min_score, provider):
    return await engine.search_natural(
        natural_query=query,
        num_results=num_results,
        min_score=min_score,
        provider=provider,
    )

scheduler.register_search_fn(_scheduler_search)

env_keys = ("EXA_", "PERPLEXITY_", "ANTHROPIC_", "COMETAPI_", "CLEARBIT_", "HUNTER_", "STRIPE_")
env_map = {k: v for k, v in os.environ.items() if k.startswith(env_keys)}
engine.set_env(env_map)

# Enrichment and LLM scoring modules (optional)
try:
    from enrichment import enrich_lead as _enrich_fn
    engine.register_enrichment_fn(_enrich_fn)
    logger.info("Enrichment module registered")
except ImportError:
    logger.info("enrichment.py not found — enrichment will be skipped")

try:
    from scoring_llm import score_leads_batch as _llm_batch_fn
    engine.register_llm_score_fn(_llm_batch_fn)
    logger.info("LLM scoring module registered")
except ImportError:
    logger.info("scoring_llm.py not found — LLM scoring will be skipped")

landing_gen = LandingPageGenerator()
capture_processor = LeadCaptureProcessor(engine, landing_pages=landing_gen._pages)
ads_gen = AdCopyGenerator()
nurture = NurtureEngine()
business_config = BusinessConfig()
crm_push = CrmPush()
crm_push.set_env(env_map)

async def _crm_push_fn(leads, config):
    provider = config.get("provider", "hubspot") if config else "hubspot"
    return await crm_push.push_leads(leads, provider=provider, config=config)

engine._router._crm_push_fn = _crm_push_fn
import types
orig_crm_push = engine._router._run_crm_push
async def _patched_crm_push(self, leads, step):
    fn = getattr(self, '_crm_push_fn', None)
    if fn:
        return await fn(leads, step.config)
    return await orig_crm_push(leads, step)
engine._router._run_crm_push = types.MethodType(_patched_crm_push, engine._router)

set_crm_engine(engine)

trade_discovery = TradeLeadDiscovery(exa_provider=engine._exa)
conversion_pipeline = ConversionPipeline()
set_crm_conversion(conversion_pipeline)

stripe_integration = StripeIntegration()

_engine_lock = asyncio.Lock()

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = STATIC_DIR / "templates"
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

_nurture_loop_running = False

async def _nurture_loop():
    global _nurture_loop_running
    _nurture_loop_running = True
    while _nurture_loop_running:
        try:
            due = nurture.get_due_actions()
            for action in due:
                logger.info("Nurture action due", extra={"type": action.get("type"), "sequence_id": action.get("sequence_id")})
                nurture.mark_action_sent(action["sequence_id"], action["action_index"])
        except Exception as e:
            logger.error("Nurture action error", exc_info=True)
        await asyncio.sleep(30)

# ─── Persistence: auto-save on shutdown ────────────────────────────

async def _save_state():
    count = persistence.save_leads(engine._leads)
    logger.info("State saved", extra={"leads_persisted": count})

async def _load_state():
    loaded = persistence.load_leads(engine=engine)
    if loaded:
        engine._leads.update(loaded)
        logger.info("State restored", extra={"leads_loaded": len(loaded)})

# ─── Lifespan ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await _load_state()
    await scheduler.start()
    loop_task = asyncio.create_task(_nurture_loop())
    yield
    await _save_state()
    await scheduler.stop()
    global _nurture_loop_running
    _nurture_loop_running = False
    loop_task.cancel()

app = FastAPI(
    title="Lead Gen Pro",
    version="3.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(crm_plus_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ─── Health ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_sec": round(time.time() - _start_time),
        "auth_enabled": _AUTH_ENABLED,
        "stripe_configured": stripe_integration.is_configured,
        "exa_configured": engine.has_exa_key,
        "perplexity_configured": engine.has_perplexity_key,
        "total_leads": len(engine._leads),
        "missing_config": {var: info["doc"] for var, info in _CONFIG_CHECKS.items() if not os.getenv(var)},
    }

import time as _time_module
_start_time: float = _time_module.time()

# ─── Settings ───────────────────────────────────────────────────────

@app.get("/api/settings", dependencies=[])
async def get_settings():
    return {
        "exa_key_configured": engine.has_exa_key,
        "exa_key_prefix": (engine._exa.api_key[:8] + "...") if engine.has_exa_key and len(engine._exa.api_key) > 8 else None,
        "perplexity_key_configured": engine.has_perplexity_key,
        "perplexity_key_prefix": (engine._perplexity.api_key[:8] + "...") if engine.has_perplexity_key and len(engine._perplexity.api_key) > 8 else None,
    }

@app.post("/api/settings/key")
async def set_api_key(data: Dict[str, str]):
    key = data.get("key", "").strip()
    service = data.get("service", "exa").strip().lower()
    if not key:
        raise HTTPException(400, "API key is required")
    if service == "exa":
        engine.set_exa_key(key)
        return {"ok": True, "message": "Exa API key configured"}
    elif service == "perplexity":
        engine.set_perplexity_key(key)
        return {"ok": True, "message": "Perplexity API key configured"}
    raise HTTPException(400, f"Unknown service: {service}. Use 'exa' or 'perplexity'.")

# ─── Smart Routing ─────────────────────────────────────────────────

@app.get("/api/routing/config")
async def get_routing_config():
    return engine.get_routing_config()

@app.put("/api/routing/config")
async def update_routing_config(data: Dict[str, Any]):
    config = data.get("config")
    if config:
        engine.set_routing_config(config)
        return {"ok": True, "config": engine.get_routing_config()}
    step_name = data.get("step")
    updates = data.get("updates", data)
    if step_name:
        result = engine.update_routing_step(step_name, updates)
        if not result:
            raise HTTPException(404, f"Step '{step_name}' not found")
        return {"ok": True, "step": result}
    raise HTTPException(400, "Provide 'config' or 'step' + 'updates'")

@app.get("/api/routing/steps")
async def list_routing_steps():
    return {"steps": list(engine.get_routing_config().get("steps", []))}

@app.get("/api/routing/history")
async def get_routing_history(limit: int = Query(20, le=100)):
    return {"history": engine.get_routing_history(limit=limit)}

@app.get("/api/routing/stats")
async def get_routing_stats():
    return engine.get_routing_stats()

# ─── Search ─────────────────────────────────────────────────────────

@app.post("/api/search")
async def search_leads(config: SearchConfig, request: Request):
    verify_api_key(request)
    rate_limit(request)
    result = await engine.search(config)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Search failed"))
    return result

@app.post("/api/search/natural")
async def search_natural(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(400, "Search query is required")
    num_results = data.get("num_results", 25)
    min_score = data.get("min_score", 30.0)
    provider = data.get("provider", "exa")
    result = await engine.search_natural(query, num_results=num_results,
                                         min_score=min_score, provider=provider)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Search failed"))
    return result

# ─── Lead Management ───────────────────────────────────────────────

@app.get("/api/leads")
async def list_leads(request: Request, limit: int = Query(100, le=500), min_score: float = Query(0.0), offset: int = Query(0, ge=0)):
    verify_api_key(request)
    rate_limit(request)
    all_leads = engine.get_leads(limit=10000, min_score=min_score)
    paginated = all_leads[offset:offset + limit]
    return {
        "leads": paginated,
        "total": len(engine._leads),
        "returned": len(paginated),
        "offset": offset,
        "limit": limit,
    }

@app.get("/api/leads/{lead_id}")
async def get_lead(lead_id: str, request: Request):
    verify_api_key(request)
    rate_limit(request)
    lead = engine.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead

@app.patch("/api/leads/{lead_id}")
async def update_lead(lead_id: str, data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    lead = engine.update_lead(lead_id, data)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead

@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: str, request: Request):
    verify_api_key(request)
    rate_limit(request)
    ok = engine.delete_lead(lead_id)
    if not ok:
        raise HTTPException(404, "Lead not found")
    return {"ok": True}

@app.delete("/api/leads")
async def clear_leads(request: Request):
    verify_api_key(request)
    rate_limit(request, tokens=5)
    engine.clear_leads()
    return {"ok": True, "message": "All leads cleared"}

# ─── Export ─────────────────────────────────────────────────────────

@app.get("/api/export/csv")
async def export_csv(request: Request, min_score: float = Query(0.0)):
    verify_api_key(request)
    rate_limit(request, tokens=2)
    csv_data = engine.export_csv(min_score=min_score)
    return PlainTextResponse(csv_data, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})

@app.get("/api/export/json")
async def export_json(request: Request, min_score: float = Query(0.0)):
    verify_api_key(request)
    rate_limit(request, tokens=2)
    leads = engine.get_leads(min_score=min_score)
    return PlainTextResponse(json.dumps(leads, indent=2, default=str),
                             media_type="application/json",
                             headers={"Content-Disposition": "attachment; filename=leads.json"})

# ─── Analytics ──────────────────────────────────────────────────────

@app.get("/api/stats")
async def get_stats():
    stats = engine.get_stats()
    stats["scheduler"] = scheduler.get_stats()
    stats["capture"] = capture_processor.get_submission_stats()
    stats["landing_pages"] = len(landing_gen._pages)
    stats["nurture"] = nurture.get_stats()
    stats["crm_push"] = crm_push.get_stats()
    stats["business_config"] = business_config.get_config()
    return stats

@app.get("/api/history")
async def get_history(limit: int = Query(20, le=100)):
    return {"history": engine.get_search_history(limit=limit)}

# ─── Multi-Source Merge Search ─────────────────────────────────────

@app.post("/api/search/multi")
async def search_multi(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request, tokens=2)
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(400, "Search query is required")
    providers = data.get("providers", ["exa", "perplexity"])
    num_results = data.get("num_results", 15)
    min_score = data.get("min_score", 30.0)

    all_leads = []
    sources_used = []
    errors = []

    for provider in providers:
        try:
            result = await engine.search_natural(
                natural_query=query,
                num_results=num_results,
                min_score=0,
                provider=provider,
            )
            if result.get("ok") and result.get("leads"):
                leads = result["leads"]
                for l in leads:
                    l["source"] = l.get("source", provider)
                all_leads.extend(leads)
                sources_used.append(provider)
        except Exception as e:
            errors.append(f"{provider}: {e}")

    merged = merge_leads(all_leads, sources_used)

    scored = []
    for lead in merged["leads"]:
        rule = lead.get("score", 0)
        lead["score"] = rule
        scored.append(lead)

    merged["leads"] = scored
    merged["stats"]["errors"] = errors

    if scored:
        async with _engine_lock:
            for lead in scored:
                lid = lead.get("id", uuid.uuid4().hex[:12])
                ls = score_lead(title=lead.get("title", ""), snippet=lead.get("snippet", ""), url=lead.get("url", ""))
                lead_obj = LeadResult(
                    id=lid,
                    title=lead.get("title", ""),
                    url=lead.get("url", ""),
                    snippet=lead.get("snippet", ""),
                    industry=lead.get("industry", ""),
                    location=lead.get("location", ""),
                    source=lead.get("source", "merged"),
                    score=ls,
                    found_at=datetime.now().isoformat(),
                    email=lead.get("email", ""),
                    phone=lead.get("phone", ""),
                    notes=lead.get("notes", ""),
                )
                engine._leads[lid] = lead_obj

    return merged

# ─── Scan Scheduler ────────────────────────────────────────────────

@app.post("/api/schedules")
async def create_schedule(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    if not data.get("query"):
        raise HTTPException(400, "query is required")
    schedule = scheduler.add_schedule(data)
    return {"ok": True, "schedule": schedule.as_dict()}

@app.get("/api/schedules")
async def list_schedules():
    return {"schedules": scheduler.list_schedules(), "stats": scheduler.get_stats()}

@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    sched = scheduler.get_schedule(schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    return sched.as_dict()

@app.put("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    sched = scheduler.update_schedule(schedule_id, data)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    return {"ok": True, "schedule": sched.as_dict()}

@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request):
    verify_api_key(request)
    rate_limit(request)
    ok = scheduler.delete_schedule(schedule_id)
    if not ok:
        raise HTTPException(404, "Schedule not found")
    return {"ok": True}

@app.get("/api/schedules/{schedule_id}/results")
async def get_schedule_results(schedule_id: str):
    if not scheduler.get_schedule(schedule_id):
        raise HTTPException(404, "Schedule not found")
    return {"schedule_id": schedule_id, "leads": scheduler.get_results(schedule_id)}

# ─── Landing Pages ─────────────────────────────────────────────────

@app.post("/api/landing/generate")
async def create_landing_page(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    if not data.get("business_name"):
        raise HTTPException(400, "business_name is required")
    result = landing_gen.create_page(data)
    return {"ok": True, "page": result}

@app.get("/api/landing/list")
async def list_landing_pages():
    return {"pages": landing_gen.list_pages(), "count": len(landing_gen._pages)}

@app.get("/api/landing/{page_id}", response_class=HTMLResponse)
async def get_landing_page(page_id: str):
    html = landing_gen.get_page(page_id)
    if not html:
        raise HTTPException(404, "Landing page not found")
    return HTMLResponse(html)

@app.delete("/api/landing/{page_id}")
async def delete_landing_page(page_id: str, request: Request):
    verify_api_key(request)
    rate_limit(request)
    ok = landing_gen.delete_page(page_id)
    if not ok:
        raise HTTPException(404, "Landing page not found")
    return {"ok": True}

# ─── Lead Capture ──────────────────────────────────────────────────

@app.post("/api/capture/lead", dependencies=[])
async def capture_lead(data: Dict[str, Any]):
    source = data.pop("_source_page_id", "")
    result = capture_processor.process_submission(data, source_page_id=source)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Validation failed"))
    try:
        lead_id = result.get("lead_id")
        if lead_id:
            lead_obj = engine._leads.get(lead_id)
            if lead_obj:
                lead_dict = lead_obj.as_dict() if hasattr(lead_obj, "as_dict") else lead_obj
                lead_dict["business_name"] = business_config.get_config().get("business_name", "Our Business")
                nurture.create_sequence(lead_dict)
                logger.info("Nurture sequence created", extra={"lead_id": lead_id})
    except Exception as e:
        logger.warning("Failed to create nurture sequence", exc_info=True)
    return result

@app.get("/api/capture/thank-you", response_class=HTMLResponse)
async def capture_thank_you(name: str = ""):
    path = TEMPLATES_DIR / "thank-you.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse(f"<h1>Thank you, {name}!</h1><p>We'll be in touch soon.</p>")

@app.get("/api/capture/stats")
async def capture_stats():
    return capture_processor.get_submission_stats()

# ─── Ad Copy Generation ────────────────────────────────────────────

@app.post("/api/ads/generate-copy")
async def generate_ad_copy(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    industry = data.get("industry", "").strip()
    if not industry:
        raise HTTPException(400, "industry is required")
    result = ads_gen.generate_ad_copy(
        industry=industry,
        location=data.get("location", ""),
        usp=data.get("usp", ""),
        platform=data.get("platform", "google"),
        count=data.get("count", 3),
    )
    return {"ok": True, "ads": result}

@app.post("/api/ads/generate-keywords")
async def generate_keywords(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    industry = data.get("industry", "").strip()
    if not industry:
        raise HTTPException(400, "industry is required")
    result = ads_gen.generate_keywords(industry=industry, location=data.get("location", ""))
    return {"ok": True, "keywords": result}

@app.post("/api/ads/generate-pixel")
async def generate_pixel(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    ptype = data.get("type", "").strip()
    tracking_id = data.get("tracking_id", "").strip()
    if not ptype or not tracking_id:
        raise HTTPException(400, "type and tracking_id are required")
    try:
        html = ads_gen.generate_pixel_html(ptype, tracking_id)
        return {"ok": True, "html": html, "type": ptype}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/ads/inject-pixels")
async def inject_pixels(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    page_id = data.get("page_id", "")
    pixels = data.get("pixels", [])
    if not page_id or not pixels:
        raise HTTPException(400, "page_id and pixels are required")
    html = landing_gen.get_page(page_id)
    if not html:
        raise HTTPException(404, "Landing page not found")
    modified = ads_gen.inject_pixels(html, pixels)
    landing_gen._pages[page_id] = modified
    return {"ok": True, "page_id": page_id, "injected": len(pixels)}

@app.post("/api/ads/utm")
async def generate_utm(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    url = data.get("url", "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    result = ads_gen.generate_utm_url(
        base_url=url,
        source=data.get("source", ""),
        medium=data.get("medium", "cpc"),
        campaign=data.get("campaign", ""),
        content=data.get("content", ""),
    )
    return {"ok": True, "utm_url": result}

# ─── Nurture Engine ────────────────────────────────────────────────

@app.post("/api/nurture/sequence")
async def create_nurture_sequence(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    lead_data = data.get("lead", data)
    result = nurture.create_sequence(lead_data)
    return {"ok": True, "sequence": result}

@app.get("/api/nurture/sequences")
async def list_nurture_sequences(limit: int = Query(50, le=200)):
    return {"sequences": nurture.get_sequences(limit=limit), "stats": nurture.get_stats()}

@app.get("/api/nurture/sequences/{sequence_id}")
async def get_nurture_sequence(sequence_id: str):
    seq = nurture.get_sequence(sequence_id)
    if not seq:
        raise HTTPException(404, "Sequence not found")
    return seq

@app.delete("/api/nurture/sequences/{sequence_id}")
async def delete_nurture_sequence(sequence_id: str, request: Request):
    verify_api_key(request)
    rate_limit(request)
    ok = nurture.delete_sequence(sequence_id)
    if not ok:
        raise HTTPException(404, "Sequence not found")
    return {"ok": True}

@app.get("/api/nurture/due")
async def get_due_actions():
    return {"actions": nurture.get_due_actions()}

@app.post("/api/nurture/mark-sent")
async def mark_action_sent(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    seq_id = data.get("sequence_id", "")
    action_idx = data.get("action_index", 0)
    ok = nurture.mark_action_sent(seq_id, action_idx)
    if not ok:
        raise HTTPException(404, "Sequence or action not found")
    return {"ok": True}

@app.post("/api/nurture/schedule")
async def schedule_appointment(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    result = nurture.handle_scheduling(data)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Validation failed"))
    return result

@app.get("/api/nurture/schedule/widget")
async def scheduling_widget(business_name: str = "Our Business"):
    html = nurture.generate_scheduling_widget(business_name=business_name)
    return HTMLResponse(html)

@app.get("/api/nurture/appointments")
async def list_appointments(limit: int = Query(50, le=200)):
    return {"appointments": nurture.get_appointments(limit=limit)}

@app.get("/api/nurture/stats")
async def nurture_stats():
    return nurture.get_stats()

# ─── Business Config ────────────────────────────────────────────────

@app.get("/api/business/config")
async def get_business_config():
    return business_config.get_config()

@app.put("/api/business/config")
async def update_business_config(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    return business_config.update_config(data)

@app.get("/api/business/metrics")
async def get_business_metrics():
    return business_config.get_metrics()

# ─── CRM Push History ──────────────────────────────────────────────

@app.get("/api/crm/history")
async def get_crm_history(limit: int = Query(20, le=100)):
    return {"history": crm_push.get_history(limit=limit)}

@app.get("/api/crm/stats")
async def get_crm_stats():
    return crm_push.get_stats()

# ─── Trade-Specific Lead Discovery ─────────────────────────────────

@app.get("/api/trades", dependencies=[])
async def get_trades():
    return {"trades": list_trades()}

@app.get("/api/trades/accounts")
async def get_trade_accounts():
    return {"accounts": conversion_pipeline.get_accounts(), "count": len(conversion_pipeline.get_accounts())}

@app.get("/api/trades/payments")
async def get_trade_payments():
    return {"payments": conversion_pipeline.get_payments()}

@app.get("/api/trades/revenue")
async def get_trade_revenue():
    return {"stats": conversion_pipeline.get_revenue_stats()}

@app.get("/api/trades/{trade_id}")
async def get_trade(trade_id: str):
    config = get_trade_config(trade_id)
    if not config:
        raise HTTPException(404, f"Trade '{trade_id}' not found")
    return {"trade_id": trade_id, "config": config}

@app.post("/api/trades/discover")
async def discover_trade_leads(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request, tokens=3)
    trade = data.get("trade", "").strip()
    location = data.get("location", "").strip()
    if not trade or not location:
        raise HTTPException(400, "trade and location are required")
    config = get_trade_config(trade)
    if not config:
        raise HTTPException(404, f"Unknown trade: {trade}")
    platforms = data.get("platforms")
    max_results = data.get("max_results", 20)
    leads = await trade_discovery.discover(trade, location, platforms=platforms, max_per_platform=max_results)
    scored = [dict(l.to_dict(), score=round(l.score, 1)) for l in leads]
    return {"ok": True, "trade": trade, "location": location, "leads": scored, "count": len(scored)}

@app.post("/api/trades/discover-all")
async def discover_all_trades(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request, tokens=5)
    location = data.get("location", "").strip()
    if not location:
        raise HTTPException(400, "location is required")
    trades = data.get("trades")
    results = await trade_discovery.discover_all(trades=trades, location=location)
    flattened = {}
    for trade, leads in results.items():
        flattened[trade] = [dict(l.to_dict(), score=round(l.score, 1)) for l in leads]
    return {"ok": True, "location": location, "trades": flattened}

# ─── Lead → Account → Payment Pipeline ────────────────────────────

@app.post("/api/trades/convert")
async def convert_lead(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    lead_id = data.get("lead_id", "")
    trade = data.get("trade", "")
    business_name = data.get("business_name", "")
    phone = data.get("phone", "")
    email = data.get("email", "")
    plan = data.get("plan", "starter")
    if not trade or not business_name:
        raise HTTPException(400, "trade and business_name are required")

    lead = TradeLead(
        business_name=business_name,
        phone=phone,
        email=email,
        source=data.get("source", "manual"),
        trade=trade,
        notes=data.get("notes", ""),
    )
    if lead_id:
        lead.id = lead_id

    account = await conversion_pipeline.convert_to_account(lead, plan=plan)
    payment = await conversion_pipeline.record_payment(account["account_id"], account["monthly_fee"])
    subscription = await conversion_pipeline.create_subscription(account["account_id"], plan=plan)

    return {
        "ok": True,
        "lead": lead.to_dict(),
        "account": account,
        "payment": payment,
        "subscription": subscription,
    }

# ─── Billing / Stripe ──────────────────────────────────────────────

@app.post("/api/billing/create-checkout-session")
async def create_checkout_session(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    if not stripe_integration.is_configured:
        raise HTTPException(503, "Stripe not configured")
    plan = data.get("plan", "").strip().lower()
    account_id = data.get("account_id", "").strip()
    success_url = data.get("success_url", "").strip()
    cancel_url = data.get("cancel_url", "").strip()
    if not plan or not account_id or not success_url:
        raise HTTPException(400, "plan, account_id, and success_url are required")
    try:
        result = await stripe_integration.create_checkout_session(plan, account_id, success_url, cancel_url)
        return {"ok": True, "url": result["url"], "session_id": result["session_id"]}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/billing/portal")
async def billing_portal(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    if not stripe_integration.is_configured:
        raise HTTPException(503, "Stripe not configured")
    account_id = data.get("account_id", "").strip()
    return_url = data.get("return_url", "").strip()
    if not account_id or not return_url:
        raise HTTPException(400, "account_id and return_url are required")
    try:
        result = await stripe_integration.create_billing_portal(account_id, return_url)
        return {"ok": True, "url": result["url"]}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/billing/webhook", dependencies=[])
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        return await stripe_integration.handle_webhook(payload, sig_header)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/billing/subscription/{account_id}")
async def get_subscription(account_id: str, request: Request):
    verify_api_key(request)
    rate_limit(request)
    if not stripe_integration.is_configured:
        raise HTTPException(503, "Stripe not configured")
    result = await stripe_integration.get_subscription(account_id)
    if result.get("status") == "not_found":
        raise HTTPException(404, "Subscription not found")
    return result

@app.post("/api/billing/cancel")
async def cancel_subscription(data: Dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    if not stripe_integration.is_configured:
        raise HTTPException(503, "Stripe not configured")
    account_id = data.get("account_id", "").strip()
    if not account_id:
        raise HTTPException(400, "account_id is required")
    try:
        return await stripe_integration.cancel_subscription(account_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

# ─── Key Vault ─────────────────────────────────────────────────────

KeyVault.load()

@app.get("/api/vault/keys")
async def vault_list_keys(request: Request):
    verify_api_key(request)
    return KeyVault.list()


@app.post("/api/vault/keys/{service}")
async def vault_set_key(service: str, request: Request):
    verify_api_key(request)
    body = await request.json()
    key = body.get("key", "")
    label = body.get("label", "user")
    if not key:
        raise HTTPException(400, "key is required")
    if service not in SERVICE_KEYS:
        raise HTTPException(400, f"Unknown service: {service}")
    ok = KeyVault.set_key(service, key, label)
    return {"ok": ok, "service": service, "label": label}


@app.delete("/api/vault/keys/{service}")
async def vault_delete_key(service: str, request: Request):
    verify_api_key(request)
    body = await request.json() if request.headers.get("content-type") else {}
    label = body.get("label", "user")
    ok = KeyVault.delete_key(service, label)
    return {"ok": ok, "service": service, "label": label}


# ─── Enrichment ────────────────────────────────────────────────────

_orchestrator: Optional[EnrichOrchestrator] = None


def _get_enrich_orch() -> EnrichOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EnrichOrchestrator()
    return _orchestrator


@app.get("/api/enrich/providers")
async def enrich_providers(request: Request):
    verify_api_key(request)
    orch = _get_enrich_orch()
    return {
        "providers": orch.list_providers(),
        "available": any(p["available"] for p in orch.list_providers()),
    }


@app.post("/api/enrich/lead")
async def enrich_single_lead(request: Request):
    verify_api_key(request)
    body = await request.json()
    business_name = body.get("business_name", "")
    trade = body.get("trade", "")
    if not business_name or not trade:
        raise HTTPException(400, "business_name and trade are required")
    orch = _get_enrich_orch()
    result = await orch.enrich(
        business_name=business_name,
        trade=trade,
        location=body.get("location"),
        website=body.get("website"),
        phone=body.get("phone"),
    )
    return result.to_dict()


@app.post("/api/enrich/batch")
async def enrich_batch(request: Request):
    verify_api_key(request)
    body = await request.json()
    leads = body.get("leads", [])
    if not leads:
        raise HTTPException(400, "leads array is required")
    orch = _get_enrich_orch()
    results = await orch.enrich_batch(leads)
    return {
        "total": len(results),
        "results": [r.to_dict() if isinstance(r, EnrichmentResult) else {"error": str(r)} for r in results],
    }


@app.get("/api/enrich/from-lead/{lead_id}")
async def enrich_from_lead(lead_id: str, request: Request):
    verify_api_key(request)
    lead = engine.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    orch = _get_enrich_orch()
    result = await orch.enrich(
        business_name=lead.get("business_name", ""),
        trade=lead.get("trade", ""),
        location=lead.get("location"),
        website=lead.get("website"),
        phone=lead.get("phone"),
    )
    enriched = result.to_dict()
    enriched["lead_id"] = lead_id
    return enriched


# ─── Vault UI ──────────────────────────────────────────────────────

@app.get("/vault", response_class=HTMLResponse)
async def vault_page():
    vault_path = STATIC_DIR / "vault.html"
    if vault_path.exists():
        return vault_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Key Vault</h1><p>Vault UI not found.</p>")


# ─── Dashboard UI ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Lead Gen Pro</h1><p>Dashboard not found.</p>")

# ─── Error handlers ────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "code": exc.status_code},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "code": 500},
    )

if __name__ == "__main__":
    import uvicorn
    _start_time = time.time()
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"\n  Lead Gen Pro v3.1.0 — http://localhost:{port}")
    print(f"  API Docs    — http://localhost:{port}/docs")
    print(f"  Dashboard   — http://localhost:{port}/\n")
    uvicorn.run("main:app", host=host, port=port, reload=True)
