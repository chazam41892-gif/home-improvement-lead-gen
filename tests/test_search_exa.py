"""Tests for engine/search/exa.py.

ExaSearchProvider uses urllib (not httpx) and takes a base_url, so we point it
at a real local HTTP server — request body, headers, HTTP error handling,
transport failures and response parsing all run for real.
"""
import asyncio
import json

import pytest

from engine.search.exa import EXA_BASE, ExaSearchProvider
from tests.support_fixtures import no_real_network, vault_free  # noqa: F401
from tests.support_http import LocalServer, closed_port


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def exa(srv):
    return ExaSearchProvider(api_key="exa-key-1", base_url=srv.base)


# ── construction ────────────────────────────────────────────────────────────
def test_base_url_defaults_to_the_real_api():
    p = ExaSearchProvider(api_key="k")
    assert p.base_url == EXA_BASE == "https://api.exa.ai"


def test_trailing_slash_is_stripped_from_base_url():
    assert ExaSearchProvider(api_key="k", base_url="http://x/").base_url == "http://x"


def test_api_key_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "from-env")
    assert ExaSearchProvider().api_key == "from-env"
    assert ExaSearchProvider(api_key="explicit").api_key == "explicit"


# ── missing key ─────────────────────────────────────────────────────────────
def test_search_without_key_errors_and_makes_no_request(vault_free, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no HTTP request may be made without a key")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    r = run(ExaSearchProvider().search("roofers in Austin"))
    assert r.error == "EXA_API_KEY not set. Add your key in Settings."
    assert r.hits == []
    assert r.provider == "exa"
    assert r.raw is None


def test_contents_and_answer_without_key_short_circuit(vault_free):
    p = ExaSearchProvider()
    assert run(p.contents(["https://x.com"])) == {"ok": False, "error": "EXA_API_KEY not set"}
    assert run(p.answer("q")) == {"ok": False, "error": "EXA_API_KEY not set"}


# ── request building ────────────────────────────────────────────────────────
def test_search_posts_to_search_with_the_api_key_header(exa, srv):
    srv.rec.add("POST", "/search", {"results": []})
    run(exa.search("roofers"))
    assert srv.rec.count("POST") == 1
    hdrs = srv.rec.requests[-1]["headers"]
    assert hdrs["x-api-key"] == "exa-key-1"
    assert hdrs["content-type"] == "application/json"
    assert hdrs["user-agent"] == "LeviathanLeadGen/3.0"
    body = srv.rec.last_body("POST", "/search")
    assert body == {"query": "roofers", "numResults": 10, "type": "auto"}


def test_search_omits_optional_fields_by_default(exa, srv):
    srv.rec.add("POST", "/search", {"results": []})
    run(exa.search("q"))
    body = srv.rec.last_body("POST", "/search")
    for absent in ("category", "startPublishedDate", "endPublishedDate",
                   "includeDomains", "excludeDomains", "contents"):
        assert absent not in body, absent


def test_search_includes_every_optional_field_when_given(exa, srv):
    srv.rec.add("POST", "/search", {"results": []})
    run(exa.search("q", num_results=3, search_type="neural", category="company",
                   text=True, highlights=True, start_published_date="2026-01-01",
                   end_published_date="2026-06-01",
                   include_domains=["a.com"], exclude_domains=["b.com"]))
    body = srv.rec.last_body("POST", "/search")
    assert body["query"] == "q"
    assert body["numResults"] == 3
    assert body["type"] == "neural"
    assert body["category"] == "company"
    assert body["startPublishedDate"] == "2026-01-01"
    assert body["endPublishedDate"] == "2026-06-01"
    assert body["includeDomains"] == ["a.com"]
    assert body["excludeDomains"] == ["b.com"]
    assert body["contents"] == {"text": True, "highlights": {"numSentences": 3}}


def test_highlights_only_contents_block(exa, srv):
    srv.rec.add("POST", "/search", {"results": []})
    run(exa.search("q", highlights=True))
    assert srv.rec.last_body("POST", "/search")["contents"] == {"highlights": {"numSentences": 3}}


# ── response parsing ────────────────────────────────────────────────────────
RESULTS = {"requestId": "abc", "autopromptString": None, "results": [
    {"title": "Acme Roofing", "url": "https://acmeroofing.com",
     "text": "x" * 900, "publishedDate": "2026-02-01", "score": 0.91,
     "author": "Sam", "image": "https://i.png"},
    {"title": "B", "url": "https://b.com", "highlights": ["h1", "h2"]},
]}


def test_search_parses_results_into_hits(exa, srv):
    srv.rec.add("POST", "/search", RESULTS)
    r = run(exa.search("roofers"))
    assert r.error is None
    assert len(r.hits) == 2
    h = r.hits[0]
    assert h.title == "Acme Roofing"
    assert h.url == "https://acmeroofing.com"
    assert len(h.snippet) == 500, "text must be truncated to 500 chars"
    assert h.published_date == "2026-02-01"
    assert h.score == 0.91
    assert h.extras == {"author": "Sam", "image": "https://i.png"}
    assert r.raw is not None and r.raw["requestId"] == "abc"
    assert r.provider == "exa"


def test_search_falls_back_to_highlights_for_the_snippet(exa, srv):
    srv.rec.add("POST", "/search", RESULTS)
    r = run(exa.search("q"))
    assert r.hits[1].snippet == "h1 h2"
    assert r.hits[1].published_date is None
    assert r.hits[1].score == 0.0


def test_search_tolerates_null_fields(exa, srv):
    srv.rec.add("POST", "/search", {"results": [
        {"title": None, "url": None, "text": None, "highlights": None,
         "publishedDate": None, "score": None, "author": None, "image": None}]})
    r = run(exa.search("q"))
    h = r.hits[0]
    assert h.title == "" and h.url == "" and h.snippet == ""
    assert h.published_date is None and h.score == 0.0


def test_search_truncates_a_null_score_string(exa, srv):
    srv.rec.add("POST", "/search", {"results": [{"title": "t", "url": "u", "score": None}]})
    assert run(exa.search("q")).hits[0].score == 0.0


def test_search_respects_num_results_truncation(exa, srv):
    srv.rec.add("POST", "/search", {"results": [
        {"title": f"t{i}", "url": f"https://{i}.com"} for i in range(20)]})
    assert len(run(exa.search("q", num_results=5)).hits) == 5


def test_search_on_empty_results_list(exa, srv):
    srv.rec.add("POST", "/search", {"results": []})
    r = run(exa.search("q"))
    assert r.hits == [] and r.error is None


def test_search_on_a_response_with_no_results_key(exa, srv):
    srv.rec.add("POST", "/search", {"requestId": "x"})
    r = run(exa.search("q"))
    assert r.hits == [] and r.error is None


# ── error paths ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500, 502, 503])
def test_http_errors_become_a_populated_error_not_an_exception(exa, srv, status):
    srv.rec.add("POST", "/search", {"message": "nope"}, status=status)
    r = run(exa.search("q"))
    assert r.hits == []
    assert r.error is not None and f"HTTP {status}" in r.error
    assert r.raw is None
    assert r.provider == "exa"


def test_rate_limit_body_is_included_in_the_error(exa, srv):
    srv.rec.add("POST", "/search", {"message": "slow down"}, status=429)
    assert "slow down" in run(exa.search("q")).error


def test_long_error_body_is_truncated(exa, srv):
    srv.rec.add("POST", "/search", {"m": "z" * 5000}, status=500)
    err = run(exa.search("q")).error
    assert len(err) < 400, err[:80]


def test_transport_failure_becomes_an_error_string(closed_port):
    """Connection refused -> a populated error string, never an exception and
    never a plausible-looking empty result."""
    p = ExaSearchProvider(api_key="k", base_url=closed_port, timeout=2.0)
    r = run(p.search("q"))
    assert r.hits == []
    assert r.error and "Error" in r.error
    assert r.raw is None


def test_malformed_json_response_becomes_an_error(exa, srv):
    srv.rec.add("POST", "/search", raw="<html>gateway</html>")
    r = run(exa.search("q"))
    assert r.hits == []
    assert r.error and "JSONDecodeError" in r.error


def test_empty_body_response_becomes_an_error(exa, srv):
    srv.rec.add("POST", "/search", raw="")
    assert run(exa.search("q")).error is not None


def test_concurrent_searches_all_succeed(exa, srv):
    """The module-level semaphore must not deadlock or drop results."""
    srv.rec.add("POST", "/search", {"results": [
        {"title": "t", "url": "https://a.com"}]})
    async def go():
        return await asyncio.gather(*(exa.search(f"q{i}") for i in range(12)))
    rs = run(go())
    assert len(rs) == 12
    assert all(len(r.hits) == 1 and r.error is None for r in rs)


# ── contents() ──────────────────────────────────────────────────────────────
def test_contents_posts_the_right_body(exa, srv):
    srv.rec.add("POST", "/contents", {"results": [{"text": "hi"}]})
    out = run(exa.contents(["https://a.com", "https://b.com"]))
    assert out == {"results": [{"text": "hi"}]}
    body = srv.rec.last_body("POST", "/contents")
    assert body == {"ids": ["https://a.com", "https://b.com"],
                    "livecrawl": "fallback", "text": True}


def test_contents_options_are_included_when_requested(exa, srv):
    srv.rec.add("POST", "/contents", {"results": []})
    run(exa.contents(["https://a.com"], text=True, highlights=True,
                     summary=True, livecrawl="always"))
    body = srv.rec.last_body("POST", "/contents")
    assert body["highlights"] == {"numSentences": 3}
    assert body["summary"] == {"query": "summarize"}
    assert body["livecrawl"] == "always"


def test_contents_without_text_omits_the_text_flag(exa, srv):
    srv.rec.add("POST", "/contents", {"results": []})
    run(exa.contents(["https://a.com"], text=False))
    assert "text" not in srv.rec.last_body("POST", "/contents")


def test_contents_http_error_is_returned_as_an_error_dict(exa, srv):
    srv.rec.add("POST", "/contents", {"message": "bad"}, status=401)
    out = run(exa.contents(["https://a.com"]))
    assert "error" in out and "HTTP 401" in out["error"]


def test_contents_transport_failure_is_returned_as_an_error_dict(vault_free):
    p = ExaSearchProvider(api_key="k", base_url="http://127.0.0.1:9", timeout=1.0)
    out = run(p.contents(["https://a.com"]))
    assert "error" in out, out
    assert "Error" in out["error"], out


# ── answer() ────────────────────────────────────────────────────────────────
def test_answer_posts_the_right_body(exa, srv):
    srv.rec.add("POST", "/answer", {"answer": "42", "citations": []})
    out = run(exa.answer("what is the answer"))
    assert out["answer"] == "42"
    body = srv.rec.last_body("POST", "/answer")
    assert body == {"query": "what is the answer", "text": True}


def test_answer_text_false(exa, srv):
    srv.rec.add("POST", "/answer", {"answer": "x"})
    run(exa.answer("q", text=False))
    assert srv.rec.last_body("POST", "/answer") == {"query": "q", "text": False}


def test_answer_http_error_is_returned_as_an_error_dict(exa, srv):
    srv.rec.add("POST", "/answer", {"message": "nope"}, status=429)
    out = run(exa.answer("q"))
    assert "error" in out and "HTTP 429" in out["error"]


def test_answer_transport_failure_is_returned_as_an_error_dict(closed_port):
    p = ExaSearchProvider(api_key="k", base_url=closed_port, timeout=2.0)
    assert "error" in run(p.answer("q"))
