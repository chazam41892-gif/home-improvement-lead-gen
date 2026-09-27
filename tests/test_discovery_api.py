"""End-to-end test of the new /api/discovery/* endpoints (parity gap B).

Proves the routes exist, auth is enforced, validation rejects bad input, and the
run endpoint really reaches the discovery engine. No live network: the scraper is
monkeypatched.
"""
import pytest
from fastapi.testclient import TestClient

import main
from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c


def test_sources_endpoint_lists_free_and_keyed(client):
    r = client.get("/api/discovery/sources")
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert "google_maps" in d["free_sources"]
    assert "reddit" in d["free_sources"]
    assert "craigslist" in d["free_sources"]
    assert "github" in d["free_sources"]
    assert "exa" in d["keyed_sources"]
    assert set(d["available"]) == {"exa", "tavily", "github"}


def test_sources_endpoint_requires_auth():
    with TestClient(app) as c:
        r = c.get("/api/discovery/sources")
    assert r.status_code in (401, 403), f"unauthenticated access allowed: {r.status_code}"


def test_run_rejects_unknown_source(client):
    r = client.post("/api/discovery/run", json={"sources": ["myspace"]})
    assert r.status_code == 400
    # This app's HTTPException handler renders {"error":..., "code":...}, not
    # FastAPI's default {"detail":...}.
    assert "myspace" in r.json()["error"]


def test_run_reaches_engine_and_reports_skip(client, monkeypatch):
    """The route must actually call run_discovery and surface its skipped list."""
    seen = {}

    async def fake_run(profile, sources):
        from engine.discovery import ScrapeJob
        seen["profile"] = profile
        seen["sources"] = sources
        return ScrapeJob(id="j_test", profile=profile, sources_used=list(sources),
                         status="completed", raw_results=[], leads=[],
                         skipped=["exa:no_api_key"])

    monkeypatch.setattr(main.discovery_engine, "run_discovery", fake_run)
    r = client.post("/api/discovery/run", json={
        "customer_description": "roofing contractor",
        "keywords": ["roofing"], "locations": ["Austin, TX"],
        "sources": ["google_maps", "exa"],
    })
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["status"] == "completed"
    assert d["skipped"] == ["exa:no_api_key"]
    assert d["lead_count"] == 0
    assert seen["profile"].keywords == ["roofing"]
    assert seen["sources"] == ["google_maps", "exa"]


def test_run_502s_on_engine_failure(client, monkeypatch):
    async def boom(profile, sources):
        from engine.discovery import ScrapeJob
        return ScrapeJob(id="j", profile=profile, status="failed", error="aiohttp missing")

    monkeypatch.setattr(main.discovery_engine, "run_discovery", boom)
    r = client.post("/api/discovery/run", json={"keywords": ["x"]})
    assert r.status_code == 502
    assert "aiohttp" in r.json()["error"]


def test_ingest_endpoint_normalizes_rows(client, monkeypatch):
    r = client.post("/api/discovery/ingest", json={
        "source": "apollo",
        "leads": [{"Email": "buyer@gmail.com", "Company": "Acme", "City": "Tulsa"}],
    })
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["ingested"] == 1
    assert d["leads"][0]["company"] == "Acme"
    assert d["leads"][0]["source_type"] == "apollo"


def test_ingest_requires_leads_array(client):
    r = client.post("/api/discovery/ingest", json={"source": "apollo"})
    assert r.status_code == 400


def test_jobs_and_leads_endpoints(client):
    assert client.get("/api/discovery/jobs").status_code == 200
    assert client.get("/api/discovery/leads").status_code == 200


def test_asdict_is_imported_in_main():
    """asdict is used in discovery_run's response; a missing import would only
    surface at request time, so pin it here."""
    from dataclasses import asdict
    assert hasattr(main, "asdict"), "main.py must import asdict for /api/discovery/run"
    from engine.discovery import LeadSource
    assert asdict(LeadSource(source="x", text="y"))["source"] == "x"
