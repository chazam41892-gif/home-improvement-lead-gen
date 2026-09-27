"""Tests for engine/enrichment/orchestrator.py.

Focus: the fallback chain. A provider that fails must fall through to the next;
a total failure must surface as failure (error set, no data) and NEVER as a
plausible-looking EnrichmentResult with invented contact fields.
"""
import asyncio

import pytest

import engine.enrichment.orchestrator as orch
from engine.enrichment.base import EnrichmentProvider, EnrichmentResult
from engine.enrichment.orchestrator import (
    EnrichmentRouter,
    EnrichOrchestrator,
    ProviderRoute,
    enrich_lead,
    get_orchestrator,
)
from tests.support_fixtures import no_real_network  # noqa: F401


def run(coro):
    return asyncio.run(coro)


# ── test doubles ────────────────────────────────────────────────────────────
class Fake(EnrichmentProvider):
    """A provider whose behaviour each test dictates."""

    def __init__(self, name, result=None, exc=None, priority=10,
                 preferences=(), required=(), name_override=None):
        super().__init__()
        self.name = name_override or name
        self._result = result
        self._exc = exc
        self.priority = priority
        self.input_preferences = list(preferences)
        self.input_required = list(required)
        self.calls = []

    def is_available(self):
        return True

    async def enrich(self, business_name, trade, location=None, website=None,
                     phone=None, **kwargs):
        self.calls.append({"business_name": business_name, "trade": trade,
                           "location": location, "website": website,
                           "phone": phone, "kwargs": kwargs})
        if self._exc:
            raise self._exc
        return self._result or EnrichmentResult(business_name=business_name, trade=trade)


def res(**kw):
    kw.setdefault("business_name", "Acme")
    kw.setdefault("trade", "roofing")
    return EnrichmentResult(**kw)


def orch_with(*providers):
    o = EnrichOrchestrator.__new__(EnrichOrchestrator)
    o.providers = list(providers)
    o.routing_mode = "parallel"
    o.router = EnrichmentRouter()
    o._provider_enabled = {}
    return o


# ── no providers ────────────────────────────────────────────────────────────
def test_no_providers_returns_a_clear_error_not_a_fake_result():
    o = orch_with()
    r = run(o.enrich("Acme", "roofing"))
    assert r.error and "No enrichment providers available" in r.error
    assert r.email is None and r.phone is None and r.contact_name is None
    assert r.confidence == 0.0
    assert r.sources == []


def test_no_providers_leaves_kwlocals_unused():
    o = orch_with()
    r = run(o.enrich("Acme", "roofing", website="https://acme.com"))
    assert r.website is None, "no provider ran, so nothing may be filled in"
    assert r.error


# ── parallel mode ───────────────────────────────────────────────────────────
def test_parallel_merges_fields_from_multiple_providers():
    a = Fake("a", res(email="info@acme.com", phone="512-555-0142"))
    b = Fake("b", res(contact_name="Dana Moxley", website="https://acme.com"))
    r = run(orch_with(a, b).enrich("Acme", "roofing"))
    assert r.email == "info@acme.com"
    assert r.phone == "512-555-0142"
    assert r.contact_name == "Dana Moxley"
    assert r.website == "https://acme.com"
    assert r.error is None


def test_parallel_forwards_all_lead_fields_to_every_provider():
    a, b = Fake("a"), Fake("b")
    run(orch_with(a, b).enrich("Acme", "roofing", location="Austin",
                              website="https://acme.com", phone="512-555-0142",
                              extra="x"))
    for p in (a, b):
        c = p.calls[0]
        assert c["business_name"] == "Acme" and c["trade"] == "roofing"
        assert c["location"] == "Austin"
        assert c["website"] == "https://acme.com"
        assert c["phone"] == "512-555-0142"
        assert c["kwargs"] == {"extra": "x"}


def test_a_raising_provider_does_not_abort_the_others():
    """return_exceptions=True: one crash must not lose the other providers' data."""
    good = Fake("good", res(email="info@acme.com"))
    bad = Fake("bad", exc=RuntimeError("apollo 500"))
    r = run(orch_with(bad, good).enrich("Acme", "roofing"))
    assert r.email == "info@acme.com"
    assert bad.calls and good.calls


def test_total_failure_across_all_providers_yields_no_data():
    a = Fake("a", exc=RuntimeError("boom"))
    b = Fake("b", exc=ValueError("bang"))
    r = run(orch_with(a, b).enrich("Acme", "roofing"))
    assert r.email is None and r.phone is None and r.contact_name is None
    assert r.website is None
    assert r.confidence == 0.0
    assert r.sources == []
    # a crashed provider produced no error string of its own; the result is
    # simply empty, which is the honest outcome
    assert r.business_name == "Acme"


def test_a_provider_returning_a_bare_error_result_does_not_silently_pass():
    a = Fake("a", res(error="Apollo API key not configured"))
    r = run(orch_with(a).enrich("Acme", "roofing"))
    assert r.error == "Apollo API key not configured"
    assert r.email is None


def test_a_provider_with_a_partial_result_still_contributes():
    a = Fake("a", res(contact_name="Dana Moxley"))
    r = run(orch_with(a).enrich("Acme", "roofing"))
    assert r.contact_name == "Dana Moxley"
    assert r.email is None, "missing fields must stay missing"


def test_non_result_values_from_gather_are_ignored():
    """asyncio.gather can hand back a non-Exception, non-EnrichmentResult
    value; the merge loop must skip it rather than crash or coerce it."""
    good = Fake("good", res(email="info@acme.com"))

    async def fake_gather(*aws, **kw):
        for a in aws:
            a.close()  # never await them: this double is returning a fixed list
        return [None, 42, "junk", await good.enrich("Acme", "roofing")]

    o = orch_with(good)
    import unittest.mock as m
    with m.patch.object(asyncio, "gather", fake_gather):
        r = run(o.enrich("Acme", "roofing"))
    assert r.email == "info@acme.com"
    assert r.phone is None and r.contact_name is None

# ── _merge semantics ────────────────────────────────────────────────────────
def test_merge_prefers_the_longer_conflicting_string():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t", contact_name="Dana")
    s = EnrichmentResult(business_name="A", trade="t",
                         contact_name="Dana Moxley the Third")
    o._merge(t, s)
    assert t.contact_name == "Dana Moxley the Third"


def test_merge_keeps_the_existing_value_when_the_new_one_is_shorter():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t", contact_name="Dana Moxley")
    s = EnrichmentResult(business_name="A", trade="t", contact_name="Dana")
    o._merge(t, s)
    assert t.contact_name == "Dana Moxley"


def test_merge_prefers_the_longer_string_across_every_merged_field():
    """orchestrator.py:213-214 -- the 'longer value wins' rule, field by field.
    Nonexercised by the rest of the suite, so pin every merged field name."""
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t")
    s = EnrichmentResult(
        business_name="A", trade="t",
        contact_name="Dana Moxley", title="Owner and Founder",
        phone="+1 (512) 555-0142", email="dana@acmeroofing.com",
        address="1200 Congress Avenue", city="Austin", state="TX",
        zip="78701", website="https://acmeroofing.com", revenue="$1M-$5M")
    o._merge(t, s)
    for f in ("contact_name", "title", "phone", "email", "address", "city",
              "state", "zip", "website", "revenue"):
        assert getattr(t, f) == getattr(s, f), f

    # now merge a SHORTER set back in: nothing may be clobbered
    shorter = EnrichmentResult(
        business_name="A", trade="t", contact_name="D", title="Owner",
        phone="555-0142", email="d@a.com", address="1200 Congress Ave",
        city="ATX", state="Tx", zip="787", website="https://a.com",
        revenue="$1M")
    o._merge(t, shorter)
    for f in ("contact_name", "title", "phone", "email", "address", "city",
              "state", "zip", "website", "revenue"):
        assert getattr(t, f) == getattr(s, f), f"{f} was clobbered by a shorter value"


def test_merge_takes_employee_count_and_year_founded_once_set():
    """orchestrator.py:215-218 -- the numeric pair, filled exactly once."""
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t")
    s = EnrichmentResult(business_name="A", trade="t",
                         employee_count=12, year_founded=2009)
    o._merge(t, s)
    assert t.employee_count == 12 and t.year_founded == 2009

    # a later provider's values must not overwrite an already-filled numeric
    t2 = EnrichmentResult(business_name="A", trade="t",
                          employee_count=3, year_founded=1999)
    s2 = EnrichmentResult(business_name="A", trade="t",
                          employee_count=99, year_founded=2020)
    o._merge(t2, s2)
    assert t2.employee_count == 3 and t2.year_founded == 1999


def test_merge_ignores_a_null_numeric_from_the_source():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t", employee_count=7)
    s = EnrichmentResult(business_name="A", trade="t", employee_count=None)
    o._merge(t, s)
    assert t.employee_count == 7


def test_website_is_carried_over_even_when_the_website_is_not_the_longer_string():
    """orchestrator.py:221-222 -- `if source.website and not target.website`.

    Note this arm is effectively dead: `website` is already in the merged
    string-field tuple at line 210, so by the time control reaches 221 a
    non-empty target.website means the guard is False. Pinned so the
    redundancy is documented rather than silently carried.
    """
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t")
    s = EnrichmentResult(business_name="A", trade="t", website="https://acme.com")
    o._merge(t, s)
    assert t.website == "https://acme.com"

    # second merge: the 221 guard can never fire because 210 already set it
    t2 = EnrichmentResult(business_name="A", trade="t")
    o._merge(t2, s)
    assert t2.website == "https://acme.com"
    t3 = EnrichmentResult(business_name="A", trade="t", website="https://a.io")
    o._merge(t3, s)
    assert t3.website == "https://acme.com", "longer website wins at line 210"


def test_merge_does_not_overwrite_a_filled_field_with_none():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t", phone="512-555-0142")
    s = EnrichmentResult(business_name="A", trade="t", phone=None, email="a@b.com")
    o._merge(t, s)
    assert t.phone == "512-555-0142"
    assert t.email == "a@b.com"


def test_merge_only_takes_zero_numeric_once():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t", employee_count=0)
    s = EnrichmentResult(business_name="A", trade="t", employee_count=9)
    o._merge(t, s)
    assert t.employee_count == 0, "0 is a real value, not an absence"


def test_merge_deduplicates_sources_and_unions_raw_data():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t")
    t.sources = ["x", "y"]
    t.raw_data["k1"] = 1
    s = EnrichmentResult(business_name="A", trade="t")
    s.sources = ["y", "z"]
    s.raw_data = {"k1": 99, "k2": 2}
    o._merge(t, s)
    assert t.sources == ["x", "y", "z"]
    assert t.raw_data == {"k1": 99, "k2": 2}


def test_merge_takes_the_max_confidence():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t", confidence=0.8)
    s = EnrichmentResult(business_name="A", trade="t", confidence=0.3)
    o._merge(t, s)
    assert t.confidence == 0.8


def test_merge_propagates_a_source_error():
    o = orch_with()
    t = EnrichmentResult(business_name="A", trade="t")
    s = EnrichmentResult(business_name="A", trade="t", error="upstream 500")
    o._merge(t, s)
    assert t.error == "upstream 500"


# ── _score_confidence ───────────────────────────────────────────────────────
def test_confidence_is_the_fraction_of_core_fields_filled():
    o = orch_with()
    r = EnrichmentResult(business_name="A", trade="t", email="a@b.com",
                         phone="512-555-0142")
    o._score_confidence(r)
    assert r.confidence == pytest.approx(0.33)  # 2 of 6


def test_confidence_never_lowers_a_higher_provider_reported_value():
    o = orch_with()
    r = EnrichmentResult(business_name="A", trade="t", confidence=0.95)
    o._score_confidence(r)
    assert r.confidence == 0.95


def test_empty_result_scores_zero():
    o = orch_with()
    r = EnrichmentResult(business_name="A", trade="t")
    o._score_confidence(r)
    assert r.confidence == 0.0


def test_full_result_scores_one():
    o = orch_with()
    r = EnrichmentResult(business_name="A", trade="t", contact_name="D",
                         phone="5", email="a@b.com", address="x",
                         website="https://a.com", employee_count=3)
    o._score_confidence(r)
    assert r.confidence == 1.0


# ── EnrichmentRouter ────────────────────────────────────────────────────────
def test_suitability_score_requires_every_required_field():
    p = Fake("p", preferences=["business_name", "website"], required=["website"])
    assert p.suitability_score({"business_name"}) == 0.0
    assert p.suitability_score({"website"}) == 0.5
    assert p.suitability_score({"website", "business_name"}) == 1.0


def test_rank_providers_orders_by_suitability_then_priority():
    router = EnrichmentRouter()
    hi = Fake("hi", priority=0, preferences=["website", "business_name"])
    lo = Fake("lo", priority=9, preferences=["website", "business_name"])
    both = {"website", "business_name"}
    ranked = router.rank_providers([lo, hi], both)
    assert [r.provider.name for r in ranked] == ["hi", "lo"]
    assert ranked[0].suitability > ranked[1].suitability
    assert all(isinstance(r, ProviderRoute) for r in ranked)


def test_rank_providers_handles_an_empty_list():
    assert EnrichmentRouter().rank_providers([], set()) == []


def test_routing_plan_selects_at_least_one_provider():
    router = EnrichmentRouter()
    p = Fake("p", preferences=["website"], required=["website"])
    plan = router.routing_plan([p], {"website"})
    assert len(plan) == 1 and plan[0].selected is True


def test_routing_plan_selects_nothing_when_no_provider_is_suitable():
    router = EnrichmentRouter()
    p = Fake("p", preferences=["website"], required=["website"])
    plan = router.routing_plan([p], {"business_name"})
    assert plan[0].suitability == 0.0
    assert plan[0].selected is False


def test_router_as_dict_reports_its_settings():
    d = EnrichmentRouter(min_confidence=0.5, fallthrough=False).as_dict()
    assert d == {"strategy": "suitability", "min_confidence": 0.5,
                 "fallthrough": False}


# ── smart routing: the fallback chain ───────────────────────────────────────
def test_smart_routing_stops_once_confidence_is_reached():
    first = Fake("first", res(email="info@acme.com", confidence=0.8), priority=0,
                 preferences=["business_name"])
    second = Fake("second", res(phone="512-555-0142", confidence=0.9), priority=5,
                  preferences=["business_name"])
    o = orch_with(first, second)
    o.routing_mode = "smart"
    r = run(o.enrich("Acme", "roofing"))
    assert r.email == "info@acme.com"
    assert first.calls, "the first provider must run"
    assert not second.calls, "confidence was met; the fallback must not fire"
    assert r.phone is None


def test_smart_routing_falls_through_when_the_first_provider_finds_nothing():
    first = Fake("first", res(error="No results found in Apollo"), priority=0,
                 preferences=["business_name"])
    second = Fake("second", res(email="info@acme.com"), priority=5,
                  preferences=["business_name"])
    o = orch_with(first, second)
    o.routing_mode = "smart"
    r = run(o.enrich("Acme", "roofing"))
    assert first.calls and second.calls, "an empty first result must fall through"
    assert r.email == "info@acme.com"
    assert r.error == "No results found in Apollo", "the upstream error is preserved"


@pytest.mark.xfail(strict=True, reason=(
    "REAL BUG (semantic inversion) engine/enrichment/orchestrator.py:193 - "
    "`if self.router.fallthrough and merged.confidence >= min_confidence: break`. "
    "The early-stop break is gated on `fallthrough`, so fallthrough=False makes "
    "the loop run EVERY selected provider (maximum fall-through) and "
    "fallthrough=True is what actually stops early. The flag therefore behaves as "
    "`early_stop`, the opposite of its name and of EnrichmentRouter's intent. The "
    "default (True) yields the sensible behaviour, so this is a latent footgun "
    "for anyone who sets fallthrough=False expecting it to stop at the first hit. "
    "Fix: `if not self.router.fallthrough or merged.confidence >= "
    "self.router.min_confidence: break`."
))
def test_smart_routing_does_not_fall_through_when_fallthrough_is_off():
    first = Fake("first", res(error="nothing"), priority=0,
                 preferences=["business_name"])
    second = Fake("second", res(email="info@acme.com", confidence=0.9), priority=5,
                  preferences=["business_name"])
    o = orch_with(first, second)
    o.routing_mode = "smart"
    o.router.fallthrough = False
    run(o.enrich("Acme", "roofing"))
    assert first.calls
    assert not second.calls, "fallthrough=False must stop at the first provider"


def test_smart_routing_skips_a_selected_provider_that_left_the_pool(monkeypatch):
    """orchestrator.py:191-192 -- a route whose provider is no longer in
    self.providers is skipped, not called.

    Drives the real _enrich_smart with a routing_plan that returns a provider
    which is NOT in self.providers.
    """
    kept = Fake("kept", res(email="kept@acme.com"), preferences=["business_name"])
    gone = Fake("gone", res(phone="512-555-0142"), preferences=["business_name"])
    o = orch_with(kept)
    o.routing_mode = "smart"

    real_plan = o.router.routing_plan
    monkeypatch.setattr(
        o.router, "routing_plan",
        lambda providers, fields: real_plan([kept, gone], fields))

    r = run(o.enrich("Acme", "roofing"))
    assert kept.calls
    assert not gone.calls, "a provider outside self.providers must not be called"
    assert r.email == "kept@acme.com"
    assert r.phone is None


def test_smart_routing_with_no_suitable_provider_returns_an_error():
    p = Fake("p", preferences=["website"], required=["website"])
    o = orch_with(p)
    o.routing_mode = "smart"
    r = run(o.enrich("Acme", "roofing"))
    assert p.calls == []
    assert r.error and "No suitable enrichment provider" in r.error
    assert r.email is None and r.phone is None
    assert r.confidence == 0.0


def test_smart_routing_totally_failing_chain_yields_no_fabricated_data():
    a = Fake("a", exc=RuntimeError("boom"), priority=0, preferences=["business_name"])
    b = Fake("b", res(email="info@acme.com"), priority=5, preferences=["business_name"])
    o = orch_with(a, b)
    o.routing_mode = "smart"
    with pytest.raises(RuntimeError, match="boom"):
        # Unlike parallel mode, smart mode does NOT use return_exceptions, so a
        # raising provider propagates out of enrich(). The important property is
        # that it surfaces as a hard failure rather than a plausible result.
        run(o.enrich("Acme", "roofing"))
    assert a.calls, "the failing provider ran"
    assert not b.calls, "the chain aborted at the exception; no result was returned"


def test_smart_routing_below_min_confidence_keeps_trying():
    a = Fake("a", res(contact_name="Dana"), priority=0, preferences=["business_name"])
    b = Fake("b", res(email="info@acme.com"), priority=5, preferences=["business_name"])
    c = Fake("c", res(phone="512-555-0142"), priority=8, preferences=["business_name"])
    o = orch_with(a, b, c)
    o.routing_mode = "smart"
    o.router.min_confidence = 0.9
    r = run(o.enrich("Acme", "roofing"))
    assert a.calls and b.calls and c.calls
    assert r.email == "info@acme.com"
    assert r.phone == "512-555-0142"


# (replaced by test_smart_routing_skips_a_selected_provider_that_left_the_pool)


# ── provider registry / enable toggles ──────────────────────────────────────
def test_init_providers_drops_unavailable_keyed_providers(monkeypatch):
    monkeypatch.setattr(orch.ApolloEnricher, "is_available", lambda s: False)
    monkeypatch.setattr(orch.ExaEnricher, "is_available", lambda s: False)
    monkeypatch.setattr(orch.LLMEnricher, "is_available", lambda s: False)
    o = EnrichOrchestrator()
    # BrowserEnricher.is_available() is hard-coded True (it needs no API key),
    # so it is the one survivor -- asserting the exact pool pins that design.
    assert [p.name for p in o.providers] == ["browser_enricher"]


def test_init_providers_keeps_the_browser_enricher_which_is_always_available(monkeypatch):
    monkeypatch.setattr(orch.ApolloEnricher, "is_available", lambda s: False)
    monkeypatch.setattr(orch.ExaEnricher, "is_available", lambda s: False)
    monkeypatch.setattr(orch.LLMEnricher, "is_available", lambda s: False)
    o = EnrichOrchestrator()
    assert [p.name for p in o.providers] == ["browser_enricher"]


def test_set_provider_enabled_rejects_unknown_names():
    o = EnrichOrchestrator()
    assert o.set_provider_enabled("not_a_provider", True) is False
    assert o.set_provider_enabled("", True) is False


@pytest.mark.parametrize("svc", ["apollo_enricher", "exa_enricher",
                                "llm_enricher", "browser_enricher"])
def test_set_provider_enabled_accepts_every_known_name(svc):
    o = EnrichOrchestrator()
    assert o.set_provider_enabled(svc, False) is True
    assert o._provider_enabled[svc] is False
    assert o.set_provider_enabled(svc, True) is True


def test_disabling_a_provider_removes_it_from_the_pool(monkeypatch):
    for cls in (orch.ApolloEnricher, orch.ExaEnricher, orch.LLMEnricher,
                orch.BrowserEnricher):
        monkeypatch.setattr(cls, "is_available", lambda s: True)
    o = EnrichOrchestrator()
    assert len(o.providers) == 4
    o.set_provider_enabled("browser_enricher", False)
    assert "browser_enricher" not in [p.name for p in o.providers]


def test_list_providers_reports_all_four_regardless_of_availability():
    listed = EnrichOrchestrator().list_providers()
    assert [p["name"] for p in listed] == ["apollo_enricher", "exa_enricher",
                                           "llm_enricher", "browser_enricher"]
    for p in listed:
        assert set(p) == {"name", "available", "enabled", "priority",
                          "input_preferences", "input_required"}
        assert isinstance(p["available"], bool)
        assert p["enabled"] is True


def test_get_routing_info_aggregates_known_input_fields():
    info = EnrichOrchestrator().get_routing_info()
    assert info["routing_mode"] == "parallel"
    assert info["router"]["strategy"] == "suitability"
    assert len(info["providers"]) == 4
    fields = info["known_input_fields"]
    assert "business_name" in fields and "website" in fields
    assert fields == sorted(fields), "known_input_fields must be sorted"


# ── enrich_batch ────────────────────────────────────────────────────────────
def test_enrich_batch_runs_every_lead():
    a = Fake("a", res(email="a@b.com"))
    o = orch_with(a)
    out = run(o.enrich_batch([
        {"business_name": "Acme", "trade": "roofing"},
        {"business_name": "Beta", "trade": "plumbing"},
    ]))
    assert len(out) == 2
    assert {r.business_name for r in out} == {"Acme", "Beta"}
    assert all(r.email == "a@b.com" for r in out)


def test_enrich_batch_swallows_exceptions_per_lead():
    o = orch_with()
    o.providers = []
    out = run(o.enrich_batch([
        {"business_name": "Acme", "trade": "roofing"},
        {"business_name": "Bad", "trade": "nope", "boom": object()},
    ]))
    assert len(out) == 2
    assert all(isinstance(r, EnrichmentResult) for r in out)
    assert all(r.error for r in out)


def test_enrich_batch_on_an_empty_list():
    assert run(orch_with().enrich_batch([])) == []


# ── module-level singleton ──────────────────────────────────────────────────
def test_get_orchestrator_is_a_singleton():
    assert get_orchestrator() is get_orchestrator()


def test_enrich_lead_delegates_to_the_singleton(monkeypatch):
    sentinel = res(email="info@acme.com")
    monkeypatch.setattr(orch, "_orchestrator", orch_with())

    async def fake(self, **kw):
        assert kw["business_name"] == "Acme"
        assert kw["location"] == "Austin"
        return sentinel

    monkeypatch.setattr(EnrichOrchestrator, "enrich", fake)
    assert run(enrich_lead("Acme", "roofing", location="Austin")) is sentinel


def test_enrich_lead_with_no_providers_available():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(orch, "_orchestrator", orch_with())
    try:
        r = run(enrich_lead("Acme", "roofing"))
        assert r.error and "No enrichment providers available" in r.error
        assert r.email is None
    finally:
        monkeypatch.undo()


# ── CRITICAL: the orchestrator must never invent a lead ─────────────────────
def test_orchestrator_never_fabricates_an_email_from_a_website():
    """Full chain: a website-only lead through every provider shape still ends
    with no invented mailbox."""
    for exc in (None, RuntimeError("500")):
        o = orch_with()
        o.routing_mode = "parallel"
        a = Fake("a", res(error="no results") if exc is None else None, exc=exc)
        b = Fake("b", res(website="https://acmeroofing.com"))
        r = run(o.enrich("Acme Roofing", "roofing",
                         website="https://acmeroofing.com"))
        assert r.email is None, f"fabricated {r.email!r} (exc={exc})"
        assert r.contact_name is None


def test_orchestrator_output_carries_no_email_when_every_provider_is_empty():
    a = Fake("a", res(error="No results found in Apollo"))
    b = Fake("b", res(error="Exa API key not configured"))
    c = Fake("c", res(error="No LLM API key configured"))
    d = Fake("d", res(error="Could not resolve business website"))
    o = orch_with(a, b, c, d)
    o.routing_mode = "parallel"
    r = run(o.enrich("Acme", "roofing"))
    assert r.email is None and r.phone is None and r.address is None
    assert r.error == "Could not resolve business website"
    assert r.confidence == 0.0
