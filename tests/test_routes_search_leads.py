"""Route tests: /api/settings, /api/routing/*, /api/search*, /api/leads*,
/api/export/*, /api/stats, /api/history.

Complements tests/test_main_api_surface.py (which owns the TokenBucket, the bare
verify_api_key() function, /health and the openapi schema). Nothing here
repeats those; every test drives a real HTTP route and asserts on the body.
"""
from __future__ import annotations

import pytest

import main
from tests.routes_fixtures import *  # noqa: F401,F403 -- pytest fixtures


# ── /api/settings ────────────────────────────────────────────────────────
def test_settings_reports_both_key_flags(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {"exa_key_configured": False, "perplexity_key_configured": False}


def test_settings_requires_auth(anon):
    assert anon.get("/api/settings").status_code == 401


def test_settings_key_rejects_blank_key(client):
    r = client.post("/api/settings/key", json={"key": "   "})
    assert r.status_code == 400
    assert r.json()["error"] == "API key is required"


def test_settings_key_rejects_unknown_service(client):
    r = client.post("/api/settings/key", json={"key": "sk-x", "service": "myspace"})
    assert r.status_code == 400
    assert "myspace" in r.json()["error"]


def test_settings_key_stores_exa_and_flips_engine_flag(client, vault_sandbox):
    """The route must both write the vault AND rewire the live engine."""
    assert main.engine.has_exa_key is False
    r = client.post("/api/settings/key", json={"key": "exa-fake-key", "service": "exa"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "exa API key configured"}
    assert ("exa", "user") in vault_sandbox
    assert main.engine.has_exa_key is True, "engine was not reconfigured"
    assert main.engine._exa.api_key == "exa-fake-key"

    # And the flag is now visible through GET /api/settings.
    assert client.get("/api/settings").json()["exa_key_configured"] is True


def test_settings_key_stores_perplexity(client, vault_sandbox):
    assert main.engine.has_perplexity_key is False
    r = client.post("/api/settings/key",
                    json={"key": "pplx-fake", "service": "Perplexity"})
    assert r.status_code == 200
    assert r.json()["message"] == "perplexity API key configured"
    assert main.engine.has_perplexity_key is True


def test_settings_key_service_defaults_to_exa(client, vault_sandbox):
    r = client.post("/api/settings/key", json={"key": "defaulted"})
    assert r.status_code == 200
    assert r.json()["message"] == "exa API key configured"
    assert vault_sandbox.get(("exa", "user")) == "defaulted"


# ── /api/routing/* ───────────────────────────────────────────────────────
ROUTING_STEPS = ["dedup", "score", "enrich", "llm_score", "crm_push"]
# enrich/llm_score/crm_push ship disabled, so they must NOT appear in enabled_steps.
ROUTING_ENABLED = ["dedup", "score"]


def test_routing_config_get_lists_steps(client):
    r = client.get("/api/routing/config")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["steps"]]
    assert names == ROUTING_STEPS, names
    assert all({"name", "label", "enabled", "config"} <= set(s)
               for s in r.json()["steps"])


def test_routing_steps_route_wraps_the_list(client):
    r = client.get("/api/routing/steps")
    assert r.status_code == 200
    assert [s["name"] for s in r.json()["steps"]] == ROUTING_STEPS


def test_routing_history_shape(client):
    r = client.get("/api/routing/history")
    assert r.status_code == 200
    assert isinstance(r.json()["history"], list)


def test_routing_history_limit_is_capped_at_100(client):
    """Query(20, le=100) -- 101 must be rejected by FastAPI, not silently passed."""
    assert client.get("/api/routing/history?limit=101").status_code == 422
    assert client.get("/api/routing/history?limit=100").status_code == 200


def test_routing_stats_shape(client):
    r = client.get("/api/routing/stats")
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"runs", "total_input", "total_output", "enabled_steps"}
    # The three optional steps ship disabled and must not be reported as enabled.
    assert d["enabled_steps"] == ROUTING_ENABLED
    assert "enrich" not in d["enabled_steps"]


def test_routing_config_put_with_step_updates_one_step(client):
    r = client.put("/api/routing/config",
                   json={"step": "dedup", "updates": {"enabled": False}})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["step"]["name"] == "dedup"
    assert r.json()["step"]["enabled"] is False
    # The sibling steps are untouched.
    assert client.get("/api/routing/stats").json()["enabled_steps"] == ["score"]


def test_routing_config_put_merges_step_config(client):
    """update_step() does step.config.update(updates["config"]), i.e. a MERGE --
    the step's shipped keys survive alongside the new one."""
    r = client.put("/api/routing/config",
                   json={"step": "score", "updates": {"config": {"weight": 0.5}}})
    assert r.status_code == 200
    cfg = r.json()["step"]["config"]
    assert cfg["weight"] == 0.5, "the new key must land"
    assert cfg["min_score"] == 30, "the step's existing config must be merged, not replaced"


def test_routing_config_put_unknown_step_is_404(client):
    r = client.put("/api/routing/config",
                   json={"step": "ghost", "updates": {"enabled": True}})
    assert r.status_code == 404
    assert "ghost" in r.json()["error"]


def test_routing_config_put_without_step_or_config_is_400(client):
    r = client.put("/api/routing/config", json={"unrelated": 1})
    assert r.status_code == 400
    assert r.json()["error"] == "Provide 'config' or 'step' + 'updates'"


def test_routing_config_put_with_full_config_replaces_everything(client):
    r = client.put("/api/routing/config", json={"config": {"steps": [
        {"name": "only", "label": "Only Step", "enabled": True, "config": {"k": "v"}},
    ]}})
    assert r.status_code == 200
    assert r.json()["config"]["steps"] == [
        {"name": "only", "label": "Only Step", "description": "", "enabled": True,
         "config": {"k": "v"}, "keys_required": []}
    ]
    assert [s["name"] for s in client.get("/api/routing/steps").json()["steps"]] == ["only"]


def test_routing_config_put_bare_step_object_is_400(client):
    """data.get('step') is truthy but there are no 'updates'; the whole body is
    the fallback. There is no 'config' key, so this must still 400, not crash."""
    r = client.put("/api/routing/config", json={"step": "dedup"})
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert r.json()["step"]["name"] == "dedup"


# ── /api/search ──────────────────────────────────────────────────────────
def test_search_rejects_a_malformed_body_with_422(client):
    """SearchConfig is a real dataclass, so a non-string query is a 422."""
    r = client.post("/api/search", json={"query": 5})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][:2] == ["body", "query"]


def test_search_surfaces_the_engine_error_as_400(client):
    """No Exa key in CI, so engine.search() returns ok=False; the route must
    translate that to a 4xx carrying the reason, not a 200 with empty leads."""
    r = client.post("/api/search", json={"query": "roofers", "industry": "roofing"})
    assert r.status_code == 400
    assert "Exa API key not configured" in r.json()["error"]


def test_search_surfaces_perplexity_error(client):
    r = client.post("/api/search",
                    json={"query": "roofers", "provider": "perplexity"})
    assert r.status_code == 400
    assert "Perplexity API key not configured" in r.json()["error"]


def test_search_returns_leads_when_the_provider_succeeds(client, monkeypatch):
    """Full happy path with the provider stubbed -- no network, no key."""
    from engine.search.base import SearchHit, SearchResult

    async def fake_search(query, *, num_results=10, search_type="auto"):
        return SearchResult(
            query=query, provider="exa", total_results=2,
            hits=[
                SearchHit(title="Acme Roofing LLC", url="https://acme.example.com",
                          snippet="Roof repair and replacement in Austin TX"),
                SearchHit(title="Best Roofers Austin", url="https://best.example.com",
                          snippet="Licensed roofing contractor serving Austin TX"),
            ],
        )

    # set_exa_key() first: with no key the engine never even reaches the provider.
    main.engine.set_exa_key("exa-fake")
    monkeypatch.setattr(main.engine._exa, "search", fake_search)

    r = client.post("/api/search", json={"query": "roofers", "industry": "roofing",
                                         "location": "Austin", "min_score": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["count"] == 2, d
    assert d["total_hits"] == 2
    assert "roof" in d["query"].lower()
    assert {l["title"] for l in d["leads"]} == {"Acme Roofing LLC", "Best Roofers Austin"}
    # The engine persisted them, so GET /api/leads now sees the same rows.
    assert client.get("/api/leads").json()["total"] == 2
    # And the search is now in history.
    assert len(client.get("/api/history").json()["history"]) == 1


def test_search_honours_min_score(client, monkeypatch):
    """The request min_score gates the provider hits, but the 'score' routing step
    then applies its OWN floor (config min_score=30) to the routed set. So
    min_score=0 is a floor request, not an "override the pipeline" request --
    document that contract rather than asserting something the product doesn't do."""
    from engine.search.base import SearchHit, SearchResult

    async def fake_search(query, *, num_results=10, search_type="auto"):
        return SearchResult(query=query, provider="exa", hits=[
            SearchHit(title="Roofers", url="https://a.test", snippet="roofing"),
            SearchHit(title="Pizzeria", url="https://b.test", snippet="pizza"),
        ])

    main.engine.set_exa_key("exa-fake")
    monkeypatch.setattr(main.engine._exa, "search", fake_search)

    strict = client.post("/api/search", json={"query": "roofers", "min_score": 99})
    assert strict.status_code == 200
    assert strict.json()["count"] == 0, "min_score=99 must filter everything out"
    assert strict.json()["total_hits"] == 2, "the provider still returned 2 hits"

    loose = client.post("/api/search", json={"query": "roofers", "min_score": 0})
    assert loose.status_code == 200
    # 'Pizzeria' scores under the routing step's min_score=30 floor and is dropped;
    # the roofing hit survives.
    assert loose.json()["count"] == 1, loose.json()
    assert loose.json()["leads"][0]["title"] == "Roofers"


def test_search_surfaces_a_provider_error_string(client, monkeypatch):
    from engine.search.base import SearchResult

    async def failing(query, *, num_results=10, search_type="auto"):
        return SearchResult(query=query, provider="exa", hits=[], error="provider exploded")

    main.engine.set_exa_key("exa-fake")
    monkeypatch.setattr(main.engine._exa, "search", failing)

    r = client.post("/api/search", json={"query": "roofers", "min_score": 0})
    assert r.status_code == 400
    assert r.json()["error"] == "provider exploded"


# ── /api/search/natural ──────────────────────────────────────────────────
def test_search_natural_requires_a_query(client):
    r = client.post("/api/search/natural", json={"query": "   "})
    assert r.status_code == 400
    assert r.json()["error"] == "Search query is required"


def test_search_natural_requires_a_query_when_key_absent(client):
    assert client.post("/api/search/natural", json={}).status_code == 400


def test_search_natural_propagates_engine_error(client):
    r = client.post("/api/search/natural", json={"query": "plumbers in Dallas"})
    assert r.status_code == 400
    assert "Exa API key not configured" in r.json()["error"]


def test_search_natural_parses_and_searches(client, monkeypatch):
    """The natural query must be decomposed into industry/location before search."""
    seen = {}

    from engine.search.base import SearchHit, SearchResult

    async def fake_search(query, *, num_results=10, search_type="auto"):
        seen["query"] = query
        seen["num_results"] = num_results
        return SearchResult(query=query, provider="exa", hits=[
            SearchHit(title="Dallas Plumbers", url="https://p.example.com",
                      snippet="plumbing services in Dallas TX"),
        ])

    main.engine.set_exa_key("exa-fake")
    monkeypatch.setattr(main.engine._exa, "search", fake_search)

    r = client.post("/api/search/natural",
                    json={"query": "plumbers in Dallas TX", "num_results": 7,
                          "min_score": 1})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["count"] == 1
    assert seen["num_results"] == 7, "num_results was not forwarded"
    assert "dallas" in seen["query"].lower()


# ── /api/leads ───────────────────────────────────────────────────────────
def test_leads_list_is_empty_and_paginated_by_default(client):
    r = client.get("/api/leads")
    assert r.status_code == 200
    assert r.json() == {"leads": [], "total": 0, "returned": 0,
                        "offset": 0, "limit": 100}


def test_leads_list_pagination_slices_and_reports_totals(client):
    for i in range(5):
        seed_lead(f"L{i}", score=50.0 + i)
    r = client.get("/api/leads?limit=2&offset=1")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 5, "total is the whole store, not the page"
    assert d["returned"] == 2
    assert d["offset"] == 1
    assert d["limit"] == 2
    assert len(d["leads"]) == 2


def test_leads_list_sorts_by_score_desc(client):
    seed_lead("LOW", score=10.0)
    seed_lead("HIGH", score=95.0)
    seed_lead("MID", score=50.0)
    scores = [l["score"] for l in client.get("/api/leads").json()["leads"]]
    assert scores == [95.0, 50.0, 10.0], scores


def test_leads_list_min_score_filters(client):
    seed_lead("LOW", score=10.0)
    seed_lead("HIGH", score=95.0)
    d = client.get("/api/leads?min_score=90").json()
    assert d["total"] == 2, "total counts the store, not the filtered set"
    assert [l["id"] for l in d["leads"]] == ["HIGH"]


def test_leads_list_rejects_negative_offset(client):
    assert client.get("/api/leads?offset=-1").status_code == 422


def test_leads_list_rejects_limit_above_500(client):
    assert client.get("/api/leads?limit=501").status_code == 422
    assert client.get("/api/leads?limit=500").status_code == 200


def test_leads_list_requires_auth(anon):
    assert anon.get("/api/leads").status_code == 401


def test_get_lead_returns_the_stored_record(client):
    seed_lead("L1", title="Acme Roofing", email="a@acme.test")
    r = client.get("/api/leads/L1")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "L1"
    assert d["title"] == "Acme Roofing"
    assert d["email"] == "a@acme.test"
    assert d["industry"] == "roofing"
    assert "score_breakdown" in d


def test_get_missing_lead_is_404(client):
    r = client.get("/api/leads/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"] == "Lead not found"


def test_patch_lead_updates_the_allowed_field(client):
    seed_lead("L1", title="Acme Roofing")
    r = client.patch("/api/leads/L1", json={"notes": "called once", "status": "contacted"})
    assert r.status_code == 200
    assert r.json()["notes"] == "called once"
    assert r.json()["status"] == "contacted"
    # Persisted, not just echoed.
    assert client.get("/api/leads/L1").json()["notes"] == "called once"


def test_patch_lead_ignores_a_field_outside_the_allowlist(client):
    """`id` and `score` are not settable; a silent no-op is correct here, but the
    stored value must genuinely not change."""
    seed_lead("L1", title="Acme Roofing", score=70.0)
    r = client.patch("/api/leads/L1", json={"id": "HACKED", "score": 999.0,
                                            "found_at": "1999-01-01"})
    assert r.status_code == 200
    assert r.json()["id"] == "L1", "id must not be patchable"
    assert r.json()["score"] == 70.0, "score must not be patchable"


def test_patch_missing_lead_is_404(client):
    r = client.patch("/api/leads/nope", json={"notes": "x"})
    assert r.status_code == 404
    assert r.json()["error"] == "Lead not found"


def test_delete_lead_removes_it(client):
    seed_lead("L1")
    assert client.get("/api/leads/L1").status_code == 200
    r = client.delete("/api/leads/L1")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert client.get("/api/leads/L1").status_code == 404
    assert client.get("/api/leads").json()["total"] == 0


def test_delete_missing_lead_is_404(client):
    r = client.delete("/api/leads/ghost")
    assert r.status_code == 404
    assert r.json()["error"] == "Lead not found"


def test_delete_is_not_idempotent_silently(client):
    """Deleting twice must 404 the second time, not 200 an 'ok'."""
    seed_lead("L1")
    assert client.delete("/api/leads/L1").status_code == 200
    assert client.delete("/api/leads/L1").status_code == 404


def test_clear_leads_empties_the_store(client):
    seed_lead("L1")
    seed_lead("L2")
    r = client.delete("/api/leads")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "message": "All leads cleared"}
    assert client.get("/api/leads").json()["total"] == 0


def test_clear_leads_requires_auth(anon):
    assert anon.delete("/api/leads").status_code == 401


# ── /api/export/* ────────────────────────────────────────────────────────
def test_export_csv_is_a_csv_attachment(client):
    seed_lead("L1", title="Acme Roofing", email="a@acme.test")
    r = client.get("/api/export/csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == "attachment; filename=leads.csv"
    body = r.text
    assert "Acme Roofing" in body
    assert "a@acme.test" in body
    assert body.count("\n") >= 2, body


def test_export_csv_min_score_filters_rows(client):
    seed_lead("LOW", title="Cheap", score=5.0)
    seed_lead("HIGH", title="Premium", score=95.0)
    r = client.get("/api/export/csv?min_score=90")
    assert r.status_code == 200
    assert "Premium" in r.text
    assert "Cheap" not in r.text


def test_export_json_is_a_json_attachment(client):
    seed_lead("L1", title="Acme Roofing")
    r = client.get("/api/export/json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"] == "attachment; filename=leads.json"
    import json as _json
    body = _json.loads(r.text)
    assert len(body) == 1
    assert body[0]["id"] == "L1"
    assert body[0]["title"] == "Acme Roofing"


def test_export_json_min_score_filters(client):
    seed_lead("LOW", score=5.0)
    seed_lead("HIGH", score=95.0)
    import json as _json
    body = _json.loads(client.get("/api/export/json?min_score=90").text)
    assert [b["id"] for b in body] == ["HIGH"]


def test_export_requires_auth(anon):
    assert anon.get("/api/export/csv").status_code == 401
    assert anon.get("/api/export/json").status_code == 401


# ── /api/stats, /api/history ─────────────────────────────────────────────
def test_stats_aggregates_every_subsystem(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    d = r.json()
    # The keys /api/stats adds on top of engine.get_stats().
    for key in ("scheduler", "capture", "landing_pages", "nurture",
                "crm_push", "business_config", "ad_platforms"):
        assert key in d, f"{key} missing from /api/stats"
    assert d["landing_pages"] == 0
    assert "google_ads" in d["ad_platforms"]
    assert "total_sequences" in d["nurture"]
    assert "business_name" in d["business_config"]
    assert "total_pushes" in d["crm_push"]
    assert "total_schedules" in d["scheduler"]
    assert "total" in d["capture"]


def test_stats_on_an_empty_store_uses_the_short_shape(client):
    """engine.get_stats() returns a *different* key set when the store is empty
    (no max_score/by_industry) than when it is not. Both must still 200."""
    d = client.get("/api/stats").json()
    assert d["total"] == 0
    assert d["avg_score"] == 0
    assert d["by_industry"] == {}
    assert d["searches_run"] == 0
    assert "max_score" not in d, "the empty-store contract has no max_score key"


def test_stats_reflects_the_lead_store(client):
    seed_lead("L1", score=80.0)
    seed_lead("L2", score=40.0, industry="plumbing")
    d = client.get("/api/stats").json()
    assert d["total"] == 2
    assert d["max_score"] == 80.0
    assert d["avg_score"] == 60.0
    assert d["by_industry"] == {"roofing": 1, "plumbing": 1}


def test_history_is_empty_then_records_searches(client, monkeypatch):
    assert client.get("/api/history").json() == {"history": []}
    from engine.search.base import SearchHit, SearchResult

    async def fake_search(query, *, num_results=10, search_type="auto"):
        return SearchResult(query=query, provider="exa", hits=[
            SearchHit(title="Roofers", url="https://a.test", snippet="roofing"),
        ])

    main.engine.set_exa_key("exa-fake")
    monkeypatch.setattr(main.engine._exa, "search", fake_search)
    client.post("/api/search", json={"query": "roofers", "min_score": 0})

    hist = client.get("/api/history").json()["history"]
    assert len(hist) == 1
    assert hist[0]["results_count"] == 1
    assert hist[0]["config"]["query"] == "roofers"
    assert "elapsed_sec" in hist[0]


def test_history_limit_is_enforced(client):
    assert client.get("/api/history?limit=101").status_code == 422
    assert client.get("/api/history?limit=1").json()["history"] == []


# ── /api/search/multi ────────────────────────────────────────────────────
def test_search_multi_requires_a_query(client):
    r = client.post("/api/search/multi", json={"query": "  "})
    assert r.status_code == 400
    assert r.json()["error"] == "Search query is required"


def test_search_multi_merges_two_providers_and_dedups(client, monkeypatch):
    from engine.search.base import SearchHit, SearchResult

    # NOTE: merger dedups on URL *domain*, so every hit below needs its own domain.
    # Every snippet is roofing-flavoured on purpose: the 'score' routing step drops
    # anything under its min_score=30 floor *before* merge_leads ever sees it, so a
    # weak snippet would vanish early and the dedup assertion would be vacuous.
    exa_hits = [
        SearchHit(title="Acme Roofing", url="https://acme-roofing.test",
                  snippet="roofing contractor offering roof repair in Austin TX"),
        SearchHit(title="Best Roofers", url="https://best-roofers.test",
                  snippet="licensed roofing contractor serving Austin TX"),
    ]
    pplx_hits = [
        # Same URL as the first Exa hit -> must be deduped, not double counted.
        SearchHit(title="Acme Roofing", url="https://acme-roofing.test",
                  snippet="roofing contractor offering roof repair in Austin TX"),
        SearchHit(title="Only On Pplx", url="https://pplx-only.test",
                  snippet="roofing services and roof repair in Austin TX"),
    ]

    async def exa_search(query, *, num_results=10, search_type="auto"):
        return SearchResult(query=query, provider="exa", hits=exa_hits)

    async def pplx_search(query, *, num_results=10, search_type="auto"):
        return SearchResult(query=query, provider="perplexity", hits=pplx_hits)

    main.engine.set_exa_key("exa-fake")
    main.engine.set_perplexity_key("pplx-fake")
    monkeypatch.setattr(main.engine._exa, "search", exa_search)
    monkeypatch.setattr(main.engine._perplexity, "search", pplx_search)

    r = client.post("/api/search/multi",
                    json={"query": "roofers in Austin TX", "num_results": 10})
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d["stats"]["sources_used"]) == {"exa", "perplexity"}
    assert d["stats"]["dedup_removed"] == 1, d["stats"]
    assert d["stats"]["after_dedup"] == 3, d["stats"]
    assert len(d["leads"]) == 3
    # Every lead is stamped with the provider it came from.
    assert {l["source"] for l in d["leads"]} <= {"exa", "perplexity"}
    assert all(l["source"] for l in d["leads"])
    # The route persisted them into the engine store.
    assert client.get("/api/leads").json()["total"] == 3


def test_search_multi_records_per_provider_errors_and_keeps_going(client, monkeypatch):
    """One provider blowing up must not lose the other provider's results."""
    from engine.search.base import SearchHit, SearchResult

    async def exa_search(query, *, num_results=10, search_type="auto"):
        return SearchResult(query=query, provider="exa", hits=[
            SearchHit(title="Exa Only", url="https://exa-only.test",
                      snippet="roofing contractor in Austin TX"),
        ])

    async def pplx_search(query, *, num_results=10, search_type="auto"):
        raise RuntimeError("perplexity exploded")

    main.engine.set_exa_key("exa-fake")
    main.engine.set_perplexity_key("pplx-fake")
    monkeypatch.setattr(main.engine._exa, "search", exa_search)
    monkeypatch.setattr(main.engine._perplexity, "search", pplx_search)

    r = client.post("/api/search/multi", json={"query": "roofers in Austin TX"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["leads"]) == 1, "the surviving provider's lead must still come back"
    assert d["stats"]["errors"] == ["perplexity: perplexity exploded"], d["stats"]
    # Only the provider that actually returned leads is credited in sources_used.
    assert d["stats"]["sources_used"] == ["exa"]


def test_search_multi_survives_total_provider_failure(client, monkeypatch):
    """Everything failing still returns 200 with an empty, honest result -- the
    errors list is the signal. It must NOT be reported as a success with leads."""
    from engine.search.base import SearchResult

    async def boom(query, *, num_results=10, search_type="auto"):
        raise RuntimeError("nope")

    main.engine.set_exa_key("exa-fake")
    main.engine.set_perplexity_key("pplx-fake")
    monkeypatch.setattr(main.engine._exa, "search", boom)
    monkeypatch.setattr(main.engine._perplexity, "search", boom)

    r = client.post("/api/search/multi", json={"query": "roofers in Austin TX"})
    assert r.status_code == 200
    d = r.json()
    assert d["leads"] == []
    assert len(d["stats"]["errors"]) == 2
    assert client.get("/api/leads").json()["total"] == 0, "nothing must be stored"
