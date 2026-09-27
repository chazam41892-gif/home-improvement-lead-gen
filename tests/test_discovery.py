"""Tests for engine/discovery.py — the live multi-source scraper port (parity gap B).

These run with NO network: every HTTP call is monkeypatched. They verify wiring,
query generation, degradation behaviour, and lock shut the Craigslist bug found in
the SIOS original (cl_queries built but never stored -> silent no-op forever).
"""
import asyncio
import types

import pytest

from engine.discovery import (
    DiscoveryEngine, LeadSource, ScrapeJob, TargetProfile,
    FREE_SOURCES, KEYED_SOURCES,
    generate_search_queries, verify_lead_email, extract_leads_with_ai,
    scrape_reddit, scrape_google_maps, scrape_craigslist, scrape_github,
)


# ── the bug from SIOS ──────────────────────────────────────────────────────
def test_craigslist_queries_are_not_empty():
    """REGRESSION: SIOS built cl_queries then never stored it, so
    queries.get("craigslist") was always [] and the scraper was dead code."""
    p = TargetProfile(customer_description="roofing contractor",
                      keywords=["roofing"], locations=["Austin, TX"])
    q = generate_search_queries(p)
    assert "craigslist" in q, "craigslist key missing entirely"
    assert q["craigslist"], "craigslist queries empty -> scraper would be a no-op"
    assert "need roofing" in q["craigslist"]


def test_every_source_has_a_query_key():
    """run_discovery reads queries.get(name); a source with no key gets [] silently."""
    p = TargetProfile(customer_description="plumber", keywords=["plumber"],
                      locations=["Miami"])
    q = generate_search_queries(p)
    for src in list(FREE_SOURCES) + list(KEYED_SOURCES):
        if src == "url":
            continue
        assert src in q, f"source {src!r} has no query key in generate_search_queries"
        assert isinstance(q[src], list)


def test_empty_profile_still_produces_queries():
    """A blank profile must not yield empty lists that make every source a no-op."""
    q = generate_search_queries(TargetProfile())
    for src in ("google_maps", "reddit", "craigslist", "github", "exa", "tavily"):
        assert q.get(src), f"{src} produced no fallback query for an empty profile"


# ── query generation ──────────────────────────────────────────────────────
def test_queries_combine_keyword_and_location():
    p = TargetProfile(customer_description="", keywords=["hvac"],
                      locations=["Denver", "Boulder"])
    q = generate_search_queries(p)
    assert "hvac Denver" in q["google_maps"]
    assert "hvac Boulder" in q["google_maps"]


def test_reddit_queries_use_intent_prefixes():
    p = TargetProfile(customer_description="", keywords=["landscaping"], locations=[""])
    q = generate_search_queries(p)
    assert any("need a landscaping" in x for x in q["reddit"])
    assert any("looking for landscaping" in x for x in q["reddit"])


def test_location_free_profile_has_no_trailing_space():
    p = TargetProfile(customer_description="", keywords=["roofing"], locations=[""])
    for q in generate_search_queries(p)["google_maps"]:
        assert q == q.strip(), f"query has stray whitespace: {q!r}"


# ── email verification ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_verify_rejects_malformed_email():
    r = await verify_lead_email("not-an-email")
    assert r["valid_syntax"] is False
    assert r["deliverability_score"] == 0.0


@pytest.mark.asyncio
async def test_verify_accepts_syntax_for_real_domain():
    r = await verify_lead_email("owner@gmail.com")
    assert r["valid_syntax"] is True
    assert r["email"] == "owner@gmail.com"


@pytest.mark.asyncio
async def test_verify_empty_email():
    r = await verify_lead_email("")
    assert r["valid_syntax"] is False


# ── AI extraction ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_extract_parses_fenced_json():
    srcs = [LeadSource(source="reddit", text="x" * 100, url="https://reddit.com/1")]

    async def llm(prompt):
        return '```json\n[{"name":"Jane","email":"jane@x.com","intent_score":0.9}]\n```'

    leads = await extract_leads_with_ai(srcs, TargetProfile(), llm)
    assert len(leads) == 1
    assert leads[0]["name"] == "Jane"
    assert leads[0]["source_type"] == "reddit"


@pytest.mark.asyncio
async def test_extract_skips_short_text():
    srcs = [LeadSource(source="reddit", text="too short")]

    async def llm(prompt):
        raise AssertionError("LLM must not be called for <50 chars")

    assert await extract_leads_with_ai(srcs, TargetProfile(), llm) == []


@pytest.mark.asyncio
async def test_extract_survives_garbage_llm_output():
    srcs = [LeadSource(source="web", text="y" * 200)]

    async def llm(prompt):
        return "I'm sorry, I cannot do that."

    assert await extract_leads_with_ai(srcs, TargetProfile(), llm) == []


@pytest.mark.asyncio
async def test_extract_clamps_intent_score():
    srcs = [LeadSource(source="web", text="z" * 200)]

    async def llm(prompt):
        return '[{"name":"A","intent_score":5.0}]'

    leads = await extract_leads_with_ai(srcs, TargetProfile(), llm)
    assert leads[0]["intent_score"] == 1.0


# ── engine behaviour ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_run_discovery_reports_skipped_source_without_key(monkeypatch):
    """A missing API key must be reported, not silently dropped and not a crash."""
    e = DiscoveryEngine()

    async def fake_exa(queries, api_key=""):
        return []
    monkeypatch.setattr("engine.discovery.scrape_exa", fake_exa)
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    job = await e.run_discovery(TargetProfile(keywords=["roofing"]), ["exa"])
    assert job.status == "completed"
    assert any("no_api_key" in s for s in job.skipped), job.skipped


@pytest.mark.asyncio
async def test_run_discovery_marks_unknown_source(monkeypatch):
    e = DiscoveryEngine()
    job = await e.run_discovery(TargetProfile(keywords=["x"]), ["not_a_source"])
    assert any("unknown_source" in s for s in job.skipped)


@pytest.mark.asyncio
async def test_run_discovery_without_llm_reports_it(monkeypatch):
    """No LLM => no leads, and that fact is recorded rather than shown as success."""
    e = DiscoveryEngine()

    async def fake_maps(queries):
        return [LeadSource(source="google_maps", text="a" * 300, url="https://maps")]
    monkeypatch.setattr("engine.discovery.scrape_google_maps", fake_maps)

    job = await e.run_discovery(TargetProfile(keywords=["roofing"]), ["google_maps"])
    assert job.status == "completed"
    assert any("no_llm" in s for s in job.skipped), job.skipped
    assert job.leads == []


@pytest.mark.asyncio
async def test_run_discovery_records_push_count_hook(monkeypatch):
    e = DiscoveryEngine()

    async def fake_llm(prompt):
        # gmail.com has real MX; using a reserved/non-resolving domain here would
        # (correctly) mark the lead unverified and make the assertion meaningless.
        return '[{"name":"A","email":"a@gmail.com"}]'
    e.set_llm(fake_llm)

    async def fake_maps(queries):
        return [LeadSource(source="google_maps", text="a" * 300, url="https://maps")]
    monkeypatch.setattr("engine.discovery.scrape_google_maps", fake_maps)

    job = await e.run_discovery(TargetProfile(keywords=["roofing"]), ["google_maps"])
    assert len(job.leads) == 1
    assert job.leads[0]["email_verified"] is True


@pytest.mark.asyncio
async def test_run_discovery_catches_scraper_exception(monkeypatch):
    e = DiscoveryEngine()

    async def boom(queries):
        raise RuntimeError("upstream 500")
    monkeypatch.setattr("engine.discovery.scrape_reddit", boom)

    job = await e.run_discovery(TargetProfile(keywords=["x"]), ["reddit"])
    assert job.status == "failed"
    assert "upstream 500" in job.error


@pytest.mark.asyncio
async def test_webhook_ingest_normalizes_caps_keys(monkeypatch):
    e = DiscoveryEngine()
    out = await e.ingest_webhook_leads(
        [{"Email": "a@b.com", "Company": "Acme", "City": "Tulsa"}], source_name="apollo")
    assert out[0]["email"] == "a@b.com"
    assert out[0]["company"] == "Acme"
    assert out[0]["location"] == "Tulsa"
    assert e.get_leads()[0]["source_type"] == "apollo"


def test_job_is_registered_and_listed():
    e = DiscoveryEngine()
    e.jobs["j1"] = ScrapeJob(id="j1", profile=TargetProfile())
    assert len(e.get_jobs()) == 1


# ── source availability must be reported, not silently empty (2026-09-27) ──
@pytest.mark.asyncio
async def test_blocked_reddit_is_reported_in_skipped(monkeypatch):
    """Reddit returns 403 from datacenter IPs. An empty result must NOT look the
    same as 'no matching posts' — the block has to surface in job.skipped."""
    import engine.discovery as disc

    async def blocked(queries, subreddits=None):
        disc.last_reddit_error = "HTTP 403 Blocked"
        return []

    monkeypatch.setattr(disc, "scrape_reddit", blocked)
    e = DiscoveryEngine()
    job = await e.run_discovery(TargetProfile(keywords=["roofing"]), ["reddit"])
    assert job.status == "completed"
    assert any("reddit:blocked" in s for s in job.skipped), job.skipped


@pytest.mark.asyncio
async def test_reddit_success_clears_previous_error(monkeypatch):
    """A successful run after a blocked one must not keep reporting the block."""
    import engine.discovery as disc

    async def ok(queries, subreddits=None):
        disc.last_reddit_error = ""
        return [LeadSource(source="reddit", text="x" * 200)]

    monkeypatch.setattr(disc, "scrape_reddit", ok)
    e = DiscoveryEngine()
    job = await e.run_discovery(TargetProfile(keywords=["roofing"]), ["reddit"])
    assert not any("reddit:blocked" in s for s in job.skipped), job.skipped


def test_google_maps_rejects_js_shell(monkeypatch):
    """A 200 response whose text is a JS shell (<200 chars) is NOT a lead."""
    import engine.discovery as disc

    class _Resp:
        status = 200

        async def text(self):
            return "<html><body><div id=app></div></body></html>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Sess:
        def __init__(self, *a, **k):
            pass

        def get(self, *a, **k):
            return _Resp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Sess)
    import asyncio
    out = asyncio.run(disc.scrape_google_maps(["roofing Austin"]))
    assert out == [], "JS-rendered shell must not be reported as a lead"
