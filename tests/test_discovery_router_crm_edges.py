"""Coverage-closing tests for the last uncovered branches in discovery.py,
router.py and crm_push.py (audit 2026-09-27).

Each test here targets a specific line/branch reported by
`pytest --cov=engine.discovery --cov=engine.router --cov=engine.crm_push
--cov-report=term-missing` and is named for the behaviour it locks down.
"""
import asyncio

import pytest

import engine.discovery as disc
from engine.discovery import (
    DiscoveryEngine,
    LeadSource,
    TargetProfile,
    extract_leads_with_ai,
    scrape_craigslist,
    scrape_reddit,
    scrape_tavily,
)
from engine.router import SmartRouter
from tests.test_discovery_scrapers import _Recorder, _Resp


@pytest.fixture
def fake_aiohttp(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(disc.aiohttp, "ClientSession", rec.handler())
    real_sleep = asyncio.sleep

    async def _instant(_delay, *a, **k):
        return await real_sleep(0, *a, **k)

    monkeypatch.setattr(asyncio, "sleep", _instant)
    return rec


class _Exploding:
    """A session whose get/post raises before any context manager exists."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    def get(self, *a, **k):
        raise OSError("read timeout")

    def post(self, *a, **k):
        raise OSError("read timeout")


# ── discovery: per-source transport failures must not abort the run ────────
async def test_reddit_swallows_a_per_request_transport_error(fake_aiohttp, monkeypatch):
    """The per-query `except` in scrape_reddit; a timeout on one sub/query must
    not stop the loop or propagate."""
    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Exploding)
    disc.last_reddit_error = ""
    assert await scrape_reddit(["a", "b"], subreddits=["DIY", "Roofing"]) == []
    assert disc.last_reddit_error == "", "a transport failure is not a 403 block"


async def test_craigslist_swallows_a_per_request_transport_error(fake_aiohttp, monkeypatch):
    """`except Exception: pass` — craigslist failures are non-fatal by design."""
    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Exploding)
    assert await scrape_craigslist(["x", "y"], cities=["eugene", "portland"]) == []


async def test_tavily_swallows_a_per_request_transport_error(fake_aiohttp, monkeypatch):
    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Exploding)
    assert await scrape_tavily(["a", "b"], api_key="tv-key") == []


async def test_reddit_survives_a_non_json_body(fake_aiohttp):
    """A 200 that isn't JSON raises inside resp.json() and is caught per-query."""
    fake_aiohttp.routes["/search.json"] = _Resp(200, "<html>not json</html>")
    disc.last_reddit_error = ""
    assert await scrape_reddit(["a"], subreddits=["DIY"]) == []


# ── discovery: run_discovery reporting when no queries were generated ───────
async def test_source_with_no_generated_queries_is_reported(monkeypatch):
    """If generate_search_queries ever returns {} for a source, the run must say
    so rather than report an empty result as 'no leads found'."""
    monkeypatch.setattr(disc, "generate_search_queries", lambda p: {})
    engine = DiscoveryEngine()
    job = await engine.run_discovery(TargetProfile(), ["google_maps", "craigslist"])
    assert "google_maps:no_queries_generated" in job.skipped, job.skipped
    assert "craigslist:no_queries_generated" in job.skipped, job.skipped


async def test_no_queries_generated_is_not_reported_for_a_producing_source(monkeypatch):
    async def maps(queries):
        return [LeadSource(source="google_maps", text="x" * 200)]

    monkeypatch.setattr(disc, "generate_search_queries", lambda p: {})
    monkeypatch.setattr(disc, "scrape_google_maps", maps)
    job = await DiscoveryEngine().run_discovery(TargetProfile(), ["google_maps"])
    assert not any("no_queries_generated" in s for s in job.skipped), job.skipped


# ── discovery: extract_leads_with_ai JSON shapes ───────────────────────────
async def test_extract_skips_sources_with_empty_text():
    srcs = [LeadSource(source="web", text=""), LeadSource(source="web", text="y" * 200)]
    seen = []

    async def llm(prompt):
        seen.append(prompt)
        return "[]"

    assert await extract_leads_with_ai(srcs, TargetProfile(), llm) == []
    assert len(seen) == 1, "the empty-text source must never reach the LLM"


async def test_extract_ignores_a_json_object_that_is_not_a_list():
    srcs = [LeadSource(source="web", text="z" * 200)]

    async def llm(prompt):
        return '{"name": "not a list"}'

    assert await extract_leads_with_ai(srcs, TargetProfile(), llm) == []


async def test_extract_ignores_a_fenced_block_with_no_leading_newline():
    srcs = [LeadSource(source="web", text="z" * 200)]

    async def llm(prompt):
        return "```\n[{\"name\":\"A\"}]\n```"

    leads = await extract_leads_with_ai(srcs, TargetProfile(), llm)
    assert len(leads) == 1, leads


async def test_extract_defaults_every_missing_field():
    srcs = [LeadSource(source="web", text="z" * 200, url="https://w.test")]

    async def llm(prompt):
        return "[{}]"

    extracted = (await extract_leads_with_ai(srcs, TargetProfile(), llm))[0]
    assert extracted["name"] == "" and extracted["email"] == ""
    assert extracted["pain_points"] == [] and extracted["need_type"] == ""
    assert extracted["intent_score"] == 0.0
    assert extracted["source_url"] == "https://w.test"
    assert extracted["raw_snippet"].startswith("z")


async def test_extract_passes_the_profile_description_and_truncates_text():
    srcs = [LeadSource(source="craigslist", text="q" * 9000)]
    captured = {}

    async def llm(prompt):
        captured["prompt"] = prompt
        return "[]"

    profile = TargetProfile(customer_description="roofing contractor in Austin")
    await extract_leads_with_ai(srcs, profile, llm)
    assert "roofing contractor in Austin" in captured["prompt"]
    assert "craigslist" in captured["prompt"]
    assert len(captured["prompt"]) < 9000, "text must be truncated to 6000 chars"


async def test_extract_defaults_a_blank_profile_description():
    srcs = [LeadSource(source="web", text="q" * 200)]
    captured = {}

    async def llm(prompt):
        captured["prompt"] = prompt
        return "[]"

    await extract_leads_with_ai(srcs, TargetProfile(), llm)
    assert "general contractor services" in captured["prompt"]


async def test_extract_keeps_extracting_after_one_source_fails():
    """A garbage response from source 1 must not lose source 2's leads."""
    srcs = [LeadSource(source="a", text="a" * 200), LeadSource(source="b", text="b" * 200)]
    calls = {"n": 0}

    async def llm(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return '[{"name":"Survivor"}]'

    leads = await extract_leads_with_ai(srcs, TargetProfile(), llm)
    assert [ld["name"] for ld in leads] == ["Survivor"], leads


async def test_extract_returns_nothing_for_an_empty_source_list():
    assert await extract_leads_with_ai([], TargetProfile(), None) == []


async def test_extract_ignores_a_non_string_llm_result():
    """The LLM contract is a JSON string; a dict/none response is not parsed and
    must not raise."""
    srcs = [LeadSource(source="web", text="z" * 200)]

    async def llm(prompt):
        return {"name": "already parsed"}

    assert await extract_leads_with_ai(srcs, TargetProfile(), llm) == []


async def test_extract_handles_an_unterminated_code_fence():
    """Opened with ``` but never closed: the inner split yields the JSON with
    no trailing fence to rsplit, which must still parse."""
    srcs = [LeadSource(source="web", text="z" * 200)]

    async def llm(prompt):
        return '```json\n[{"name":"Unterminated"}]'

    leads = await extract_leads_with_ai(srcs, TargetProfile(), llm)
    assert [ld["name"] for ld in leads] == ["Unterminated"], leads


async def test_github_non_200_user_search_still_collects_repositories(fake_aiohttp):
    """A throttled user search must not stop the repository half of the query."""
    fake_aiohttp.routes["/search/users"] = _Resp(403, "rate limited")
    fake_aiohttp.routes["/search/repositories"] = _Resp(200, "", {
        "items": [{"full_name": "o/r", "description": "d", "owner": {"login": "o"},
                   "topics": [], "stargazers_count": 0, "html_url": "https://gh.test/o/r"}]})
    out = await disc.scrape_github(["roofing"])
    assert len(out) == 1, out
    assert out[0].metadata["repo"] == "o/r"


# ── router: enrich and llm_score reached through route_leads ───────────────
def _lead(url, score):
    return {"url": url, "title": "", "score": score}


async def test_route_leads_runs_the_enrich_step_when_enabled(monkeypatch):
    r = SmartRouter({"steps": [{"name": "enrich", "label": "E", "description": "",
                                "enabled": True, "config": {"batch_size": 25}}]})
    r.set_env({})
    calls = []

    async def enrich(lead):
        calls.append(lead["url"])
        return {"email": "a@b.test"}

    r.register_enrichment_fn(enrich)
    out = await r.route_leads([_lead("https://a.test", 50)])
    assert calls == ["https://a.test"], "enrich must be dispatched from the pipeline"
    assert out["leads"][0]["email"] == "a@b.test"
    assert out["pipeline"]["steps_run"] == ["enrich"]


async def test_route_leads_runs_the_llm_score_step_when_enabled(monkeypatch):
    r = SmartRouter({"steps": [{"name": "llm_score", "label": "L", "description": "",
                                "enabled": True, "keys_required": ["ANTHROPIC_API_KEY"],
                                "config": {"provider": "anthropic", "model": "m",
                                           "max_leads": 5, "min_rule_score": 50}}]})
    r.set_env({"ANTHROPIC_API_KEY": "sk-x"})

    async def score(batch, provider=None, model=None):
        return [{"score": 90, "rationale": "hot"} for _ in batch]

    r.register_llm_score_fn(score)
    out = await r.route_leads([_lead("https://a.test", 80)])
    assert out["leads"][0]["llm_score"] == 90
    assert out["leads"][0]["score"] == 84.0, "0.6*80 + 0.4*90"
    assert out["pipeline"]["steps_run"] == ["llm_score"]


async def test_route_leads_preserves_declared_step_order_regardless_of_config_order():
    """Config lists steps in a different order; the pipeline must still run them
    dedup -> score -> enrich -> llm_score -> crm_push."""
    r = SmartRouter({"steps": [
        {"name": "crm_push", "label": "c", "description": "", "enabled": False, "config": {}},
        {"name": "enrich", "label": "e", "description": "", "enabled": True, "config": {}},
        {"name": "score", "label": "s", "description": "", "enabled": True, "config": {"min_score": 0}},
        {"name": "dedup", "label": "d", "description": "", "enabled": True, "config": {}},
    ]})
    r.set_env({})
    r.register_enrichment_fn(lambda lead: _noop())
    out = await r.route_leads([_lead("https://a.test", 50), _lead("https://a.test", 50)])
    assert out["pipeline"]["steps_run"] == ["dedup", "score", "enrich"]


async def _noop():
    return {}


async def test_route_leads_ignores_a_config_step_outside_the_fixed_step_order():
    """route_leads iterates a hardcoded step_order, NOT the configured steps, so
    a config-only step like 'mystery_step' is never dispatched and never even
    appears in steps_skipped. The five canonical names are what run."""
    r = SmartRouter({"steps": [
        {"name": "mystery_step", "label": "m", "description": "", "enabled": True, "config": {}},
        {"name": "dedup", "label": "d", "description": "", "enabled": True, "config": {}},
    ]})
    r.set_env({})
    out = await r.route_leads([_lead("https://a.test", 50)])
    assert "mystery_step" not in out["pipeline"]["steps_skipped"], (
        "only the five fixed step names are iterated")
    assert out["pipeline"]["steps_run"] == ["dedup"]
    assert out["pipeline"]["steps_skipped"] == ["score", "enrich", "llm_score", "crm_push"]


async def test_route_leads_falls_through_the_elif_chain_for_every_step():
    """route_leads is one if/elif over step_name; this walks all five branches."""
    r = SmartRouter({"steps": [
        {"name": n, "label": n, "description": "", "enabled": True,
         "keys_required": [], "config": c}
        for n, c in [
            ("dedup", {}),
            ("score", {"min_score": 0}),
            ("enrich", {"batch_size": 25}),
            ("llm_score", {"provider": "anthropic", "model": "m", "max_leads": 5,
                           "min_rule_score": 0}),
            ("crm_push", {"provider": "hubspot", "min_score": 0, "max_per_batch": 25}),
        ]
    ]})
    r.set_env({"ANTHROPIC_API_KEY": "sk-x"})

    async def enrich(lead):
        return {"email": "a@b.test"}

    async def score(batch, provider=None, model=None):
        return [{"score": 80, "rationale": "ok"} for _ in batch]

    async def push(leads, config):
        pushed.append([ld["url"] for ld in leads])

    pushed = []
    r.register_enrichment_fn(enrich)
    r.register_llm_score_fn(score)
    r.register_crm_push_fn(push)
    out = await r.route_leads([_lead("https://a.test", 50)])
    assert out["pipeline"]["steps_run"] == [
        "dedup", "score", "enrich", "llm_score", "crm_push"], out["pipeline"]
    assert pushed == [["https://a.test"]], pushed
    assert out["leads"][0]["email"] == "a@b.test"
    assert out["leads"][0]["llm_score"] == 80


# ── crm_push: the real _get_key resolution order ──────────────────────────
def test_get_key_prefers_the_vault_over_the_environment(monkeypatch):
    from engine.crm_push import CrmPush
    from engine.key_vault import KeyVault

    monkeypatch.setattr(KeyVault, "get", classmethod(lambda cls, s: "vault-key"))
    monkeypatch.setenv("HUBSPOT_API_KEY", "env-key")
    assert CrmPush()._get_key("hubspot", "HUBSPOT_API_KEY") == "vault-key"


def test_get_key_falls_back_to_the_environment(monkeypatch):
    from engine.crm_push import CrmPush
    from engine.key_vault import KeyVault

    monkeypatch.setattr(KeyVault, "get", classmethod(lambda cls, s: None))
    monkeypatch.setenv("HUBSPOT_API_KEY", "env-key")
    assert CrmPush()._get_key("hubspot", "HUBSPOT_API_KEY") == "env-key"


def test_get_key_returns_none_when_neither_source_has_a_key(monkeypatch):
    from engine.crm_push import CrmPush
    from engine.key_vault import KeyVault

    monkeypatch.setattr(KeyVault, "get", classmethod(lambda cls, s: None))
    monkeypatch.delenv("HUBSPOT_API_KEY", raising=False)
    assert CrmPush()._get_key("hubspot", "HUBSPOT_API_KEY") is None


def test_get_key_treats_an_empty_env_var_as_absent(monkeypatch):
    from engine.crm_push import CrmPush
    from engine.key_vault import KeyVault

    monkeypatch.setattr(KeyVault, "get", classmethod(lambda cls, s: None))
    monkeypatch.setenv("HUBSPOT_API_KEY", "")
    assert CrmPush()._get_key("hubspot", "HUBSPOT_API_KEY") is None


async def test_gohighlevel_non_dict_body_yields_no_remote_id(monkeypatch):
    """GHL can answer ok=True with a list or string body. The isinstance guard
    must leave remote_id None rather than raising on .get()."""
    from engine.crm_push import CrmPush

    async def upsert(lead):
        return {"ok": True, "body": ["unexpected", "shape"]}

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await CrmPush().push_leads(
        [{"id": "L1", "title": "Jane Doe", "score": 90}], provider="gohighlevel")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] is None, out
