from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import time as _time_module
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_start_time: float = _time_module.time()

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

# CRITICAL (audit 2026-09-27, C-6): the .env file MUST be loaded before ANY engine
# import. engine/auth.py reads JWT_SECRET from os.environ at *import* time and raises
# RuntimeError if it is missing, so importing it before load_dotenv() made the whole
# app un-bootable on a clean checkout (`uvicorn main:app` -> RuntimeError, exit 1)
# even though .env contained a valid JWT_SECRET.
#
# override=False under test: an already-set environment variable wins. Without
# this, load_dotenv() would silently clobber the DATABASE_FILE the test suite
# exported before importing main, and tests would write into the production
# data/lead_gen.db. In production nothing pre-sets it, so behavior is unchanged.
if os.environ.get("LEADGEN_TESTING"):
    load_dotenv(override=False)
else:
    load_dotenv()


def _read_version() -> str:
    """Read the version from pyproject.toml so it is stated exactly once.

    The /health endpoint used to hardcode "3.2.0" while pyproject.toml said
    3.1.3, so the version the product reported did not match the version it
    was built from. Falls back to "0.0.0+unknown" only if pyproject is
    unreadable (e.g. installed without the source tree), and never guesses.
    """
    try:
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).parent / "pyproject.toml"
        with pyproject.open("rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        return "0.0.0+unknown"


_VERSION = _read_version()


from crm_plus.crm_plus_routes import router as crm_plus_router
from crm_plus.crm_plus_routes import set_conversion as set_crm_conversion
from crm_plus.crm_plus_routes import set_engine as set_crm_engine
from engine import persistence
from engine.ad_apis import AdCampaignPlan, AdPlatformManager
from engine.ads import AdCopyGenerator
from engine.auth import auth_manager
from engine.business_config import BusinessConfig
from engine.capture import LeadCaptureProcessor
from engine.crm_push import CrmPush
from engine.discovery import FREE_SOURCES, KEYED_SOURCES, DiscoveryEngine, TargetProfile
from engine.enrichment import EnrichOrchestrator
from engine.enrichment.base import EnrichmentResult
from engine.growth_portal import growth_router, tracking_router
from engine.key_vault import SERVICE_KEYS, KeyVault
from engine.landing import LandingPageGenerator
from engine.merger import merge_leads
from engine.nurture import NurtureEngine
from engine.scheduler import ScanScheduler
from engine.scout import LeadResult, LeadScoutEngine, SearchConfig
from engine.simulator import CampaignSimulator
from engine.stripe_integration import StripeIntegration
from engine.trades import ConversionPipeline, TradeLeadDiscovery
from engine.trades.base import TradeLead
from engine.trades.trades import get_trade_config, list_trades
from engine.utils.scoring import score_lead

# NOTE: load_dotenv() is called above the engine imports (see the CRITICAL comment
# there). Do not call it again here.

# ─── Structured JSON Logging ────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(UTC).isoformat(),
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
    "GOOGLE_ADS_DEVELOPER_TOKEN": {"required_for": ["google_ads"], "doc": "Google Ads API developer token"},
    "GOOGLE_ADS_CUSTOMER_ID": {"required_for": ["google_ads"], "doc": "Google Ads customer ID"},
    "GOOGLE_ADS_REFRESH_TOKEN": {"required_for": ["google_ads"], "doc": "Google Ads OAuth refresh token"},
    "META_ACCESS_TOKEN": {"required_for": ["meta_ads"], "doc": "Meta Marketing API access token"},
    "META_AD_ACCOUNT_ID": {"required_for": ["meta_ads"], "doc": "Meta ad account ID"},
    "TWILIO_ACCOUNT_SID": {"required_for": ["sms", "calls"], "doc": "Twilio SMS/call provider"},
    "TWILIO_AUTH_TOKEN": {"required_for": ["sms", "calls"], "doc": "Twilio auth token"},
    "TWILIO_FROM_NUMBER": {"required_for": ["sms", "calls"], "doc": "Twilio sender phone number"},
    "SENDGRID_API_KEY": {"required_for": ["email"], "doc": "SendGrid email provider"},
    "SENDGRID_FROM_EMAIL": {"required_for": ["email"], "doc": "SendGrid from email address"},
}

_MISSING_CONFIG: list[str] = []
for var, info in _CONFIG_CHECKS.items():
    if not os.getenv(var):
        _MISSING_CONFIG.append(f"  {var}: {info['doc']} (required for {', '.join(info['required_for'])})")

if _MISSING_CONFIG:
    logger.warning("Startup with missing optional config:\n%s", "\n".join(_MISSING_CONFIG))

# ─── API Authentication ─────────────────────────────────────────────

_API_KEY = os.getenv("API_KEY", "").strip()
_AUTH_EXPLICITLY_DISABLED = os.getenv("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")
_AUTH_ENABLED = bool(_API_KEY) and not _AUTH_EXPLICITLY_DISABLED

if _API_KEY:
    logger.info("API authentication enabled (bearer token)")
elif _AUTH_EXPLICITLY_DISABLED:
    logger.warning("API authentication explicitly disabled via AUTH_DISABLED. This is unsafe for production.")
else:
    logger.warning("API_KEY not set. API routes will reject requests until a key is configured.")


def verify_api_key(request: Request):
    if _AUTH_EXPLICITLY_DISABLED:
        return True
    if not _API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: API_KEY not configured on server")
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _API_KEY:
        return True
    if auth.startswith("Bearer "):
        token = auth[7:]
        payload = auth_manager.verify_jwt(token)
        if payload:
            request.state.user = payload
            return True
        # An unprovisioned or unreachable auth store (missing api_keys table,
        # locked DB, corrupt row) must not turn an authentication failure into a
        # 500. verify_api_key raises rather than returning falsy on those, so
        # contain it here and fall through to the 401 below.
        try:
            info = auth_manager.verify_api_key(token)
        except Exception:
            logger.exception("auth_manager.verify_api_key failed; treating token as invalid")
            info = None
        if info:
            request.state.user = info
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
        client_key = key or request.headers.get(
            "Authorization", request.client.host if request.client else "unknown"
        )
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

# Live multi-source discovery (Google Maps / Reddit / Craigslist / GitHub / Exa /
# Tavily) — ported from sios.leadgen.engine, audit 2026-09-27 parity gap B.
# The LLM extraction hook is the same one scout uses, so both paths enrich alike.
discovery_engine = DiscoveryEngine(llm_func=None)

env_keys = (
    "EXA_",
    "PERPLEXITY_",
    "ANTHROPIC_",
    "OPENAI_",
    "COMETAPI_",
    "CLEARBIT_",
    "HUNTER_",
    "APOLLO_",
    "PEOPLE_DATA_LABS_",
    "LOOX_",
    "ENRICHMENT_",
    "STRIPE_",
)
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
ad_platforms = AdPlatformManager()
nurture = NurtureEngine()
campaign_simulator = CampaignSimulator()
business_config = BusinessConfig()
crm_push = CrmPush()
crm_push.set_env(env_map)


async def _crm_push_fn(leads, config):
    provider = config.get("provider", "hubspot") if config else "hubspot"
    return await crm_push.push_leads(leads, provider=provider, config=config)


engine._router.register_crm_push_fn(_crm_push_fn)

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
            await nurture.execute_due_actions()
        except Exception:
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
app.include_router(growth_router)
app.include_router(tracking_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ─── Health ─────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {
        "status": "ok",
        # Single-sourced from pyproject.toml. This was hardcoded as "3.2.0"
        # while pyproject said 3.1.3, so the reported version was fiction.
        "version": _VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_sec": round(time.time() - _start_time),
        "auth_enabled": _AUTH_ENABLED,
        "stripe_configured": stripe_integration.is_configured,
        "exa_configured": engine.has_exa_key,
        "perplexity_configured": engine.has_perplexity_key,
        "google_ads_configured": ad_platforms.google.is_configured,
        "meta_ads_configured": ad_platforms.meta.is_configured,
        "total_leads": len(engine._leads),
        "missing_config": {var: info["doc"] for var, info in _CONFIG_CHECKS.items() if not os.getenv(var)},
    }


# ─── Settings ───────────────────────────────────────────────────────


@app.get("/api/settings")
async def get_settings(request: Request):
    verify_api_key(request)
    return {
        "exa_key_configured": engine.has_exa_key,
        "perplexity_key_configured": engine.has_perplexity_key,
    }


@app.post("/api/settings/key")
async def set_api_key(data: dict[str, str], request: Request):
    verify_api_key(request)
    key = data.get("key", "").strip()
    service = data.get("service", "exa").strip().lower()
    if not key:
        raise HTTPException(400, "API key is required")
    if service not in SERVICE_KEYS:
        raise HTTPException(400, f"Unknown service: {service}")
    KeyVault.set_key(service, key)
    if service == "exa":
        engine.set_exa_key(key)
    elif service == "perplexity":
        engine.set_perplexity_key(key)
    return {"ok": True, "message": f"{service} API key configured"}


# ─── Smart Routing ─────────────────────────────────────────────────


@app.get("/api/routing/config")
async def get_routing_config():
    return engine.get_routing_config()


@app.put("/api/routing/config")
async def update_routing_config(data: dict[str, Any], request: Request):
    # This route was the only MUTATING endpoint of 50 that never called
    # verify_api_key. Anyone who could reach the port could rewrite the routing
    # pipeline -- enabling crm_push / llm_score, or moving the scoring floors --
    # which changes what data is pushed to the CRM. It now authenticates like
    # its sibling PUT /api/business/config. (The 4 other unguarded mutating
    # routes are public by design: /api/auth/register, /api/auth/login,
    # /api/billing/webhook, /api/capture/lead.)
    verify_api_key(request)
    rate_limit(request)
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
async def search_natural(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    query = data.get("query", "").strip()
    if not query:
        raise HTTPException(400, "Search query is required")
    num_results = data.get("num_results", 25)
    min_score = data.get("min_score", 30.0)
    provider = data.get("provider", "exa")
    result = await engine.search_natural(
        query, num_results=num_results, min_score=min_score, provider=provider
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Search failed"))
    return result


# ─── Live Multi-Source Discovery (parity gap B, audit 2026-09-27) ─────
# Ported from sios.leadgen.engine so the standalone can harvest Google Maps /
# Reddit / Craigslist / GitHub directly instead of only paying Exa + Perplexity.


@app.get("/api/discovery/sources")
async def discovery_sources(request: Request):
    """List the live sources discovery can use, and which need a credential."""
    verify_api_key(request)
    return {
        "free_sources": list(FREE_SOURCES),
        "keyed_sources": list(KEYED_SOURCES),
        "available": {
            "exa": bool(os.environ.get("EXA_API_KEY")),
            "tavily": bool(os.environ.get("TAVILY_API_KEY")),
            "github": bool(os.environ.get("GITHUB_TOKEN")),
        },
    }


@app.post("/api/discovery/run")
async def discovery_run(data: dict[str, Any], request: Request):
    """Run multi-source discovery for a target profile.

    Returns the job including `raw_results`, `leads`, and `skipped` so a caller can
    tell the difference between "found nothing" and "source unavailable".
    """
    verify_api_key(request)
    rate_limit(request)
    sources = data.get("sources") or list(FREE_SOURCES)
    unknown = [s for s in sources if s not in set(FREE_SOURCES) | set(KEYED_SOURCES) | {"url"}]
    if unknown:
        raise HTTPException(400, f"Unknown source(s): {', '.join(unknown)}")

    profile = TargetProfile(
        customer_description=data.get("customer_description", "") or data.get("query", ""),
        keywords=data.get("keywords") or [],
        locations=data.get("locations") or [],
        industry=data.get("industry", ""),
        target_count=int(data.get("target_count", 25)),
    )
    job = await discovery_engine.run_discovery(profile, sources)
    if job.status == "failed":
        raise HTTPException(502, job.error or "Discovery failed")
    return {
        "job_id": job.id,
        "status": job.status,
        "sources_used": job.sources_used,
        "raw_count": len(job.raw_results),
        "lead_count": len(job.leads),
        "skipped": job.skipped,
        "leads": job.leads,
        "raw_results": [asdict(r) for r in job.raw_results[:50]],
    }


@app.get("/api/discovery/jobs")
async def discovery_jobs(request: Request):
    verify_api_key(request)
    return {"jobs": discovery_engine.get_jobs()}


@app.get("/api/discovery/leads")
async def discovery_leads(request: Request):
    verify_api_key(request)
    return {"leads": discovery_engine.get_leads()}


@app.post("/api/discovery/ingest")
async def discovery_ingest(data: dict[str, Any], request: Request):
    """Ingest raw Apollo/Hunter/LinkedIn CSV/JSON lead exports."""
    verify_api_key(request)
    rate_limit(request)
    rows = data.get("leads") or []
    if not rows:
        raise HTTPException(400, "leads array is required")
    out = await discovery_engine.ingest_webhook_leads(rows, source_name=data.get("source", "webhook_apollo"))
    return {"ingested": len(out), "leads": out}


# ─── Lead Management ───────────────────────────────────────────────


@app.get("/api/leads")
async def list_leads(
    request: Request,
    limit: int = Query(100, le=500),
    min_score: float = Query(0.0),
    offset: int = Query(0, ge=0),
):
    verify_api_key(request)
    rate_limit(request)
    all_leads = engine.get_leads(limit=10000, min_score=min_score)
    paginated = all_leads[offset : offset + limit]
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
async def update_lead(lead_id: str, data: dict[str, Any], request: Request):
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
    return PlainTextResponse(
        csv_data, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"}
    )


@app.get("/api/export/json")
async def export_json(request: Request, min_score: float = Query(0.0)):
    verify_api_key(request)
    rate_limit(request, tokens=2)
    leads = engine.get_leads(min_score=min_score)
    return PlainTextResponse(
        json.dumps(leads, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=leads.json"},
    )


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
    stats["ad_platforms"] = ad_platforms.status()
    return stats


@app.get("/api/history")
async def get_history(limit: int = Query(20, le=100)):
    return {"history": engine.get_search_history(limit=limit)}


# ─── Multi-Source Merge Search ─────────────────────────────────────


@app.post("/api/search/multi")
async def search_multi(data: dict[str, Any], request: Request):
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
            # The caller's min_score was being read and then discarded: a hardcoded
            # 0 was passed instead, so /api/search/natural returned everything
            # regardless of the requested threshold. Honour it now.
            result = await engine.search_natural(
                natural_query=query,
                num_results=num_results,
                min_score=min_score,
                provider=provider,
            )
            if result.get("ok") and result.get("leads"):
                leads = result["leads"]
                for lead in leads:
                    lead["source"] = lead.get("source", provider)
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
            # CRITICAL (audit 2026-09-27): engine.search_natural() above ALREADY
            # wrote each provider's raw hits into engine._leads under their own
            # fresh ids. This block then minted a SECOND id for every merged lead
            # (`lead.get("id", ...)` never fires because the dicts carry the
            # provider id, but the merge can renumber), so the store ended up
            # holding both copies: a multi search returned 3 deduped leads while
            # /api/leads reported 4, with the pre-dedup duplicate still present.
            # Fix: index what is already stored by URL, and evict the
            # provider-level rows for URLs the merge kept, before writing the
            # merged set. Duplicates therefore cannot survive in the store.
            keep_ids = {lead.get("id") for lead in scored if lead.get("id")}
            keep_urls = {(lead.get("url") or "").rstrip("/") for lead in scored}
            for existing_id, existing in list(engine._leads.items()):
                if existing_id in keep_ids:
                    continue
                existing_url = (getattr(existing, "url", "") or "").rstrip("/")
                if existing_url and existing_url in keep_urls:
                    del engine._leads[existing_id]

            for lead in scored:
                # Reuse the id the merge produced; only mint when it is absent.
                lid = lead.get("id") or uuid.uuid4().hex[:12]
                ls = score_lead(
                    title=lead.get("title", ""), snippet=lead.get("snippet", ""), url=lead.get("url", "")
                )
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
                # Keep the response and the store in agreement about the id.
                lead["id"] = lid

    return merged


# ─── Scan Scheduler ────────────────────────────────────────────────


@app.post("/api/schedules")
async def create_schedule(data: dict[str, Any], request: Request):
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
async def update_schedule(schedule_id: str, data: dict[str, Any], request: Request):
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
async def create_landing_page(data: dict[str, Any], request: Request):
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
async def capture_lead(data: dict[str, Any]):
    source = data.pop("_source_page_id", "")
    result = capture_processor.process_submission(data, source_page_id=source)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Validation failed"))
    try:
        lead_id = result.get("lead_id")
        if lead_id:
            lead_obj = engine._leads.get(lead_id)
            if lead_obj:
                # `Any` on purpose: `engine._leads` is annotated dict[str, LeadResult]
                # but persistence.load_leads() and capture.py also park plain dicts
                # and _CaptureLead objects in it, so the as_dict()/raw split below
                # is load-bearing. Annotating the concrete union here would force a
                # narrowing that changes which branch runs.
                lead_dict: Any = lead_obj.as_dict() if hasattr(lead_obj, "as_dict") else lead_obj
                lead_dict["business_name"] = business_config.get_config().get("business_name", "Our Business")
                nurture.create_sequence(lead_dict)
                logger.info("Nurture sequence created", extra={"lead_id": lead_id})
    except Exception:
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
async def generate_ad_copy(data: dict[str, Any], request: Request):
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
async def generate_keywords(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    industry = data.get("industry", "").strip()
    if not industry:
        raise HTTPException(400, "industry is required")
    result = ads_gen.generate_keywords(industry=industry, location=data.get("location", ""))
    return {"ok": True, "keywords": result}


@app.post("/api/ads/generate-pixel")
async def generate_pixel(data: dict[str, Any], request: Request):
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
async def inject_pixels(data: dict[str, Any], request: Request):
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
async def generate_utm(data: dict[str, Any], request: Request):
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


# ─── Ad Platform API Campaigns ────────────────────────────────────


@app.get("/api/ads/platforms/status")
async def ads_platform_status(request: Request):
    verify_api_key(request)
    return ad_platforms.status()


@app.get("/api/ads/campaigns")
async def ads_list_campaigns(request: Request):
    verify_api_key(request)
    from engine.database import Database

    with Database.get_connection() as conn:
        rows = conn.execute("SELECT * FROM ad_campaigns ORDER BY created_at DESC").fetchall()
    return {"campaigns": [dict(r) for r in rows]}


@app.post("/api/ads/platforms/launch")
async def ads_platform_launch(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request, tokens=3)
    # Accept frontend field names (campaign_name, trade, daily_budget) or backend names (name, industry, budget_cents)
    name = data.get("campaign_name") or data.get("name") or ""
    industry = data.get("trade") or data.get("industry") or ""
    platform = data.get("platform", "google")
    location = data.get("location", "")
    # Accept either spelling of the budget. `daily_budget` is DOLLARS and
    # `budget_cents` is CENTS, and the two must not be conflated.
    #
    # CRITICAL (audit 2026-09-27): this used to be
    #     budget_cents = int(float(daily_budget) * 100) if float(daily_budget) < 10000
    #                    else int(daily_budget)
    # applied to BOTH spellings, so a caller sending the backend spelling
    # budget_cents=5000 (i.e. $50) got 5000 * 100 = 500000 cents = $5,000/day.
    # A 100x money error from an ambiguous heuristic. Branch on which key the
    # caller actually sent.
    if data.get("budget_cents") is not None and data.get("daily_budget") is None:
        daily_budget = float(data["budget_cents"]) / 100.0
    else:
        daily_budget = float(data.get("daily_budget") or 50)
    objective = data.get("objective", "leads")
    landing_page = data.get("landing_page_url") or data.get("landing_page", "")

    if not name or not industry:
        raise HTTPException(400, "name/campaign_name and trade/industry are required")

    # daily_budget is now always normalised to DOLLARS above, so this is a plain
    # unit conversion with no heuristic.
    # round() with no ndigits already returns an int, so the outer int() was
    # redundant.
    budget_cents = round(float(daily_budget) * 100)

    copy = ads_gen.generate_ad_copy(
        industry=industry,
        location=location,
        usp=data.get("usp", ""),
        platform="google" if platform in ("google", "google_ads", "both") else "facebook",
        count=1,
    )[0]

    keywords = ads_gen.generate_keywords(industry=industry, location=location)

    plan = AdCampaignPlan(
        platform=platform,
        name=name,
        budget_cents=budget_cents,
        industry=industry,
        location=location,
        headline=copy["headline"],
        description=copy["description"],
        cta=copy["cta"],
        keywords=keywords.get("broad", []),
        landing_page_url=landing_page,
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
    )

    result = await ad_platforms.launch(plan)

    # CRITICAL (audit 2026-09-27, C-3): the campaign_id was previously minted
    # unconditionally and the row persisted with status='created', so a SIMULATED
    # preview (no ad credentials) appeared in the campaigns list and the UI alerted
    # "Campaign created!" -- a fabricated external side effect the user would act on.
    # Now: a simulation is labelled as such, persisted as 'simulated', and carries NO
    # fabricated campaign id. A real launch uses the provider's own id.
    simulated = bool(result.get("simulated"))
    provider_ids = result.get("provider_campaign_ids") or []
    if simulated or not provider_ids:
        campaign_id = f"preview_{uuid.uuid4().hex[:12]}"
        db_status = "simulated"
    else:
        campaign_id = provider_ids[0]
        db_status = "created"

    # Persist to database
    from engine.database import Database

    with Database.get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ad_campaigns
                (campaign_id, name, platform, industry, location, daily_budget_dollars, objective,
                 status, headline, description, cta, keywords, landing_page_url, platform_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                campaign_id,
                name,
                platform,
                industry,
                location,
                float(daily_budget),
                objective,
                db_status,
                copy["headline"],
                copy["description"],
                copy["cta"],
                json.dumps(keywords.get("broad", [])),
                landing_page,
                json.dumps({k: v for k, v in result.items() if k != "plan"}),
            ),
        )
        conn.commit()

    result["campaign_id"] = campaign_id
    result["simulated"] = simulated
    if simulated:
        result["message"] = (
            "Preview only -- no ad platform credentials are configured, so no campaign "
            "was created. Add credentials in Settings to launch for real."
        )
    return result


# ─── Nurture Engine ────────────────────────────────────────────────


@app.post("/api/nurture/sequence")
async def create_nurture_sequence(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    lead_data = data.get("lead", data)
    result = nurture.create_sequence(lead_data)
    return {"ok": True, "sequence": result}


@app.post("/api/nurture/incoming-reply")
async def nurture_incoming_reply(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    sequence_id = data.get("sequence_id", "").strip()
    reply_text = data.get("reply_text", "").strip()
    if not sequence_id or not reply_text:
        raise HTTPException(400, "sequence_id and reply_text are required")
    result = await nurture.handle_incoming_reply(sequence_id, reply_text)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed to process reply"))
    return result


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
async def mark_action_sent(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    seq_id = data.get("sequence_id", "")
    action_idx = data.get("action_index", 0)
    ok = nurture.mark_action_sent(seq_id, action_idx)
    if not ok:
        raise HTTPException(404, "Sequence or action not found")
    return {"ok": True}


@app.post("/api/nurture/schedule")
async def schedule_appointment(data: dict[str, Any], request: Request):
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
async def update_business_config(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    # update_config raises a bare ValueError for a bad or negative value. Left
    # uncaught that became an unhandled 500, so a client sending "abc" for a
    # float field got a server error instead of a 400 -- and the response body
    # leaked a traceback.
    try:
        return business_config.update_config(data)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/business/metrics")
async def get_business_metrics():
    return business_config.get_metrics()


@app.post("/api/business/evaluate-lead")
async def evaluate_lead_economics(request: Request):
    verify_api_key(request)
    body = await request.json()
    trade_id = body.get("trade", "")
    lead_score = body.get("lead_score", 50)
    trade = get_trade_config(trade_id)
    if not trade:
        raise HTTPException(400, f"Unknown trade: {trade_id}")
    return business_config.evaluate_lead(
        trade_avg_job_value=trade.get("avg_job_value", 0),
        trade_cpl_ceiling=trade.get("lead_cpl_ceiling", 0),
        lead_score=lead_score,
    )


@app.post("/api/simulator/project-roi")
async def simulator_project_roi(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    trade = data.get("trade", "").strip()
    location = data.get("location", "").strip()
    daily_budget = float(data.get("daily_budget", 50.0))
    if not trade or not location:
        raise HTTPException(400, "trade and location are required")
    try:
        result = campaign_simulator.project_roi(trade, location, daily_budget)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/chat/collaborate")
async def chat_collaborate(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request)
    user_message = data.get("message", "").strip()
    history = data.get("history", [])
    if not user_message:
        raise HTTPException(400, "message is required")

    system_prompt = (
        "You are LeadForge Copilot, a helpful B2B growth and lead generation assistant. "
        "You help users configure verticals, search for local contractor/trade leads, setup campaigns, "
        "and run ROI simulations.\n\n"
        "Key capabilities of LeadForge:\n"
        "- Verticals page: Setup industries and budget constraints.\n"
        "- Search page: Find business contacts using Exa/Perplexity.\n"
        "- Enrichment page: Get phone/email for lead lists.\n"
        "- Key Vault: Safe storage of API keys.\n"
        "- ROI Simulator: Simulates B2B campaign margins and customer conversions.\n\n"
        "You can guide users on these topics. "
        "Answer in a professional, brief manner (under 4 sentences)."
    )

    perplexity_key = KeyVault.get("perplexity") or os.environ.get("PERPLEXITY_API_KEY")
    response_text = ""
    if perplexity_key:
        try:
            import httpx

            messages = [{"role": "system", "content": system_prompt}]
            for h in history[-6:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
            messages.append({"role": "user", "content": user_message})

            headers = {"Authorization": f"Bearer {perplexity_key}", "Content-Type": "application/json"}
            body = {"model": "sonar-pro", "messages": messages, "max_tokens": 300}
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.perplexity.ai/chat/completions", json=body, headers=headers
                )
                if resp.status_code == 200:
                    response_text = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("Perplexity chat failed: %s", e)

    if not response_text:
        msg_lower = user_message.lower()
        if "simulate" in msg_lower or "roi" in msg_lower:
            response_text = (
                "I can help you model B2B margins and projected ROI! "
                "Ask me to simulate a specific trade, location, and daily budget. "
                "Example: 'simulate plumbing in Dallas TX with a budget of 100'."
            )
        elif "search" in msg_lower or "find" in msg_lower or "sourcing" in msg_lower:
            response_text = (
                "You can search for new trade lists directly on our [Search Page](#search). "
                "Just input a trade and a target area to start scraping high-intent leads."
            )
        elif "vertical" in msg_lower or "industry" in msg_lower:
            response_text = (
                "To configure lead criteria and platform options, head over to the [Verticals Page](#verticals). "
                "There you can add custom keyword lists and job values."
            )
        elif "vault" in msg_lower or "key" in msg_lower or "api" in msg_lower:
            response_text = (
                "Need to update your system integrations or LLM keys? "
                "Please configure them in your [Key Vault](#vault) for safe storage."
            )
        else:
            response_text = (
                "Hello! I am your LeadForge AI Copilot. I can recommend B2B outreach strategies, "
                "help you run ROI simulations, search for high-intent leads, or setup your key vault. "
                "How can I help you grow your business today?"
            )

    return {"ok": True, "response": response_text}


@app.get("/api/business/plans")
async def list_business_plans():
    from engine.stripe_integration import PLANS

    return {
        "plans": [
            {"id": plan, "monthly_cents": cents, "monthly_dollars": cents / 100}
            for plan, cents in PLANS.items()
        ]
    }


# ─── CRM Push History ──────────────────────────────────────────────


@app.get("/api/crm/history")
async def get_crm_history(limit: int = Query(20, le=100)):
    return {"history": crm_push.get_history(limit=limit)}


@app.get("/api/crm/stats")
async def get_crm_stats():
    return crm_push.get_stats()


# ─── Multi-Tenant Auth ──────────────────────────────────────────────


@app.post("/api/auth/register", dependencies=[])
async def auth_register(data: dict[str, Any]):
    email = data.get("email", "").strip()
    password = data.get("password", "")
    name = data.get("name", "").strip()
    org_name = data.get("org_name", "").strip() or f"{name}'s Org"
    if not email or not password or not name:
        raise HTTPException(400, "email, password, and name are required")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    try:
        result = auth_manager.register(email, password, name, org_name)
        return {"ok": True, **result}
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/auth/login", dependencies=[])
async def auth_login(data: dict[str, Any]):
    email = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        raise HTTPException(400, "email and password are required")
    try:
        result = auth_manager.login(email, password)
        return {"ok": True, **result}
    except ValueError as e:
        raise HTTPException(401, str(e))


@app.get("/api/auth/me")
async def auth_me(request: Request):
    verify_api_key(request)
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    user_id = user.get("sub") or user.get("user_id")
    if not user_id:
        raise HTTPException(401, "Invalid token")
    u = auth_manager.get_user(user_id)
    if not u:
        raise HTTPException(404, "User not found")
    org = auth_manager.get_org(u["org_id"])
    return {"user": u, "org": org}


@app.get("/api/auth/api-keys")
async def auth_list_keys(request: Request):
    verify_api_key(request)
    # A caller presenting the server's own static API_KEY passes verify_api_key
    # but never gets a request.state.user, so the .get() below raised
    # AttributeError -> 500. 401 is the correct answer, as /api/auth/me already does.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    user_id = user.get("sub") or user.get("user_id")
    if not user_id:
        raise HTTPException(401, "Not authenticated")
    return {"keys": auth_manager.list_api_keys(user_id)}


@app.post("/api/auth/api-keys")
async def auth_create_key(data: dict[str, Any], request: Request):
    verify_api_key(request)
    # See auth_list_keys: no request.state.user (static server key) -> 401, not 500.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    user_id = user.get("sub") or user.get("user_id")
    org_id = user.get("org_id")
    if not user_id or not org_id:
        raise HTTPException(401, "Not authenticated")
    name = data.get("name", "default")
    key = auth_manager.create_api_key(user_id, org_id, name)
    return {"ok": True, "api_key": key, "name": name}


@app.delete("/api/auth/api-keys/{key_id}")
async def auth_delete_key(key_id: str, request: Request):
    verify_api_key(request)
    # See auth_list_keys: no request.state.user (static server key) -> 401, not 500.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    user_id = user.get("sub") or user.get("user_id")
    if not user_id:
        raise HTTPException(401, "Not authenticated")
    ok = auth_manager.delete_api_key(key_id, user_id)
    if not ok:
        raise HTTPException(404, "API key not found")
    return {"ok": True}


@app.get("/api/auth/verticals")
async def auth_list_verticals(request: Request):
    verify_api_key(request)
    # See auth_list_keys: no request.state.user (static server key) -> 401, not 500.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(401, "Not authenticated")
    return {"verticals": auth_manager.get_org_verticals(org_id)}


@app.post("/api/auth/verticals")
async def auth_add_vertical(data: dict[str, Any], request: Request):
    verify_api_key(request)
    # See auth_list_keys: no request.state.user (static server key) -> 401, not 500.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(401, "Not authenticated")
    name = data.get("name", "").strip()
    slug = data.get("slug", "").strip() or name.lower().replace(" ", "-")
    config = data.get("config", {})
    if not name:
        raise HTTPException(400, "name is required")
    result = auth_manager.add_vertical(org_id, name, slug, config)
    return {"ok": True, "vertical": result}


@app.put("/api/auth/verticals/{vertical_id}")
async def auth_update_vertical(vertical_id: str, data: dict[str, Any], request: Request):
    verify_api_key(request)
    # See auth_list_keys: no request.state.user (static server key) -> 401, not 500.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(401, "Not authenticated")
    ok = auth_manager.update_vertical(vertical_id, org_id, data)
    if not ok:
        raise HTTPException(404, "Vertical not found")
    return {"ok": True}


@app.delete("/api/auth/verticals/{vertical_id}")
async def auth_delete_vertical(vertical_id: str, request: Request):
    verify_api_key(request)
    # See auth_list_keys: no request.state.user (static server key) -> 401, not 500.
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(401, "Not authenticated")
    ok = auth_manager.delete_vertical(vertical_id, org_id)
    if not ok:
        raise HTTPException(404, "Vertical not found")
    return {"ok": True}


@app.get("/app", response_class=HTMLResponse)
async def saas_app():
    path = STATIC_DIR / "app.html"
    if path.exists():
        return HTMLResponse(path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>App</h1><p>App UI not found.</p>")


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
async def discover_trade_leads(data: dict[str, Any], request: Request):
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
    scored = [dict(lead.to_dict(), score=round(lead.score, 1)) for lead in leads]
    return {"ok": True, "trade": trade, "location": location, "leads": scored, "count": len(scored)}


@app.post("/api/trades/discover-all")
async def discover_all_trades(data: dict[str, Any], request: Request):
    verify_api_key(request)
    rate_limit(request, tokens=5)
    location = data.get("location", "").strip()
    if not location:
        raise HTTPException(400, "location is required")
    trades = data.get("trades")
    results = await trade_discovery.discover_all(trades=trades, location=location)
    flattened = {}
    for trade, leads in results.items():
        flattened[trade] = [dict(lead.to_dict(), score=round(lead.score, 1)) for lead in leads]
    return {"ok": True, "location": location, "trades": flattened}


# ─── Lead → Account → Payment Pipeline ────────────────────────────


@app.post("/api/trades/convert")
async def convert_lead(data: dict[str, Any], request: Request):
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
async def create_checkout_session(data: dict[str, Any], request: Request):
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
async def billing_portal(data: dict[str, Any], request: Request):
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
async def cancel_subscription(data: dict[str, Any], request: Request):
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

_orchestrator: EnrichOrchestrator | None = None


def _get_enrich_orch(routing_mode: str = "parallel") -> EnrichOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EnrichOrchestrator(routing_mode=routing_mode)
    return _orchestrator


@app.get("/api/enrich/routing")
async def enrich_routing_info(request: Request):
    verify_api_key(request)
    orch = _get_enrich_orch()
    return orch.get_routing_info()


@app.get("/api/enrich/providers")
async def enrich_providers(request: Request):
    verify_api_key(request)
    orch = _get_enrich_orch()
    return {
        "providers": orch.list_providers(),
        "available": any(p["available"] for p in orch.list_providers()),
    }


@app.put("/api/enrich/providers/{service}")
async def toggle_provider(service: str, request: Request):
    verify_api_key(request)
    body = await request.json()
    enabled = body.get("enabled", True)
    orch = _get_enrich_orch()
    if not orch.set_provider_enabled(service, enabled):
        raise HTTPException(404, f"Unknown provider: {service}")
    return {"name": service, "enabled": enabled}


@app.post("/api/enrich/lead")
async def enrich_single_lead(request: Request, routing_mode: str = "parallel"):
    verify_api_key(request)
    body = await request.json()
    business_name = body.get("business_name", "")
    trade = body.get("trade", "")
    if not business_name or not trade:
        raise HTTPException(400, "business_name and trade are required")
    orch = _get_enrich_orch(routing_mode=routing_mode)
    result = await orch.enrich(
        business_name=business_name,
        trade=trade,
        location=body.get("location"),
        website=body.get("website"),
        phone=body.get("phone"),
    )
    return result.to_dict()


@app.post("/api/enrich/batch")
async def enrich_batch(request: Request, routing_mode: str = "parallel"):
    verify_api_key(request)
    body = await request.json()
    leads = body.get("leads", [])
    if not leads:
        raise HTTPException(400, "leads array is required")
    orch = _get_enrich_orch(routing_mode=routing_mode)
    # BUG (audit 2026-09-27): orch.enrich_batch() does
    #   await asyncio.gather(*(self.enrich(**lead) for lead in leads),
    #                         return_exceptions=True)
    # but `business_name` is a REQUIRED positional of enrich(), so a single row
    # missing that key raises TypeError *inside the generator expression* -- before
    # gather is ever called. return_exceptions=True therefore never saw it, the
    # whole request 500'd, and every good row in the batch was lost. Validate the
    # shape here so a bad row becomes a per-row error entry (which the response
    # builder below already knows how to render) instead of killing the batch.
    prepared = []
    for i, lead in enumerate(leads):
        if not isinstance(lead, dict):
            prepared.append({"business_name": "", "trade": "", "_error": f"row {i} is not an object"})
            continue
        if not lead.get("business_name"):
            prepared.append(
                {
                    **lead,
                    "business_name": "",
                    "trade": lead.get("trade", ""),
                    "_error": f"row {i} is missing business_name",
                }
            )
            continue
        prepared.append(lead)

    results = await orch.enrich_batch(prepared)
    out = []
    # strict=True: a short result list would silently drop the unpaired leads
    # and still return HTTP 200, losing data with no signal.
    for lead, r in zip(prepared, results, strict=True):
        if lead.get("_error"):
            out.append(
                {
                    "error": lead["_error"],
                    "business_name": lead.get("business_name", ""),
                    "trade": lead.get("trade", ""),
                }
            )
        elif isinstance(r, EnrichmentResult):
            out.append(r.to_dict())
        else:
            out.append({"error": str(r)})
    return {
        "total": len(out),
        "failed": sum(1 for r in out if "error" in r),
        "results": out,
    }


@app.get("/api/enrich/from-lead/{lead_id}")
async def enrich_from_lead(lead_id: str, request: Request):
    verify_api_key(request)
    lead = engine.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    orch = _get_enrich_orch()
    # BUG (audit 2026-09-27): a search-discovered LeadResult has no
    # business_name / trade / website attributes, so this call enriched an EMPTY
    # name against every provider -- a guaranteed no-op that still returned 200
    # and a "confidence" number. Fall back to the fields LeadResult does carry.
    result = await orch.enrich(
        business_name=lead.get("business_name") or lead.get("title", ""),
        trade=lead.get("trade") or lead.get("industry", ""),
        location=lead.get("location"),
        website=lead.get("website") or lead.get("url"),
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
    uvicorn.run("main:app", host=host, port=port, reload=os.getenv("RELOAD", "0") == "1")
