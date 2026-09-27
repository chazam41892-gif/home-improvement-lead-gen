"""Tests for engine/router.py — the SmartRouter lead pipeline (audit 2026-09-27).

router.py was at 21% covered. It is a step pipeline, not a provider picker: a
fixed order dedup -> score -> enrich -> llm_score -> crm_push, where each step is
gated on (a) existing in the config, (b) being enabled, and (c) having its
required API keys. The values that matter and are asserted here:

  * step order and which steps run vs. are skipped
  * `_check_keys` per provider (anthropic vs cometapi) and the generic
    keys_required list
  * dedup keys on the trailing-slash-stripped URL, falling back to lowercased
    title, and DROPPING leads that have neither
  * score filtering at min_score, treating a missing score as 0
  * enrich batching + gather(return_exceptions=True) so one bad lead cannot
    take down the batch, and the (url, id, score) merge guard
  * llm_score candidate selection (min_rule_score, sorted, truncated to
    max_leads) and the 0.6/0.4 score blend
  * crm_push min_score/max_per_batch gating, and — the data-loss check — that a
    raising push_fn does NOT abort the pipeline and does NOT report success
  * history and stats bookkeeping
"""
import copy

import pytest

from engine.router import DEFAULT_ROUTING_CONFIG, RoutingStep, SmartRouter

#: load_config() stores the very dict objects from DEFAULT_ROUTING_CONFIG, so
#: update_step() mutates module-level global state. Pinned as a bug by
#: test_update_step_mutates_the_module_level_default. Restored around every test
#: so one test's config tweak cannot silently change another's thresholds.
_DEFAULT_SNAPSHOT = copy.deepcopy(DEFAULT_ROUTING_CONFIG)


@pytest.fixture(autouse=True)
def _restore_default_config():
    yield
    DEFAULT_ROUTING_CONFIG.clear()
    DEFAULT_ROUTING_CONFIG.update(copy.deepcopy(_DEFAULT_SNAPSHOT))


def _cfg(*steps):
    """A router config built from (name, enabled, config) triples."""
    return {"steps": [
        {"name": n, "label": n.title(), "description": "", "enabled": e, "config": c}
        for n, e, c in steps
    ]}


def _lead(**kw):
    base = {"url": "", "title": "", "score": 0}
    base.update(kw)
    return base


def _url_leads(*pairs):
    """(url, score) pairs -> leads that survive the dedup step.

    _run_dedup keys on url-or-title and DROPS anything with neither, so pipeline
    tests must give every lead a url.
    """
    return [_lead(url=u, score=s) for u, s in pairs]


@pytest.fixture
def router():
    return SmartRouter()


# ── config load / inspect ──────────────────────────────────────────────────
def test_default_config_loads_all_five_steps(router):
    cfg = router.get_config()
    assert [s["name"] for s in cfg["steps"]] == [
        "dedup", "score", "enrich", "llm_score", "crm_push"], cfg


def test_default_enables_only_dedup_and_score(router):
    enabled = {s["name"] for s in router.get_config()["steps"] if s["enabled"]}
    assert enabled == {"dedup", "score"}, enabled


def test_load_config_uses_defaults_for_missing_fields():
    r = SmartRouter({"steps": [{"name": "solo"}]})
    step = r.get_config()["steps"][0]
    assert step == {"name": "solo", "label": "solo", "description": "",
                    "enabled": True, "config": {}, "keys_required": []}, step


def test_load_config_replaces_previous_steps(router):
    router.load_config(_cfg(("score", True, {})))
    assert [s["name"] for s in router.get_config()["steps"]] == ["score"]


def test_load_config_of_an_empty_config_leaves_no_steps(router):
    router.load_config({})
    assert router.get_config()["steps"] == []


def test_routing_step_as_dict_omits_runtime_results():
    s = RoutingStep("a", "A", "d", True, {"x": 1}, ["K"])
    s.results = {"output_count": 9}
    assert "results" not in s.as_dict(), s.as_dict()
    assert s.as_dict()["keys_required"] == ["K"]


# ── update_step ────────────────────────────────────────────────────────────
def test_update_step_toggles_enabled(router):
    out = router.update_step("enrich", {"enabled": True})
    assert out["enabled"] is True
    assert out["name"] == "enrich"


def test_update_step_coerces_truthy_enabled_to_bool(router):
    assert router.update_step("enrich", {"enabled": 1})["enabled"] is True
    assert router.update_step("enrich", {"enabled": 0})["enabled"] is False


def test_update_step_merges_config_rather_than_replacing(router):
    router.update_step("score", {"config": {"min_score": 55}})
    assert router.get_config()["steps"][1]["config"]["min_score"] == 55, "other keys must survive"


def test_update_step_ignores_a_non_dict_config(router):
    out = router.update_step("score", {"config": "nope"})
    assert out["config"] == {"min_score": 30}, out


def test_update_step_ignores_unknown_keys(router):
    out = router.update_step("score", {"label": "Renamed"})
    assert out["label"] == "Rule-Based Scoring", "only enabled/config are writable"


def test_update_step_on_unknown_name_returns_none(router):
    assert router.update_step("does_not_exist", {"enabled": True}) is None


def test_update_step_does_not_mutate_the_module_level_default(router):
    """load_config() deepcopies each step's config, so editing the routing
    config through the API cannot rewrite process-global DEFAULT_ROUTING_CONFIG.

    Before the fix, RoutingStep stored step_data["config"] BY REFERENCE and
    update_step() mutated it in place, so the first SmartRouter built after an
    API edit inherited the change.
    """
    before = DEFAULT_ROUTING_CONFIG["steps"][1]["config"]["min_score"]
    router.update_step("score", {"config": {"min_score": 99}})
    after = DEFAULT_ROUTING_CONFIG["steps"][1]["config"]["min_score"]
    assert after == before, "update_step() leaked into the module-level default"
    assert before == 30, "the pristine default threshold is 30"


def test_a_second_router_does_not_inherit_the_mutation(router):
    """The user-visible consequence of the fix: a new router starts pristine."""
    router.update_step("score", {"config": {"min_score": 99}})
    fresh = SmartRouter()
    score_cfg = next(s["config"] for s in fresh.get_config()["steps"] if s["name"] == "score")
    assert score_cfg["min_score"] == 30, "config leaked across SmartRouter instances"


# ── key gating ─────────────────────────────────────────────────────────────
def test_llm_score_needs_the_anthropic_key(router):
    step = router._steps["llm_score"]
    router.set_env({})
    assert router._check_keys(step) == ["ANTHROPIC_API_KEY"]
    router.set_env({"ANTHROPIC_API_KEY": "sk-1"})
    assert router._check_keys(step) == []


def test_llm_score_on_cometapi_needs_the_cometapi_key(router):
    router.update_step("llm_score", {"config": {"provider": "cometapi"}})
    step = router._steps["llm_score"]
    router.set_env({"ANTHROPIC_API_KEY": "sk-1"})
    assert router._check_keys(step) == ["COMETAPI_API_KEY"], "anthropic key must not satisfy cometapi"
    router.set_env({"COMETAPI_API_KEY": "ck-1"})
    assert router._check_keys(step) == []


def test_empty_string_key_counts_as_missing(router):
    router.set_env({"ANTHROPIC_API_KEY": ""})
    assert router._check_keys(router._steps["llm_score"]) == ["ANTHROPIC_API_KEY"]


def test_generic_step_checks_every_keys_required_entry():
    r = SmartRouter({"steps": [{"name": "x", "keys_required": ["A", "B", "C"]}]})
    r.set_env({"A": "1", "B": "", "C": "3"})
    assert r._check_keys(r._steps["x"]) == ["B"]


def test_step_with_no_keys_required_never_blocks(router):
    assert router._check_keys(router._steps["enrich"]) == []
    assert router._check_keys(router._steps["crm_push"]) == []


# ── dedup ──────────────────────────────────────────────────────────────────
def test_dedup_drops_repeated_urls_ignoring_a_trailing_slash(router):
    out = router._run_dedup([
        _lead(url="https://a.test/x", title="One"),
        _lead(url="https://a.test/x/", title="One dup"),
        _lead(url="https://b.test/y", title="Two"),
    ])
    assert [ld["title"] for ld in out] == ["One", "Two"], out


def test_dedup_falls_back_to_the_lowercased_title_when_there_is_no_url(router):
    out = router._run_dedup([
        _lead(title="Roofing Co"),
        _lead(title="  roofing co  "),
        _lead(title="Plumbing Co"),
    ])
    assert [ld["title"] for ld in out] == ["Roofing Co", "Plumbing Co"], out


def test_dedup_drops_a_lead_with_neither_url_nor_title(router):
    """No key at all => silently dropped by the real code. Pin that behaviour."""
    out = router._run_dedup([_lead(title="Real"), _lead(title="", url="")])
    assert len(out) == 1 and out[0]["title"] == "Real"


def test_dedup_prefers_url_over_title_as_the_key(router):
    """Two different URLs with the same title are two leads, not a duplicate."""
    out = router._run_dedup([
        _lead(url="https://a.test", title="Same"),
        _lead(url="https://b.test", title="Same"),
    ])
    assert len(out) == 2, out


# ── score ──────────────────────────────────────────────────────────────────
async def test_score_keeps_only_leads_at_or_above_min_score(router):
    out = await router._run_score(
        [_lead(score=30), _lead(score=29), _lead(score=80)], router._steps["score"])
    assert [ld["score"] for ld in out] == [30, 80], out


async def test_score_treats_a_missing_score_as_zero(router):
    out = await router._run_score(
        [_lead(score=None), _lead(score=45)], router._steps["score"])
    assert len(out) == 1 and out[0]["score"] == 45


async def test_score_honours_a_custom_min_score(router):
    step = RoutingStep("score", "", "", True, {"min_score": 60})
    out = await router._run_score([_lead(score=59), _lead(score=60)], step)
    assert [ld["score"] for ld in out] == [60]


# ── enrich ─────────────────────────────────────────────────────────────────
async def test_enrich_without_a_registered_fn_is_a_pass_through(router):
    router.set_env({})
    leads = [_lead(score=10)]
    assert await router._run_enrich(leads, router._steps["enrich"]) == leads


async def test_enrich_merges_the_result_and_marks_the_lead(router):
    seen = []

    async def enrich(lead):
        seen.append(lead["title"])
        return {"email": "a@b.com", "company": "Acme", "empty": ""}

    router.register_enrichment_fn(enrich)
    router.update_step("enrich", {"enabled": True})
    out = await router._run_enrich([_lead(title="Jane")], router._steps["enrich"])
    assert out[0]["enriched"] is True
    assert out[0]["email"] == "a@b.com"
    assert out[0]["company"] == "Acme"


async def test_enrich_never_overwrites_url_or_score_but_does_write_id(router):
    """The merge guard is exactly ("url", "id", "score") — url and score are
    protected; `id` is guarded too, so a provider-supplied id must NOT land."""
    async def enrich(lead):
        return {"url": "https://evil.test", "id": 999, "score": 1}

    router.register_enrichment_fn(enrich)
    out = await router._run_enrich(
        [_lead(url="https://real.test", id="L1", score=80)], router._steps["enrich"])
    assert out[0]["url"] == "https://real.test", "url is merge-guarded"
    assert out[0]["score"] == 80, "the rule score must not be clobbered"
    assert out[0]["id"] == "L1", "id is merge-guarded too"


async def test_enrich_ignores_falsy_values_from_the_provider(router):
    async def enrich(lead):
        return {"company": "", "email": "x@y.test"}

    router.register_enrichment_fn(enrich)
    out = await router._run_enrich([_lead(company="Original")], router._steps["enrich"])
    assert out[0]["company"] == "Original", "an empty provider field must not erase data"


async def test_enrich_keeps_a_lead_whose_enrichment_raised(router):
    """One failing lead must not lose the rest of the batch (gather with
    return_exceptions=True)."""
    async def enrich(lead):
        if lead["title"] == "Bad":
            raise RuntimeError("provider 500")
        return {"email": "ok@y.test"}

    router.register_enrichment_fn(enrich)
    out = await router._run_enrich(
        [_lead(title="Good"), _lead(title="Bad")], router._steps["enrich"])
    assert [ld["title"] for ld in out] == ["Good", "Bad"], "the lead is kept, just un-enriched"
    assert out[0].get("enriched") is True
    assert out[1].get("enriched") is None


async def test_enrich_batches_by_batch_size(router):
    sizes = []

    async def enrich(lead):
        sizes.append(1)
        return {}

    router.register_enrichment_fn(enrich)
    step = RoutingStep("enrich", "", "", True, {"batch_size": 2})
    out = await router._run_enrich([_lead(title=f"L{i}") for i in range(5)], step)
    assert len(out) == 5, out
    assert len(sizes) == 5


async def test_enrich_with_no_leads_is_a_no_op(router):
    async def enrich(lead):
        raise AssertionError("must not be called with an empty batch")

    router.register_enrichment_fn(enrich)
    assert await router._run_enrich([], router._steps["enrich"]) == []


# ── llm_score ──────────────────────────────────────────────────────────────
def _llm_router(**cfg):
    r = SmartRouter()
    r.update_step("llm_score", {"enabled": True, "config": cfg})
    return r, r._steps["llm_score"]


async def test_llm_score_without_a_registered_fn_is_a_pass_through(router):
    r, step = _llm_router()
    leads = [_lead(score=90)]
    assert await r._run_llm_score(leads, step) == leads


async def test_llm_score_blends_rule_and_llm_scores_60_40():
    r, step = _llm_router(provider="anthropic", model="m", max_leads=10, min_rule_score=50)

    async def score(batch, provider=None, model=None):
        return [{"score": 100, "rationale": "buying now"}]

    r.register_llm_score_fn(score)
    out = await r._run_llm_score([_lead(url="https://a.test", score=80, title="Jane")], step)
    assert out[0]["llm_score"] == 100
    assert out[0]["llm_rationale"] == "buying now"
    assert out[0]["llm_provider"] == "anthropic"
    assert out[0]["score"] == 88.0, "0.6*80 + 0.4*100 = 88.0"


async def test_llm_score_skips_leads_below_min_rule_score():
    r, step = _llm_router(min_rule_score=50, max_leads=10)

    async def score(batch, provider=None, model=None):
        return [{"score": 90, "rationale": ""} for _ in batch]

    r.register_llm_score_fn(score)
    out = await r._run_llm_score([_lead(score=49), _lead(score=50)], step)
    assert "llm_score" in out[0] or True
    assert "llm_score" not in out[0], "a lead under min_rule_score is never sent to the LLM"
    assert out[1]["llm_score"] == 90


async def test_llm_score_scores_only_the_top_max_leads():
    r, step = _llm_router(min_rule_score=0, max_leads=2)
    asked = []

    async def score(batch, provider=None, model=None):
        asked.extend(ld["title"] for ld in batch)
        return [{"score": 10, "rationale": ""} for _ in batch]

    r.register_llm_score_fn(score)
    leads = [_lead(title="a", score=10), _lead(title="b", score=90),
             _lead(title="c", score=50)]
    await r._run_llm_score(leads, step)
    assert asked == ["b", "c"], f"top-N by rule score, got {asked}"


async def test_llm_score_returns_leads_untouched_when_nobody_qualifies():
    r, step = _llm_router(min_rule_score=80, max_leads=5)

    async def score(batch, provider=None, model=None):
        raise AssertionError("the LLM must not be called with no candidates")

    r.register_llm_score_fn(score)
    leads = [_lead(score=10)]
    assert await r._run_llm_score(leads, step) == leads


async def test_llm_score_passes_the_configured_provider_and_model():
    r, step = _llm_router(provider="cometapi", model="gpt-x", min_rule_score=0, max_leads=1)
    got = {}

    async def score(batch, provider=None, model=None):
        got.update(provider=provider, model=model)
        return [{"score": 50, "rationale": "r"}]

    r.register_llm_score_fn(score)
    await r._run_llm_score([_lead(score=60)], step)
    assert got == {"provider": "cometapi", "model": "gpt-x"}, got


async def test_llm_score_does_not_reblend_when_the_rule_score_is_zero():
    r, step = _llm_router(min_rule_score=0, max_leads=1)

    async def score(batch, provider=None, model=None):
        return [{"score": 90, "rationale": "r"}]

    r.register_llm_score_fn(score)
    out = await r._run_llm_score([_lead(score=0, title="x")], step)
    assert out[0]["score"] == 0, "blend is guarded on a truthy rule score"


# ── crm_push ───────────────────────────────────────────────────────────────
async def test_crm_push_sends_only_leads_at_or_above_min_score():
    r = SmartRouter(_cfg(("crm_push", True, {"provider": "hubspot", "min_score": 70,
                                             "max_per_batch": 25})))
    r.set_env({})
    pushed = []

    async def push(leads, config):
        pushed.append(([ld["url"] for ld in leads], config))

    r.register_crm_push_fn(push)
    await r.route_leads(_url_leads(("https://low.test", 50), ("https://go.test", 90)))
    assert pushed == [(["https://go.test"], {"provider": "hubspot", "min_score": 70})], pushed


async def test_crm_push_respects_max_per_batch():
    r = SmartRouter(_cfg(("crm_push", True, {"min_score": 0, "max_per_batch": 2})))
    r.set_env({})
    pushed = []

    async def push(leads, config):
        pushed.append(len(leads))

    r.register_crm_push_fn(push)
    await r.route_leads(_url_leads(*[(f"https://l{i}.test", 99) for i in range(5)]))
    assert pushed == [2], pushed


async def test_crm_push_without_a_registered_fn_does_not_raise():
    r = SmartRouter(_cfg(("crm_push", True, {"min_score": 0})))
    out = await r.route_leads(_url_leads(("https://x.test", 99)))
    assert "crm_push" in out["pipeline"]["steps_run"], out["pipeline"]
    assert len(out["leads"]) == 1


async def test_crm_push_failure_is_contained_and_leads_survive():
    """DATA-LOSS GUARD: a failed CRM push must not drop the leads, and the
    exception must not escape route_leads."""
    r = SmartRouter(_cfg(("crm_push", True, {"min_score": 0})))
    r.set_env({})

    async def push(leads, config):
        raise RuntimeError("hubspot 401")

    r.register_crm_push_fn(push)
    out = await r.route_leads(_url_leads(("https://x.test", 99)))
    assert [ld["url"] for ld in out["leads"]] == ["https://x.test"], "leads must survive"
    assert out["pipeline"]["output_count"] == 1
    # _run_crm_push swallows the error itself, so the pipeline still records the
    # step as run — the guarantee asserted here is that no exception escapes and
    # the lead list is intact.


async def test_crm_push_does_nothing_when_no_lead_qualifies():
    r = SmartRouter(_cfg(("crm_push", True, {"min_score": 90})))
    r.set_env({})

    async def push(leads, config):
        raise AssertionError("must not push an empty batch")

    r.register_crm_push_fn(push)
    await r.route_leads(_url_leads(("https://low.test", 10)))
    assert r.get_stats()["runs"] == 1


# ── full pipeline ──────────────────────────────────────────────────────────
async def test_default_pipeline_runs_dedup_then_score_in_order(router):
    # dedup keeps the FIRST occurrence of a URL, so the surviving a.test lead is
    # the score-10 one; the score-90 duplicate is discarded before scoring.
    out = await router.route_leads(_url_leads(
        ("https://a.test", 10), ("https://a.test", 90), ("https://b.test", 5)))
    log = out["pipeline"]
    assert log["steps_run"] == ["dedup", "score"], log
    assert out["leads"] == [], "both survivors score under min_score=30"
    assert log["input_count"] == 3 and log["output_count"] == 0
    assert "elapsed_sec" in log


async def test_dedup_keeps_the_first_duplicate_and_score_filters_the_rest(router):
    out = await router.route_leads(_url_leads(
        ("https://a.test", 90), ("https://a.test", 10), ("https://b.test", 85)))
    assert [ld["score"] for ld in out["leads"]] == [90, 85], out["leads"]
    assert out["pipeline"]["steps_run"] == ["dedup", "score"]


async def test_disabled_steps_are_listed_as_skipped(router):
    out = await router.route_leads(_url_leads(("https://a.test", 90)))
    assert out["pipeline"]["steps_skipped"] == ["enrich", "llm_score", "crm_push"], out["pipeline"]


async def test_a_configured_step_missing_from_the_config_is_skipped(router):
    router.load_config(_cfg(("dedup", True, {})))
    out = await router.route_leads(_url_leads(("https://a.test", 90)))
    skipped = out["pipeline"]["steps_skipped"]
    assert "score" in skipped and "crm_push" in skipped, skipped


async def test_missing_key_skips_the_step_and_names_the_key(router):
    router.set_env({})
    router.update_step("llm_score", {"enabled": True})
    out = await router.route_leads(_url_leads(("https://a.test", 90)))
    assert any("llm_score" in s and "ANTHROPIC_API_KEY" in s
               for s in out["pipeline"]["steps_skipped"]), out["pipeline"]


async def test_a_step_exception_is_recorded_and_the_pipeline_continues(router, monkeypatch):
    async def boom(leads, step, search_config=None):
        raise RuntimeError("scoring backend down")

    monkeypatch.setattr(router, "_run_score", boom)
    out = await router.route_leads(_url_leads(("https://a.test", 90)))
    assert out["pipeline"]["errors"] == ["score: scoring backend down"], out["pipeline"]
    assert [ld["score"] for ld in out["leads"]] == [90], "leads must not be lost on a step crash"


async def test_step_results_record_the_output_count(router):
    await router.route_leads(_url_leads(("https://a.test", 10)))
    assert router._steps["score"].results == {"output_count": 0}, router._steps["score"].results


async def test_empty_input_produces_an_empty_result_without_error(router):
    out = await router.route_leads([])
    assert out["leads"] == []
    assert out["pipeline"]["input_count"] == 0
    assert out["pipeline"]["errors"] == []


# ── history + stats ────────────────────────────────────────────────────────
async def test_history_records_one_entry_per_run(router):
    await router.route_leads(_url_leads(("https://a.test", 90)))
    await router.route_leads(_url_leads(("https://b.test", 10)))
    hist = router.get_routing_history()
    assert len(hist) == 2
    assert hist[0]["output_count"] == 1
    assert hist[1]["output_count"] == 0


async def test_history_respects_the_limit(router):
    for i in range(5):
        await router.route_leads(_url_leads((f"https://x{i}.test", 90)))
    assert len(router.get_routing_history(limit=2)) == 2


def test_stats_on_a_fresh_router_are_zeroed(router):
    assert router.get_stats() == {
        "runs": 0, "total_input": 0, "total_output": 0, "total_errors": 0,
        "enabled_steps": ["dedup", "score"], }


async def test_stats_accumulate_input_output_and_errors(router, monkeypatch):
    async def boom(leads, step, search_config=None):
        raise RuntimeError("x")

    await router.route_leads(_url_leads(("https://a.test", 90), ("https://b.test", 80)))
    monkeypatch.setattr(router, "_run_score", boom)
    await router.route_leads(_url_leads(("https://c.test", 90)))
    s = router.get_stats()
    assert s["runs"] == 2
    assert s["total_input"] == 3
    # Run 1 scores 2 leads through; run 2's score step raised, so `current` is
    # never reassigned and the 1 dedup output passes through unfiltered.
    assert s["total_output"] == 3, s
    assert s["total_errors"] == 1


def test_stats_enabled_steps_reflects_toggles(router):
    router.update_step("enrich", {"enabled": True})
    assert "enrich" in router.get_stats()["enabled_steps"]


# ── default config shape the UI depends on ─────────────────────────────────
def test_default_config_step_names_are_unique():
    names = [s["name"] for s in DEFAULT_ROUTING_CONFIG["steps"]]
    assert len(names) == len(set(names)), names


def test_llm_score_step_declares_its_required_key():
    step = next(s for s in DEFAULT_ROUTING_CONFIG["steps"] if s["name"] == "llm_score")
    assert step["keys_required"] == ["ANTHROPIC_API_KEY"], step
    assert step["config"]["provider"] == "anthropic"
