"""Tests for engine/enrichment/base.py — EnrichmentResult + EnrichmentProvider.

Coverage of the contract itself, not just importability.
"""
import asyncio

import pytest
from tests.support_fixtures import no_real_network  # noqa: F401

from engine.enrichment.base import EnrichmentProvider, EnrichmentResult


def run(coro):
    return asyncio.run(coro)


# ── EnrichmentResult ────────────────────────────────────────────────────────
def test_to_dict_omits_none_fields():
    r = EnrichmentResult(business_name="Acme Roofing", trade="roofing")
    d = r.to_dict()
    assert d["business_name"] == "Acme Roofing"
    assert d["trade"] == "roofing"
    for absent in ("email", "phone", "contact_name", "title", "website",
                   "error", "address", "city", "state", "zip", "revenue",
                   "employee_count", "year_founded"):
        assert absent not in d, f"{absent} should be dropped when None"
    # containers are always kept even when empty
    assert d["sources"] == []
    assert d["social_links"] == {}
    assert d["raw_data"] == {}


def test_to_dict_keeps_zero_confidence_because_it_is_not_none():
    r = EnrichmentResult(business_name="X", trade="y")
    assert r.confidence == 0.0
    assert "confidence" in r.to_dict()


def test_to_dict_keeps_falsy_but_present_values():
    r = EnrichmentResult(business_name="X", trade="y", revenue="", phone="")
    d = r.to_dict()
    assert d["revenue"] == "" and d["phone"] == ""


def test_mutable_defaults_are_not_shared():
    a = EnrichmentResult(business_name="A", trade="t")
    b = EnrichmentResult(business_name="B", trade="t")
    a.sources.append("s")
    a.social_links["facebook"] = "x"
    a.raw_data["k"] = 1
    assert b.sources == []
    assert b.social_links == {}
    assert b.raw_data == {}


# ── EnrichmentProvider contract ─────────────────────────────────────────────
def test_base_enrich_is_not_implemented():
    with pytest.raises(NotImplementedError):
        run(EnrichmentProvider().enrich("Acme", "roofing"))


def test_base_enrich_accepts_the_documented_signature():
    """The ABC's signature is the contract subclasses are written against."""
    import inspect

    sig = inspect.signature(EnrichmentProvider.enrich)
    params = list(sig.parameters)
    assert params[:5] == ["self", "business_name", "trade", "location", "website"]
    for p in ("phone", "kwargs"):
        assert p in sig.parameters
    assert sig.parameters["location"].default is None
    assert sig.parameters["website"].default is None
    assert sig.parameters["phone"].default is None
    assert sig.parameters["kwargs"].kind is inspect.Parameter.VAR_KEYWORD


def test_base_is_available_by_default_and_stores_config():
    p = EnrichmentProvider()
    assert p.is_available() is True
    assert p.config == {}
    assert EnrichmentProvider({"a": 1}).config == {"a": 1}
    assert p.name == "base"
    assert p.priority == 10


def test_suitability_is_one_when_no_preferences_declared():
    assert EnrichmentProvider().suitability_score(set()) == 1.0


def test_suitability_is_zero_when_a_required_field_is_missing():
    class NeedsWebsite(EnrichmentProvider):
        input_preferences = ["website", "business_name"]
        input_required = ["website"]

    p = NeedsWebsite()
    assert p.suitability_score({"business_name"}) == 0.0
    assert p.suitability_score({"website"}) == 0.5
    assert p.suitability_score({"website", "business_name"}) == 1.0
    # extra fields the provider does not care about do not help
    assert p.suitability_score({"website", "business_name", "phone"}) == 1.0


def test_suitability_counts_partial_matches_as_a_fraction():
    class P(EnrichmentProvider):
        input_preferences = ["a", "b", "c", "d"]
        input_required = []

    p = P()
    assert p.suitability_score(set()) == 0.0
    assert p.suitability_score({"a"}) == 0.25
    assert p.suitability_score({"a", "c"}) == 0.5


def test_subclass_that_forgets_to_implement_enrich_still_fails_loudly():
    """The contract is enforced at call time: no silent empty EnrichmentResult."""
    class Half(EnrichmentProvider):
        name = "half"
        def is_available(self):
            return True

    h = Half()
    assert h.is_available() is True
    with pytest.raises(NotImplementedError):
        run(h.enrich("Acme", "roofing"))


def test_shipped_providers_all_satisfy_the_contract():
    """Every real provider must implement enrich and not leak a class-level
    mutable list across instances (input_preferences is shared by design)."""
    from engine.enrichment.apollo_enricher import ApolloEnricher
    from engine.enrichment.browser_enricher import BrowserEnricher
    from engine.enrichment.exa_enricher import ExaEnricher
    from engine.enrichment.llm_enricher import LLMEnricher

    for cls in (ApolloEnricher, ExaEnricher, LLMEnricher, BrowserEnricher):
        p = cls()
        assert p.enrich.__func__ is not EnrichmentProvider.enrich, cls
        assert p.enrich.__func__.__code__.co_flags & 0x80, f"{cls.__name__} enrich must be async"
        assert isinstance(p.input_preferences, list) and p.input_preferences, cls
        assert isinstance(p.input_required, list), cls
        assert isinstance(p.priority, int), cls
        assert p.name and p.name != "base", cls
        assert 0.0 <= p.suitability_score(set(p.input_required + p.input_preferences)) <= 1.0
