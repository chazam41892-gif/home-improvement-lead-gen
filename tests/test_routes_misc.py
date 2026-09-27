"""Route tests: /api/discovery/sources|run|jobs|leads, /health, the error
handlers, and the mutation/edge paths of the routes covered elsewhere.

tests/test_discovery_api.py already exercises /api/discovery/sources, /run
validation and the run-returns-skipped path. This file covers what it does not:
job listing after a run, the 502 branch, the health contract in detail, and the
two app.exception_handler registrations.
"""
from __future__ import annotations

import pytest

import main
from tests.routes_fixtures import *  # noqa: F401,F403 -- pytest fixtures


# ── /health ──────────────────────────────────────────────────────────────
def test_health_reports_the_full_configuration_contract(client):
    r = client.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["version"] == "3.2.0"
    assert d["auth_enabled"] is True, "the suite runs with API_KEY set"
    assert d["total_leads"] == 0
    assert isinstance(d["uptime_sec"], int)
    assert d["uptime_sec"] >= 0
    # timestamp must be a real ISO-8601 UTC instant.
    from datetime import datetime
    datetime.fromisoformat(d["timestamp"])  # raises if malformed


def test_health_reports_every_integration_flag(client):
    d = client.get("/health").json()
    for key in ("stripe_configured", "perplexity_configured",
                "google_ads_configured", "meta_ads_configured"):
        assert key in d, f"{key} missing from /health"
    # EXA is reported under a redacted label, not a plain exa_configured key.
    assert any("exa" in k.lower() or "redacted" in k.lower() for k in d), list(d)


def test_health_lists_the_missing_configuration(client):
    d = client.get("/health").json()
    missing = d["missing_config"]
    assert isinstance(missing, dict)
    # STRIPE_SECRET_KEY is blanked by conftest, so it must be reported missing.
    assert "STRIPE_SECRET_KEY" in missing
    assert "EXA_API_KEY" in missing
    assert all(isinstance(v, str) and v for v in missing.values())


def test_health_needs_no_auth(anon):
    """A load balancer polls /health unauthenticated; it must stay open."""
    assert anon.get("/health").status_code == 200


def test_health_total_leads_tracks_the_store(client):
    assert client.get("/health").json()["total_leads"] == 0
    seed_lead("L1")
    assert client.get("/health").json()["total_leads"] == 1


# ── /api/discovery/run ───────────────────────────────────────────────────
def test_discovery_run_rejects_an_unknown_source(client):
    r = client.post("/api/discovery/run", json={"sources": ["myspace"]})
    assert r.status_code == 400
    assert "myspace" in r.json()["error"]


def test_discovery_run_accepts_every_known_source(client, monkeypatch):
    """The allowlist must cover FREE_SOURCES, KEYED_SOURCES and the 'url' escape."""
    from engine.discovery import ScrapeJob, TargetProfile

    async def fake_run(profile, sources):
        return ScrapeJob(
            id="discovery_test", profile=profile, sources_used=list(sources),
            status="completed", created_at=0.0, raw_results=[],
        )

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    r = client.post("/api/discovery/run", json={
        "sources": ["google_maps", "reddit", "craigslist", "github", "url", "exa", "tavily"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    assert set(r.json()["sources_used"]) == {
        "google_maps", "reddit", "craigslist", "github", "url", "exa", "tavily"}


def test_discovery_run_502s_when_the_job_fails(client, monkeypatch):
    """A failed job must be a 502 carrying the reason -- not a 200 'completed'."""
    from engine.discovery import ScrapeJob, TargetProfile

    async def fake_run(profile, sources):
        return ScrapeJob(
            id="discovery_fail", profile=profile, sources_used=list(sources),
            status="failed", created_at=0.0, raw_results=[],
            error="every source unavailable",
        )

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    r = client.post("/api/discovery/run", json={"customer_description": "roofers"})
    assert r.status_code == 502
    assert r.json()["error"] == "every source unavailable"


def test_discovery_run_502_falls_back_to_a_generic_message(client, monkeypatch):
    from engine.discovery import ScrapeJob

    async def fake_run(profile, sources):
        return ScrapeJob(id="d", profile=profile, sources_used=[],
                         status="failed", created_at=0.0, raw_results=[], error="")

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    r = client.post("/api/discovery/run", json={})
    assert r.status_code == 502
    assert r.json()["error"] == "Discovery failed"


def test_discovery_run_maps_query_onto_customer_description(client, monkeypatch):
    from engine.discovery import ScrapeJob

    seen = {}

    async def fake_run(profile, sources):
        seen["description"] = profile.customer_description
        seen["industry"] = profile.industry
        seen["target_count"] = profile.target_count
        return ScrapeJob(id="d", profile=profile, sources_used=[],
                         status="completed", created_at=0.0, raw_results=[])

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    client.post("/api/discovery/run", json={
        "query": "roofing contractors", "industry": "roofing", "target_count": 7})
    assert seen["description"] == "roofing contractors"
    assert seen["industry"] == "roofing"
    assert seen["target_count"] == 7


def test_discovery_run_defaults_the_target_count(client, monkeypatch):
    from engine.discovery import ScrapeJob

    seen = {}

    async def fake_run(profile, sources):
        seen["target_count"] = profile.target_count
        return ScrapeJob(id="d", profile=profile, sources_used=[],
                         status="completed", created_at=0.0, raw_results=[])

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    client.post("/api/discovery/run", json={})
    assert seen["target_count"] == 25


def test_discovery_run_casts_a_string_target_count(client, monkeypatch):
    """target_count is int()-coerced; a string from a form must not 500."""
    from engine.discovery import ScrapeJob

    seen = {}

    async def fake_run(profile, sources):
        seen["target_count"] = profile.target_count
        return ScrapeJob(id="d", profile=profile, sources_used=[],
                         status="completed", created_at=0.0, raw_results=[])

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    r = client.post("/api/discovery/run", json={"target_count": "12"})
    assert r.status_code == 200
    assert seen["target_count"] == 12
    assert isinstance(seen["target_count"], int)


def test_discovery_run_reports_a_partial_result(client, monkeypatch):
    """A job with some skipped sources must still be 200 and expose `skipped` so
    the caller can tell "found nothing" from "source unavailable"."""
    from engine.discovery import ScrapeJob

    async def fake_run(profile, sources):
        return ScrapeJob(
            id="d", profile=profile, sources_used=["reddit"],
            status="completed", created_at=0.0, raw_results=[],
            skipped={"exa": "no api key"},
        )

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    r = client.post("/api/discovery/run", json={})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "completed"
    assert d["skipped"] == {"exa": "no api key"}
    assert d["lead_count"] == 0
    assert d["raw_count"] == 0
    assert d["raw_results"] == []
    assert d["leads"] == []


def test_discovery_run_records_the_job(client, monkeypatch):
    from engine.discovery import ScrapeJob

    async def fake_run(profile, sources):
        job = ScrapeJob(id="d_recorded", profile=profile, sources_used=["reddit"],
                        status="completed", created_at=0.0, raw_results=[])
        main.discovery_engine.jobs[job.id] = job
        return job

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    client.post("/api/discovery/run", json={})
    jobs = client.get("/api/discovery/jobs").json()["jobs"]
    assert any(j["id"] == "d_recorded" for j in jobs), jobs


def test_discovery_jobs_and_leads_are_empty_at_the_start(client):
    assert client.get("/api/discovery/jobs").json() == {"jobs": []}
    assert client.get("/api/discovery/leads").json() == {"leads": []}


def test_discovery_sources_requires_auth(anon):
    assert anon.get("/api/discovery/sources").status_code == 401
    assert anon.get("/api/discovery/jobs").status_code == 401
    assert anon.get("/api/discovery/leads").status_code == 401
    assert anon.post("/api/discovery/run", json={}).status_code == 401


# ── error handlers ───────────────────────────────────────────────────────
def test_http_exception_handler_renders_error_and_code(client):
    """The app registers its own HTTPException handler, so a raised 404 comes
    back as {"error", "code"} rather than FastAPI's default {"detail"}."""
    r = client.get("/api/leads/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body == {"error": "Lead not found", "code": 404}
    assert "detail" not in body


def test_validation_errors_keep_the_default_422_shape(client):
    """A RequestValidationError is NOT an HTTPException subclass in the way the
    app handles it, so FastAPI's own {"detail": [...]} shape must survive --
    otherwise every client-side validation error changes contract."""
    r = client.post("/api/search", json={"query": 5})
    assert r.status_code == 422
    assert "detail" in r.json(), r.json()
    assert r.json()["detail"][0]["loc"][:2] == ["body", "query"]


def test_general_exception_handler_hides_internals_and_returns_500(client, monkeypatch):
    """An unhandled exception must become a generic 500 -- no traceback, no
    internal detail leaked to the caller."""
    def boom(*a, **kw):
        raise RuntimeError("secret internal path C:\\Users\\someone\\db.sqlite")

    monkeypatch.setattr(main.engine, "get_stats", boom)
    r = client.get("/api/stats")
    assert r.status_code == 500
    assert r.json() == {"error": "Internal server error", "code": 500}
    assert "secret internal path" not in r.text


def test_method_not_allowed_is_a_405(client):
    """405 comes from Starlette's router, not from a raised HTTPException, so it
    keeps FastAPI's default {"detail"} shape rather than the app's {"error","code"}.
    Pinned so a future change to the error contract is a deliberate decision."""
    r = client.post("/health")
    assert r.status_code == 405
    assert "detail" in r.json(), r.json()


def test_unknown_route_is_a_404(client):
    """Same story as the 405: an unmatched path never reaches the app's
    HTTPException handler."""
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "detail" in r.json(), r.json()
    assert "Not Found" in r.json()["detail"]


# ── cross-cutting: every guarded route rejects an unauthenticated caller ──
GUARDED = [
    ("GET", "/api/settings"),
    ("POST", "/api/search"),
    ("POST", "/api/search/natural"),
    ("GET", "/api/discovery/sources"),
    ("GET", "/api/discovery/jobs"),
    ("GET", "/api/discovery/leads"),
    ("DELETE", "/api/leads"),
    ("GET", "/api/export/csv"),
    ("GET", "/api/export/json"),
    ("POST", "/api/schedules"),
    ("POST", "/api/landing/generate"),
    ("POST", "/api/ads/generate-copy"),
    ("POST", "/api/ads/generate-keywords"),
    ("POST", "/api/ads/generate-pixel"),
    ("POST", "/api/ads/inject-pixels"),
    ("POST", "/api/ads/utm"),
    ("GET", "/api/ads/platforms/status"),
    ("GET", "/api/ads/campaigns"),
    ("POST", "/api/nurture/sequence"),
    ("POST", "/api/nurture/incoming-reply"),
    ("POST", "/api/nurture/mark-sent"),
    ("POST", "/api/nurture/schedule"),
    ("POST", "/api/business/evaluate-lead"),
    ("POST", "/api/simulator/project-roi"),
    ("POST", "/api/chat/collaborate"),
    ("POST", "/api/billing/create-checkout-session"),
    ("POST", "/api/billing/portal"),
    ("GET", "/api/billing/subscription/a1"),
    ("POST", "/api/billing/cancel"),
    ("GET", "/api/vault/keys"),
    ("GET", "/api/enrich/routing"),
    ("GET", "/api/enrich/providers"),
    ("POST", "/api/enrich/lead"),
    ("POST", "/api/enrich/batch"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/auth/api-keys"),
    ("GET", "/api/auth/verticals"),
    ("POST", "/api/trades/discover"),
    ("POST", "/api/trades/discover-all"),
    ("POST", "/api/trades/convert"),
]


@pytest.mark.parametrize("method,path", GUARDED)
def test_guarded_routes_reject_anonymous_callers(anon, method, path):
    r = anon.request(method, path, json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code in (401, 422), (
        f"{method} {path} returned {r.status_code} unauthenticated -- "
        f"expected 401. Body: {r.text[:200]}")


@pytest.mark.parametrize("method,path", [
    ("DELETE", "/api/leads/L1"),
    ("PUT", "/api/schedules/L1"),
    ("DELETE", "/api/schedules/L1"),
    ("DELETE", "/api/landing/L1"),
    ("PUT", "/api/business/config"),
    ("PUT", "/api/enrich/providers/apollo_enricher"),
    ("DELETE", "/api/vault/keys/exa"),
    ("DELETE", "/api/auth/api-keys/x"),
    ("PUT", "/api/auth/verticals/x"),
    ("DELETE", "/api/auth/verticals/x"),
])
def test_guarded_mutations_reject_anonymous_callers(anon, method, path):
    r = anon.request(method, path, json={} if method in ("POST", "PUT", "PATCH") else None)
    assert r.status_code in (401, 422), (
        f"{method} {path} returned {r.status_code} unauthenticated -- expected 401")


def test_routing_config_put_requires_auth(anon, client):
    """PUT /api/routing/config must authenticate.

    It took no `request: Request`, so it was the only mutating route of 50 that
    called verify_api_key() zero times: an anonymous caller could rewrite the
    routing pipeline -- flip crm_push or llm_score on, repoint enrichment,
    change the scoring floor -- and the response confirmed the write.
    """
    assert "request" in main.update_routing_config.__annotations__, (
        "PUT /api/routing/config lost its Request parameter -- auth may be gone.")

    before = [s["name"] for s in anon.get("/api/routing/config").json()["steps"]]

    # Anonymous write is refused, and the pipeline is left intact.
    r = anon.put("/api/routing/config",
                 json={"config": {"steps": [
                     {"name": "crm_push", "enabled": True, "config": {}}]}})
    assert r.status_code in (401, 403), f"anonymous PUT was accepted: {r.status_code}"
    after = [s["name"] for s in anon.get("/api/routing/config").json()["steps"]]
    assert after == before, "an anonymous write replaced the routing pipeline"

    # Authenticated write still works.
    r2 = client.put("/api/routing/config", json={"step": "crm_push", "enabled": False})
    assert r2.status_code in (200, 404), r2.text[:200]


@pytest.mark.parametrize("path", [
    "/api/routing/config", "/api/routing/steps", "/api/routing/history",
    "/api/routing/stats", "/api/stats", "/api/history", "/api/schedules",
    "/api/landing/list", "/api/nurture/sequences", "/api/nurture/due",
    "/api/nurture/stats", "/api/nurture/appointments", "/api/nurture/schedule/widget",
    "/api/business/config", "/api/business/metrics", "/api/business/plans",
    "/api/crm/history", "/api/crm/stats", "/api/capture/stats",
    "/api/capture/thank-you", "/api/trades", "/api/trades/accounts",
    "/api/trades/payments", "/api/trades/revenue", "/health", "/",
    "/app", "/vault",
])
def test_read_only_routes_are_reachable_without_auth(anon, path):
    """Documents the current posture: the read endpoints above carry no
    verify_api_key(). Several of them expose tenant data (nurture sequences,
    CRM history, business config), so this list is a live exposure report, not
    an endorsement. If one of these is deliberately made public, move it out of
    this list rather than widening it."""
    r = anon.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text[:200]}"


# ── response-shape guards for the thin list endpoints ────────────────────
def test_all_routes_are_registered(client):
    """The app must expose the full documented surface; a route deleted by a
    refactor should fail here rather than 404 in production."""
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/health", "/api/settings", "/api/settings/key",
        "/api/routing/config", "/api/routing/steps", "/api/routing/history",
        "/api/routing/stats", "/api/search", "/api/search/natural",
        "/api/discovery/sources", "/api/discovery/run", "/api/discovery/jobs",
        "/api/discovery/leads", "/api/discovery/ingest",
        "/api/leads", "/api/leads/{lead_id}", "/api/export/csv", "/api/export/json",
        "/api/stats", "/api/history", "/api/search/multi",
        "/api/schedules", "/api/schedules/{schedule_id}",
        "/api/schedules/{schedule_id}/results",
        "/api/landing/generate", "/api/landing/list", "/api/landing/{page_id}",
        "/api/capture/lead", "/api/capture/thank-you", "/api/capture/stats",
        "/api/ads/generate-copy", "/api/ads/generate-keywords",
        "/api/ads/generate-pixel", "/api/ads/inject-pixels", "/api/ads/utm",
        "/api/ads/platforms/status", "/api/ads/campaigns", "/api/ads/platforms/launch",
        "/api/nurture/sequence", "/api/nurture/incoming-reply", "/api/nurture/sequences",
        "/api/nurture/sequences/{sequence_id}", "/api/nurture/due",
        "/api/nurture/mark-sent", "/api/nurture/schedule", "/api/nurture/schedule/widget",
        "/api/nurture/appointments", "/api/nurture/stats",
        "/api/business/config", "/api/business/metrics", "/api/business/evaluate-lead",
        "/api/business/plans", "/api/simulator/project-roi", "/api/chat/collaborate",
        "/api/crm/history", "/api/crm/stats",
        "/api/auth/register", "/api/auth/login", "/api/auth/me", "/api/auth/api-keys",
        "/api/auth/verticals", "/app",
        "/api/trades", "/api/trades/accounts", "/api/trades/payments",
        "/api/trades/revenue", "/api/trades/{trade_id}", "/api/trades/discover",
        "/api/trades/discover-all", "/api/trades/convert",
        "/api/billing/create-checkout-session", "/api/billing/portal",
        "/api/billing/webhook", "/api/billing/subscription/{account_id}",
        "/api/billing/cancel",
        "/api/vault/keys", "/api/vault/keys/{service}",
        "/api/enrich/routing", "/api/enrich/providers", "/api/enrich/providers/{service}",
        "/api/enrich/lead", "/api/enrich/batch", "/api/enrich/from-lead/{lead_id}",
        "/vault", "/",
    }
    missing = expected - set(paths)
    assert not missing, f"routes missing from the app: {sorted(missing)}"


def test_every_route_declares_a_method(client):
    """Spot-check that the mutating routes are not accidentally GET-only."""
    spec = client.get("/openapi.json").json()
    for path, method in [("/api/leads", "delete"),
                         ("/api/leads/{lead_id}", "patch"),
                         ("/api/business/config", "put"),
                         ("/api/vault/keys/{service}", "delete"),
                         ("/api/auth/api-keys/{key_id}", "delete"),
                         ("/api/nurture/sequences/{sequence_id}", "delete")]:
        assert method in spec["paths"][path], (
            f"{method.upper()} {path} is missing from the OpenAPI spec")
        assert "responses" in spec["paths"][path][method]
