"""Tests for engine/search/perplexity.py.

PerplexitySearchProvider uses urllib and takes a base_url, so the whole path
runs against a real local HTTP server.
"""
import asyncio

import pytest

from engine.search.perplexity import PERPLEXITY_BASE, PerplexitySearchProvider
from tests.support_fixtures import no_real_network, vault_free  # noqa: F401
from tests.support_http import LocalServer, closed_port


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def pplx(srv):
    return PerplexitySearchProvider(api_key="pplx-key", base_url=srv.base)


# ── construction ────────────────────────────────────────────────────────────
def test_base_url_defaults_to_the_real_api():
    p = PerplexitySearchProvider(api_key="k")
    assert p.base_url == PERPLEXITY_BASE == "https://api.perplexity.ai"
    assert p.name == "perplexity"


def test_trailing_slash_is_stripped():
    assert PerplexitySearchProvider(api_key="k", base_url="http://x/").base_url == "http://x"


def test_api_key_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "env-key")
    assert PerplexitySearchProvider().api_key == "env-key"
    assert PerplexitySearchProvider(api_key="explicit").api_key == "explicit"


# ── missing key ─────────────────────────────────────────────────────────────
def test_search_without_key_errors_and_makes_no_request(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no HTTP request may be made without a key")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    r = run(PerplexitySearchProvider().search("roofers"))
    assert r.error == "PERPLEXITY_API_KEY not set. Add your key in Settings."
    assert r.hits == []
    assert r.provider == "perplexity"


# ── request building ────────────────────────────────────────────────────────
def test_search_posts_to_chat_completions_with_bearer_auth(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {"choices": [], "citations": []})
    run(pplx.search("roofers in Austin"))
    hdrs = srv.rec.requests[-1]["headers"]
    assert hdrs["authorization"] == "Bearer pplx-key"
    assert hdrs["content-type"] == "application/json"
    assert hdrs["user-agent"] == "LeviathanLeadGen/3.0"
    body = srv.rec.last_body("POST", "/chat/completions")
    assert body == {
        "model": "sonar-pro",
        "messages": [{"role": "user", "content": "roofers in Austin"}],
        "max_tokens": 1024,
    }


def test_num_results_and_search_type_are_accepted_but_not_sent(pplx, srv):
    """These kwargs exist on the signature for provider parity but the Sonar
    request body is fixed. Pin that so a change is a deliberate one."""
    srv.rec.add("POST", "/chat/completions", {"choices": [], "citations": []})
    run(pplx.search("q", num_results=3, search_type="neural"))
    body = srv.rec.last_body("POST", "/chat/completions")
    assert "num_results" not in body and "search_type" not in body
    assert body["max_tokens"] == 1024


# ── citation parsing (the primary path) ─────────────────────────────────────
def test_citations_become_hits_with_derived_titles(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {
        "id": "c1", "model": "sonar-pro",
        "choices": [{"message": {"content": "Acme is great."}}],
        "citations": ["https://acmeroofing.com", "https://www.bbb.org/biz/x"],
    })
    r = run(pplx.search("roofers in Austin"))
    assert len(r.hits) == 2
    assert r.hits[0].url == "https://acmeroofing.com"
    assert r.hits[0].title == "Source: acmeroofing.com"
    assert r.hits[1].title == "Source: bbb.org", "www. must be stripped"
    assert r.hits[0].score == 0.9
    assert r.hits[0].extras == {"source": "perplexity", "citation": True,
                                "model": "sonar-pro"}
    assert "roofers in Austin" in r.hits[0].snippet
    assert r.raw["id"] == "c1"
    assert r.error is None


def test_citations_are_truncated_by_num_results(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {
        "choices": [], "citations": [f"https://s{i}.com" for i in range(10)]})
    assert len(run(pplx.search("q", num_results=4)).hits) == 4


def test_empty_citation_strings_are_skipped(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {
        "choices": [], "citations": ["", "https://real.com", ""]})
    r = run(pplx.search("q"))
    assert [h.url for h in r.hits] == ["https://real.com"]


def test_citation_with_no_domain_yields_an_empty_source_title(pplx, srv):
    """urlparse never raises for a bare string, so the "Cited Business Source"
    fallback is unreachable. The hit is still returned, with a blank domain.

    Pinned so the near-empty title is a known behaviour rather than a surprise.
    """
    srv.rec.add("POST", "/chat/completions", {
        "choices": [], "citations": ["not-a-url-at-all"]})
    r = run(pplx.search("q"))
    assert r.hits[0].url == "not-a-url-at-all"
    assert r.hits[0].title == "Source: "
    assert r.error is None


# ── fallback path: no citations -> use the answer text ──────────────────────
def test_falls_back_to_choices_when_there_are_no_citations(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {
        "choices": [{"message": {"content": "Here are some roofers. " + "x" * 900}}],
        "citations": [],
    })
    r = run(pplx.search("roofers"))
    assert len(r.hits) == 1
    h = r.hits[0]
    assert h.title == "roofers"
    assert h.url == ""
    assert len(h.snippet) == 500
    assert h.score == 1.0
    assert h.extras == {"source": "perplexity", "model": "sonar-pro"}


def test_fallback_handles_a_choice_with_no_message(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {"choices": [{}], "citations": []})
    r = run(pplx.search("q"))
    assert r.hits[0].snippet == ""


def test_fallback_respects_num_results(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {
        "choices": [{"message": {"content": f"c{i}"}} for i in range(9)],
        "citations": []})
    assert len(run(pplx.search("q", num_results=2)).hits) == 2


def test_no_citations_and_no_choices_yields_zero_hits_not_an_error(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {"choices": [], "citations": []})
    r = run(pplx.search("q"))
    assert r.hits == []
    assert r.error is None, "an empty answer is a valid empty result"


def test_response_with_neither_key_is_an_empty_result(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {"id": "x"})
    r = run(pplx.search("q"))
    assert r.hits == [] and r.error is None


# ── error paths ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", [400, 401, 402, 429, 500, 502, 503])
def test_http_errors_become_a_populated_error(pplx, srv, status):
    srv.rec.add("POST", "/chat/completions", {"error": "nope"}, status=status)
    r = run(pplx.search("q"))
    assert r.hits == []
    assert r.error and f"HTTP {status}" in r.error
    assert r.raw is None


def test_rate_limit_message_is_preserved(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {"error": "too many requests"},
                status=429)
    assert "too many requests" in run(pplx.search("q")).error


def test_transport_failure_becomes_an_error(closed_port):
    p = PerplexitySearchProvider(api_key="k", base_url=closed_port, timeout=2.0)
    r = run(p.search("q"))
    assert r.hits == []
    assert r.error and "Error" in r.error
    assert r.raw is None


def test_malformed_json_becomes_an_error(pplx, srv):
    srv.rec.add("POST", "/chat/completions", raw="<html>bad gateway</html>")
    r = run(pplx.search("q"))
    assert r.hits == []
    assert r.error and "JSONDecodeError" in r.error


def test_empty_body_becomes_an_error(pplx, srv):
    srv.rec.add("POST", "/chat/completions", raw="")
    assert run(pplx.search("q")).error is not None


def test_concurrent_searches_all_succeed(pplx, srv):
    srv.rec.add("POST", "/chat/completions", {
        "choices": [], "citations": ["https://a.com"]})
    async def go():
        return await asyncio.gather(*(pplx.search(f"q{i}") for i in range(10)))
    rs = run(go())
    assert len(rs) == 10
    assert all(len(r.hits) == 1 and r.error is None for r in rs)


# ── CRITICAL: a search must never fabricate a citation ──────────────────────
def test_failed_search_returns_no_hits_instead_of_invented_urls(closed_port):
    p = PerplexitySearchProvider(api_key="k", base_url=closed_port, timeout=2.0)
    r = run(p.search("roofers in Austin TX"))
    assert r.hits == []
    assert r.error is not None
    assert r.as_dict()["ok"] is False


def test_error_response_with_a_citations_key_is_not_mined_for_hits(pplx, srv):
    """A 200 that still carries an `error` field must not yield citations."""
    srv.rec.add("POST", "/chat/completions", {
        "error": "quota exceeded", "citations": ["https://ghost.example"]})
    r = run(pplx.search("q"))
    assert r.hits == []
    assert r.error and "quota exceeded" in r.error
