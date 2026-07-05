from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from engine.scout import LeadScoutEngine, SearchConfig
from engine.merger import merge_leads
from engine.scheduler import ScanScheduler
from engine.landing import LandingPageGenerator
from engine.capture import LeadCaptureProcessor
from engine.ads import AdCopyGenerator
from engine.nurture import NurtureEngine
from engine.business_config import BusinessConfig
from engine.crm_push import CrmPush

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("leadgen")

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

env_keys = ("EXA_", "PERPLEXITY_", "ANTHROPIC_", "COMETAPI_", "CLEARBIT_", "HUNTER_")
env_map = {k: v for k, v in os.environ.items() if k.startswith(env_keys)}
engine.set_env(env_map)

try:
    from enrichment import enrich_lead as _enrich_fn
    engine.register_enrichment_fn(_enrich_fn)
    logger.info("Enrichment module registered")
except ImportError:
    logger.info("enrichment.py not found — enrichment step will be skipped at runtime")

try:
    from scoring_llm import score_leads_batch as _llm_batch_fn
    engine.register_llm_score_fn(_llm_batch_fn)
    logger.info("LLM scoring module registered")
except ImportError:
    logger.info("scoring_llm.py not found — LLM scoring step will be skipped at runtime")

landing_gen = LandingPageGenerator()
capture_processor = LeadCaptureProcessor(engine)
capture_processor._landing_pages = landing_gen._pages
ads_gen = AdCopyGenerator()
nurture = NurtureEngine()
business_config = BusinessConfig()
crm_push = CrmPush()
crm_push.set_env(env_map)

# Wire CrmPush into router as the CRM push handler
async def _crm_push_fn(leads, config):
    provider = config.get("provider", "hubspot") if config else "hubspot"
    return await crm_push.push_leads(leads, provider=provider, config=config)

engine._router._crm_push_fn = _crm_push_fn
# Patch _run_crm_push to use the registered function
import types
orig_crm_push = engine._router._run_crm_push
async def _patched_crm_push(self, leads, step):
    fn = getattr(self, '_crm_push_fn', None)
    if fn:
        return await fn(leads, step.config)
    return await orig_crm_push(leads, step)
engine._router._run_crm_push = types.MethodType(_patched_crm_push, engine._router)

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
                logger.info(f"Nurture action due: {action['type']} for sequence {action['sequence_id']}")
                nurture.mark_action_sent(action["sequence_id"], action["action_index"])
        except Exception:
            pass
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await scheduler.start()
    loop_task = asyncio.create_task(_nurture_loop())
    yield
    await scheduler.stop()
    global _nurture_loop_running
    _nurture_loop_running = False
    loop_task.cancel()


app = FastAPI(
    title="Lead Gen Pro",
    version="3.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Settings ──────────────────────────────────────────────────────

@app.get("/api/settings")
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


# ─── Smart Routing ────────────────────────────────────────────────

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


# ─── Search ────────────────────────────────────────────────────────

@app.post("/api/search")
async def search_leads(config: SearchConfig):
    result = await engine.search(config)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Search failed"))
    return result


@app.post("/api/search/natural")
async def search_natural(data: Dict[str, Any]):
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
async def list_leads(limit: int = Query(100, le=500), min_score: float = Query(0.0)):
    return {"leads": engine.get_leads(limit=limit, min_score=min_score), "count": len(engine._leads)}


@app.get("/api/leads/{lead_id}")
async def get_lead(lead_id: str):
    lead = engine.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@app.patch("/api/leads/{lead_id}")
async def update_lead(lead_id: str, data: Dict[str, Any]):
    lead = engine.update_lead(lead_id, data)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: str):
    ok = engine.delete_lead(lead_id)
    if not ok:
        raise HTTPException(404, "Lead not found")
    return {"ok": True}


@app.delete("/api/leads")
async def clear_leads():
    engine.clear_leads()
    return {"ok": True, "message": "All leads cleared"}


# ─── Export ────────────────────────────────────────────────────────

@app.get("/api/export/csv")
async def export_csv(min_score: float = Query(0.0)):
    csv_data = engine.export_csv(min_score=min_score)
    return PlainTextResponse(csv_data, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})


@app.get("/api/export/json")
async def export_json(min_score: float = Query(0.0)):
    leads = engine.get_leads(min_score=min_score)
    return PlainTextResponse(json.dumps(leads, indent=2, default=str),
                             media_type="application/json",
                             headers={"Content-Disposition": "attachment; filename=leads.json"})


# ─── Analytics ─────────────────────────────────────────────────────

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
async def search_multi(data: Dict[str, Any]):
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
                query=query,
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

    # Re-score after merge
    scored = []
    for lead in merged["leads"]:
        rule = lead.get("score", 0)
        lead["score"] = rule
        scored.append(lead)

    merged["leads"] = scored
    merged["stats"]["errors"] = errors

    # Store in engine if any leads
    if scored:
        for lead in scored:
            engine._leads.append(lead)

    return merged


# ─── Scan Scheduler ────────────────────────────────────────────────

@app.post("/api/schedules")
async def create_schedule(data: Dict[str, Any]):
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
async def update_schedule(schedule_id: str, data: Dict[str, Any]):
    sched = scheduler.update_schedule(schedule_id, data)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    return {"ok": True, "schedule": sched.as_dict()}


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    ok = scheduler.delete_schedule(schedule_id)
    if not ok:
        raise HTTPException(404, "Schedule not found")
    return {"ok": True}


@app.get("/api/schedules/{schedule_id}/results")
async def get_schedule_results(schedule_id: str):
    if not scheduler.get_schedule(schedule_id):
        raise HTTPException(404, "Schedule not found")
    return {"schedule_id": schedule_id, "leads": scheduler.get_results(schedule_id)}


# ─── Landing Pages ────────────────────────────────────────────────

@app.post("/api/landing/generate")
async def create_landing_page(data: Dict[str, Any]):
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
async def delete_landing_page(page_id: str):
    ok = landing_gen.delete_page(page_id)
    if not ok:
        raise HTTPException(404, "Landing page not found")
    return {"ok": True}


# ─── Lead Capture ─────────────────────────────────────────────────

@app.post("/api/capture/lead")
async def capture_lead(data: Dict[str, Any]):
    source = data.pop("_source_page_id", "")
    result = capture_processor.process_submission(data, source_page_id=source)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Validation failed"))
    # Auto-create nurture sequence for captured lead
    try:
        lead_id = result.get("lead_id")
        if lead_id:
            lead_obj = engine._leads.get(lead_id)
            if lead_obj:
                lead_dict = lead_obj.as_dict() if hasattr(lead_obj, "as_dict") else lead_obj
                lead_dict["business_name"] = business_config.get_config().get("business_name", "Our Business")
                nurture.create_sequence(lead_dict)
                logger.info(f"Nurture sequence created for lead {lead_id}")
    except Exception as e:
        logger.warning(f"Failed to create nurture sequence: {e}")
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


# ─── Ad Copy Generation ───────────────────────────────────────────

@app.post("/api/ads/generate-copy")
async def generate_ad_copy(data: Dict[str, Any]):
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
async def generate_keywords(data: Dict[str, Any]):
    industry = data.get("industry", "").strip()
    if not industry:
        raise HTTPException(400, "industry is required")
    result = ads_gen.generate_keywords(industry=industry, location=data.get("location", ""))
    return {"ok": True, "keywords": result}


@app.post("/api/ads/generate-pixel")
async def generate_pixel(data: Dict[str, Any]):
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
async def inject_pixels(data: Dict[str, Any]):
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
async def generate_utm(data: Dict[str, Any]):
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
async def create_nurture_sequence(data: Dict[str, Any]):
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
async def delete_nurture_sequence(sequence_id: str):
    ok = nurture.delete_sequence(sequence_id)
    if not ok:
        raise HTTPException(404, "Sequence not found")
    return {"ok": True}


@app.get("/api/nurture/due")
async def get_due_actions():
    return {"actions": nurture.get_due_actions()}


@app.post("/api/nurture/mark-sent")
async def mark_action_sent(data: Dict[str, Any]):
    seq_id = data.get("sequence_id", "")
    action_idx = data.get("action_index", 0)
    ok = nurture.mark_action_sent(seq_id, action_idx)
    if not ok:
        raise HTTPException(404, "Sequence or action not found")
    return {"ok": True}


@app.post("/api/nurture/schedule")
async def schedule_appointment(data: Dict[str, Any]):
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
async def update_business_config(data: Dict[str, Any]):
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


# ─── Dashboard UI ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Lead Gen Pro</h1><p>Dashboard not found.</p>")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"\n  Lead Gen Pro — http://localhost:{port}")
    print(f"  API Docs    — http://localhost:{port}/docs")
    print(f"  Dashboard   — http://localhost:{port}/\n")
    uvicorn.run("main:app", host=host, port=port, reload=True)
