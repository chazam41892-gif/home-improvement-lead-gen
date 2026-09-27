"""Tests for the DiscoveryEngine orchestrator in engine/discovery.py (audit 2026-09-27).

The existing tests/test_discovery.py covers query generation, extraction, and the
degradation paths. This file targets what is left: the source-selection switch
inside run_discovery, api_keys_used masking, job/bookkeeping, email
verification, and webhook ingest normalisation.

Scrapers are monkeypatched on the module (that is the seam run_discovery
resolves at call time, via the dict it builds inside the function), so the real
source-gating logic — keyed-source checks, unknown sources, bs4 gating, the
reddit blocked/report path — is exercised without any network.
"""
import pytest

import engine.discovery as disc
from engine.discovery import (
    DiscoveryEngine,
    LeadSource,
    ScrapeJob,
    TargetProfile,
    verify_lead_email,
)


@pytest.fixture
def engine():
    return DiscoveryEngine()


def _src(source="web", n=200):
    return LeadSource(source=source, text="x" * n, url=f"https://{source}.test/1")


# ── api key handling ───────────────────────────────────────────────────────
def test_set_api_key_stores_per_source(engine):
    engine.set_api_key("exa", "exa-secret-key-value")
    engine.set_api_key("tavily", "tv-secret-key-value")
    assert engine._api_keys == {"exa": "exa-secret-key-value",
                                "tavily": "tv-secret-key-value"}


async def test_api_keys_used_is_masked_in_the_job(engine, monkeypatch):
    """A full key must never be written into a job record that gets serialised.
    Masking is `value[:8] + "..."`."""
    engine.set_api_key("exa", "SUPERSECRETKEY1234567890")
    monkeypatch.setattr(disc, "scrape_exa", lambda q, k="": _coro([]))
    job = await engine.run_discovery(TargetProfile(), ["exa"])
    assert job.api_keys_used == {"exa": "SUPERSEC..."}, job.api_keys_used
    assert "SUPERSECRETKEY1234567890" not in str(job.api_keys_used)


async def test_api_keys_used_only_includes_requested_sources(engine, monkeypatch):
    engine.set_api_key("exa", "exa-key-value-1234")
    engine.set_api_key("tavily", "tav-key-value-1234")
    job = await engine.run_discovery(TargetProfile(), ["exa"])
    assert set(job.api_keys_used) == {"exa"}, job.api_keys_used


async def test_a_keyed_source_runs_when_the_key_is_set(engine, monkeypatch):
    seen = {}

    async def fake_tavily(queries, api_key=""):
        seen["key"] = api_key
        return []

    engine.set_api_key("tavily", "tav-key-1234")
    monkeypatch.setattr(disc, "scrape_tavily", fake_tavily)
    job = await engine.run_discovery(TargetProfile(), ["tavily"])
    assert seen["key"] == "tav-key-1234", "the configured key must reach the scraper"
    assert not any("no_api_key" in s for s in job.skipped), job.skipped


async def test_a_keyed_source_runs_off_the_environment_key(engine, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "env-tav-key-1234")
    called = []

    async def fake_tavily(queries, api_key=""):
        called.append(api_key)
        return []

    monkeypatch.setattr(disc, "scrape_tavily", fake_tavily)
    job = await engine.run_discovery(TargetProfile(), ["tavily"])
    assert called, "an env-provided key must satisfy the keyed-source gate"
    assert not any("no_api_key" in s for s in job.skipped), job.skipped


async def test_exa_and_tavily_are_both_gated_on_their_own_key(engine, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    job = await engine.run_discovery(TargetProfile(), ["exa", "tavily"])
    assert "exa:no_api_key" in job.skipped, job.skipped
    assert "tavily:no_api_key" in job.skipped, job.skipped


def _coro(value):
    async def _inner(*a, **k):
        return value
    return _inner


# ── job bookkeeping ────────────────────────────────────────────────────────
async def test_job_id_and_timestamps_are_set(engine, monkeypatch):
    monkeypatch.setattr(disc, "scrape_url", lambda q: _coro([]))
    job = await engine.run_discovery(TargetProfile(), [])
    assert job.id.startswith("discovery_")
    assert job.created_at > 0
    assert job.completed_at >= job.created_at
    assert job.status == "completed"


async def test_job_is_retrievable_from_the_engine(engine, monkeypatch):
    job = await engine.run_discovery(TargetProfile(), [])
    assert job.id in engine.jobs
    listed = engine.get_jobs()
    assert len(listed) == 1
    # get_jobs() uses dataclasses.asdict, so a LeadSource must serialise too.
    assert listed[0]["id"] == job.id


async def test_sources_used_records_the_requested_list(engine):
    job = await engine.run_discovery(TargetProfile(), ["reddit", "not_a_source"])
    assert job.sources_used == ["reddit", "not_a_source"]


async def test_completed_job_has_no_error(engine):
    job = await engine.run_discovery(TargetProfile(), [])
    assert job.status == "completed"
    assert job.error == ""


async def test_raw_results_accumulate_across_sources(engine, monkeypatch):
    async def maps(queries):
        return [_src("google_maps")]

    async def reddit(queries, subreddits=None):
        return [_src("reddit")]

    monkeypatch.setattr(disc, "scrape_google_maps", maps)
    monkeypatch.setattr(disc, "scrape_reddit", reddit)
    job = await engine.run_discovery(TargetProfile(), ["google_maps", "reddit"])
    assert {r.source for r in job.raw_results} == {"google_maps", "reddit"}, job.raw_results


async def test_get_leads_returns_a_copy_not_the_live_list(engine):
    leads = engine.get_leads()
    leads.append({"injected": True})
    assert engine.get_leads() == [], "mutating the result must not corrupt the store"


# ── aiohttp missing ────────────────────────────────────────────────────────
async def test_missing_aiohttp_fails_the_job_with_a_actionable_message(engine, monkeypatch):
    monkeypatch.setattr(disc, "_AIOHTTP", False)
    job = await engine.run_discovery(TargetProfile(), ["reddit"])
    assert job.status == "failed"
    assert "aiohttp" in job.error
    assert "pip install aiohttp" in job.error, job.error
    assert job.skipped == [], "a hard dependency failure is an error, not a skip"


# ── bs4 gating ─────────────────────────────────────────────────────────────
async def test_bs4_dependent_sources_are_skipped_without_bs4(engine, monkeypatch):
    monkeypatch.setattr(disc, "_BS4", False)
    job = await engine.run_discovery(TargetProfile(), ["google_maps", "craigslist"])
    assert job.status == "completed"
    assert "google_maps:bs4_missing" in job.skipped, job.skipped
    assert "craigslist:bs4_missing" in job.skipped, job.skipped


async def test_bs4_dependent_sources_still_run_with_bs4(engine, monkeypatch):
    async def maps(queries):
        return [_src("google_maps")]

    async def cl(queries, cities=None):
        return [_src("craigslist")]

    monkeypatch.setattr(disc, "scrape_google_maps", maps)
    monkeypatch.setattr(disc, "scrape_craigslist", cl)
    job = await engine.run_discovery(TargetProfile(), ["google_maps", "craigslist"])
    assert job.status == "completed"
    assert job.raw_results, "both sources must have produced something"


# ── the "url" source is in FREE_SOURCES but has no switch branch ───────────
async def test_url_source_is_reported_as_unknown(engine):
    """FREE_SOURCES advertises 'url' but the dispatch dict has no 'url' entry,
    so it lands on the unknown_source path. Pinned so a future 'url' branch
    fails this test loudly."""
    job = await engine.run_discovery(TargetProfile(), ["url"])
    assert "url:unknown_source" in job.skipped, job.skipped


# ── extraction wiring ──────────────────────────────────────────────────────
async def test_extracted_leads_land_in_the_job_and_the_lead_store(engine, monkeypatch):
    async def maps(queries):
        return [_src("google_maps")]

    async def llm(prompt):
        return '[{"name":"Jane","company":"Acme","intent_score":0.7}]'

    monkeypatch.setattr(disc, "scrape_google_maps", maps)
    engine.set_llm(llm)
    job = await engine.run_discovery(TargetProfile(), ["google_maps"])
    assert job.leads and job.leads[0]["name"] == "Jane", job.leads
    assert job.leads[0]["source_type"] == "google_maps"
    assert engine.get_leads() == job.leads


async def test_constructor_accepts_an_llm_func(monkeypatch):
    async def maps(queries):
        return [_src("google_maps")]

    async def llm(prompt):
        return '[{"name":"FromCtor"}]'

    monkeypatch.setattr(disc, "scrape_google_maps", maps)
    job = await DiscoveryEngine(llm_func=llm).run_discovery(
        TargetProfile(), ["google_maps"])
    assert job.leads[0]["name"] == "FromCtor"


async def test_no_llm_and_no_sources_yields_a_clean_empty_job(engine):
    job = await engine.run_discovery(TargetProfile(), ["not_a_source"])
    assert job.leads == []
    assert job.status == "completed"
    assert not any("no_llm" in s for s in job.skipped), (
        "with no raw sources there is nothing to extract; no_llm must not be claimed")


async def test_llm_is_not_called_when_no_source_returned_anything(engine):
    async def llm(prompt):
        raise AssertionError("the LLM must not be called with zero raw sources")

    engine.set_llm(llm)
    job = await engine.run_discovery(TargetProfile(), ["not_a_source"])
    assert job.leads == []


async def test_a_source_returning_leads_with_no_llm_keeps_the_raw_records(engine, monkeypatch):
    async def maps(queries):
        return [_src("google_maps")]

    monkeypatch.setattr(disc, "scrape_google_maps", maps)
    job = await engine.run_discovery(TargetProfile(), ["google_maps"])
    assert len(job.raw_results) == 1, "raw text must be kept, not discarded"
    assert job.leads == [], "no LLM means no invented leads"
    assert "extraction:no_llm_configured" in job.skipped


# ── reddit blocked reporting through the orchestrator ──────────────────────
async def test_reddit_block_is_surfaced_in_the_job(engine, monkeypatch):
    async def blocked(queries, subreddits=None):
        disc.last_reddit_error = "HTTP 403 Blocked"
        return []

    monkeypatch.setattr(disc, "scrape_reddit", blocked)
    job = await engine.run_discovery(TargetProfile(), ["reddit"])
    assert any(s.startswith("reddit:blocked") for s in job.skipped), job.skipped
    assert job.status == "completed", "a block is a degradation, not a crash"


async def test_a_healthy_reddit_run_does_not_carry_a_stale_block(engine, monkeypatch):
    async def ok(queries, subreddits=None):
        disc.last_reddit_error = ""
        return [_src("reddit")]

    monkeypatch.setattr(disc, "scrape_reddit", ok)
    job = await engine.run_discovery(TargetProfile(), ["reddit"])
    assert not any("reddit:blocked" in s for s in job.skipped), job.skipped


# ── email verification ─────────────────────────────────────────────────────
async def test_verify_and_enrich_marks_a_lead_verified():
    e = DiscoveryEngine()
    leads = [{"email": "owner@gmail.com"}]
    out = await e.verify_and_enrich(leads)
    assert out[0]["email_verified"] is True
    assert out[0]["deliverability_score"] == 0.95


async def test_verify_and_enrich_marks_a_bad_domain_unverified():
    e = DiscoveryEngine()
    out = await e.verify_and_enrich([{"email": "nobody@nonexistent.invalid"}])
    assert out[0]["email_verified"] is False
    assert out[0]["deliverability_score"] == 0.1


async def test_verify_and_enrich_skips_leads_with_no_email():
    e = DiscoveryEngine()
    out = await e.verify_and_enrich([{"name": "No email"}])
    assert "email_verified" not in out[0]
    assert "deliverability_score" not in out[0]


async def test_verify_and_enrich_mutates_in_place_and_returns_the_same_list():
    e = DiscoveryEngine()
    leads = [{"email": "owner@gmail.com"}]
    assert await e.verify_and_enrich(leads) is leads


@pytest.mark.parametrize("bad", ["", "   ", "no-at-sign", "@nolocal.test", "a@b"])
async def test_malformed_emails_score_zero(bad):
    r = await verify_lead_email(bad)
    assert r["valid_syntax"] is False, bad
    assert r["deliverability_score"] == 0.0, bad
    assert r["domain_has_mx"] is False


async def test_email_is_lowercased_before_verification():
    r = await verify_lead_email("  Owner@Gmail.com  ")
    assert r["email"] == "owner@gmail.com", r


async def test_resolvable_domain_scores_high_and_unresolvable_low():
    good = await verify_lead_email("owner@gmail.com")
    bad = await verify_lead_email("owner@definitely-not-a-real-domain-xyz.invalid")
    assert good["domain_has_mx"] is True and good["deliverability_score"] == 0.95
    assert bad["domain_has_mx"] is False and bad["deliverability_score"] == 0.1


# ── webhook ingest ─────────────────────────────────────────────────────────
async def test_ingest_builds_a_name_from_first_and_last(engine):
    out = await engine.ingest_webhook_leads([{"first_name": "Jane", "last_name": "Doe"}])
    assert out[0]["name"] == "Jane Doe", out


async def test_ingest_defaults_the_intent_score(engine):
    out = await engine.ingest_webhook_leads([{"email": "a@b.test"}])
    assert out[0]["intent_score"] == 0.8


async def test_ingest_coerces_a_string_intent_score_to_float(engine):
    out = await engine.ingest_webhook_leads(
        [{"email": "a@b.test", "intent_score": "0.55"}])
    assert out[0]["intent_score"] == 0.55
    assert isinstance(out[0]["intent_score"], float)


async def test_ingest_prefers_an_explicit_name(engine):
    out = await engine.ingest_webhook_leads(
        [{"name": "Chosen", "first_name": "Other", "last_name": "Name"}])
    assert out[0]["name"] == "Chosen"


async def test_ingest_falls_back_to_linkedin_url_for_source_url(engine):
    out = await engine.ingest_webhook_leads(
        [{"email": "a@b.test", "linkedin_url": "https://li.test/in/x"}])
    assert out[0]["source_url"] == "https://li.test/in/x"


async def test_ingest_of_an_empty_list_is_empty(engine):
    assert await engine.ingest_webhook_leads([]) == []


async def test_ingested_leads_are_verified_and_stored(engine):
    out = await engine.ingest_webhook_leads([{"Email": "owner@gmail.com"}])
    assert out[0]["email_verified"] is True
    assert engine.get_leads()[0]["email"] == "owner@gmail.com"


# ── ScrapeJob dataclass ────────────────────────────────────────────────────
def test_scrape_job_defaults():
    j = ScrapeJob(id="j", profile=TargetProfile())
    assert j.status == "pending"
    assert j.created_at == 0.0 and j.completed_at == 0.0
    assert j.sources_used == [] and j.raw_results == [] and j.leads == []
    assert j.skipped == [] and j.api_keys_used == {}
    assert j.crm_pushed == 0 and j.error == ""


def test_scrape_job_mutable_defaults_are_not_shared():
    a = ScrapeJob(id="a", profile=TargetProfile())
    b = ScrapeJob(id="b", profile=TargetProfile())
    a.skipped.append("x")
    a.raw_results.append(_src())
    assert b.skipped == [] and b.raw_results == []


def test_target_profile_defaults():
    p = TargetProfile()
    assert p.customer_description == ""
    assert p.keywords == [] and p.locations == []
    assert p.industry == "" and p.target_count == 25
