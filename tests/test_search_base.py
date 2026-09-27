"""Tests for engine/search/base.py — SearchHit / SearchResult / SearchProvider."""
import asyncio

import pytest

from engine.search.base import SearchHit, SearchProvider, SearchResult
from tests.support_fixtures import no_real_network  # noqa: F401


def run(coro):
    return asyncio.run(coro)


# ── SearchHit ───────────────────────────────────────────────────────────────
def test_hit_defaults():
    h = SearchHit(title="T", url="https://x.com")
    assert h.snippet == ""
    assert h.published_date is None
    assert h.score == 0.0
    assert h.extras == {}


def test_hit_as_dict_flattens_extras():
    h = SearchHit(title="T", url="https://x.com", snippet="s",
                  published_date="2026-01-01", score=0.9,
                  extras={"author": "Ann", "image": "https://i.png"})
    assert h.as_dict() == {
        "title": "T", "url": "https://x.com", "snippet": "s",
        "published_date": "2026-01-01", "score": 0.9,
        "author": "Ann", "image": "https://i.png",
    }


def test_hit_extras_defaults_are_not_shared():
    a, b = SearchHit(title="A", url="a"), SearchHit(title="B", url="b")
    a.extras["k"] = 1
    assert b.extras == {}


# ── SearchResult ────────────────────────────────────────────────────────────
def test_result_as_dict_reports_ok_and_count():
    r = SearchResult(query="q", provider="exa",
                     hits=[SearchHit("a", "https://a"), SearchHit("b", "https://b")],
                     elapsed_sec=1.23456, total_results=17)
    d = r.as_dict()
    assert d["ok"] is True
    assert d["count"] == 2
    assert d["total_results"] == 17
    assert d["elapsed_sec"] == 1.235
    assert d["query"] == "q" and d["provider"] == "exa"
    assert d["error"] is None
    assert len(d["hits"]) == 2


def test_result_as_dict_reports_not_ok_on_error():
    r = SearchResult(query="q", provider="exa", hits=[], error="boom")
    d = r.as_dict()
    assert d["ok"] is False
    assert d["error"] == "boom"
    assert d["count"] == 0


def test_result_defaults():
    r = SearchResult(query="q", provider="p", hits=[])
    assert r.elapsed_sec == 0.0
    assert r.total_results is None
    assert r.raw is None
    assert r.error is None


# ── SearchProvider contract ─────────────────────────────────────────────────
def test_base_search_is_not_implemented():
    with pytest.raises(NotImplementedError):
        run(SearchProvider().search("q"))


def test_provider_stores_key_and_timeout():
    p = SearchProvider(api_key="k", timeout=7.5)
    assert p.api_key == "k" and p.timeout == 7.5
    d = SearchProvider()
    assert d.api_key is None and d.timeout == 30.0
    assert d.name == "base"


def test_search_signature_is_keyword_only_after_query():
    import inspect
    sig = inspect.signature(SearchProvider.search)
    assert list(sig.parameters) == ["self", "query", "num_results", "kwargs"]
    assert sig.parameters["query"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert sig.parameters["num_results"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["num_results"].default == 10


def test_shipped_providers_implement_search_and_are_async():
    from engine.search.browser_agent import BrowserSearchProvider
    from engine.search.exa import ExaSearchProvider
    from engine.search.perplexity import PerplexitySearchProvider

    for cls in (ExaSearchProvider, PerplexitySearchProvider, BrowserSearchProvider):
        p = cls()
        assert p.search.__func__ is not SearchProvider.search, cls
        assert p.search.__func__.__code__.co_flags & 0x80, f"{cls.__name__} must be async"
        assert p.name and p.name != "base", cls
