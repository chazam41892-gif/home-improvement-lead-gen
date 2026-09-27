"""Tests for engine/enrichment/exa_enricher.py.

ExaEnricher delegates to engine.search.exa.ExaSearchProvider, which takes a
base_url — so the whole chain (enricher -> search provider -> real HTTP server)
runs against a local server with no mocking of httpx or urllib.
"""
import asyncio

import pytest

import engine.enrichment.exa_enricher as exa_enricher_mod
from engine.enrichment.exa_enricher import ExaEnricher
from tests.support_http import LocalServer
from tests.support_fixtures import no_real_network  # noqa: F401


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def vault(monkeypatch):
    keys = {}
    monkeypatch.setattr(exa_enricher_mod.KeyVault, "get",
                        staticmethod(lambda s: keys.get(s)))
    return keys


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def wired(vault, srv):
    vault["exa"] = "exa-key-1"
    e = ExaEnricher()
    exa = e._get_exa()
    exa.base_url = srv.base
    return e, srv.rec


# ── availability ────────────────────────────────────────────────────────────
def test_unavailable_without_key(vault):
    e = ExaEnricher()
    assert e.is_available() is False
    assert e._get_exa() is None
    r = run(e.enrich("Acme", "roofing"))
    assert r.error == "Exa API key not configured"
    assert r.email is None and r.sources == []


def test_available_with_key(vault):
    vault["exa"] = "k"
    assert ExaEnricher().is_available() is True


def test_exa_client_is_cached_after_first_lookup(vault, monkeypatch):
    calls = []

    def counting(s):
        calls.append(s)
        return "k" if s == "exa" else None

    # monkeypatch, not `KeyVault.get = ...`: a bare assignment permanently
    # replaces the classmethod for every later test in the session.
    monkeypatch.setattr(exa_enricher_mod.KeyVault, "get", staticmethod(counting))
    e = ExaEnricher()
    a, b = e._get_exa(), e._get_exa()
    assert a is b
    assert calls == ["exa"]


# ── _find_website ───────────────────────────────────────────────────────────
def test_find_website_skips_directories_and_returns_first_real_domain(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": [
        {"title": "Acme on Yelp", "url": "https://www.yelp.com/biz/acme"},
        {"title": "Acme Roofing", "url": "https://acmeroofing.com/"},
    ]})
    got = run(e._find_website("Acme Roofing", "roofing", "Austin"))
    assert got == "https://acmeroofing.com/"
    body = rec.last_body("POST", "/search")
    assert body["query"] == "Acme Roofing Austin"
    assert body["numResults"] == 5
    assert "contents" not in body, "text=False must not request contents"


@pytest.mark.parametrize("host", ["facebook.com", "instagram.com", "yelp.com",
                                 "twitter.com", "linkedin.com", "angi.com",
                                 "homeadvisor.com", "nextdoor.com"])
def test_find_website_rejects_every_directory_host(wired, host):
    e, rec = wired
    rec.add("POST", "/search", {"results": [
        {"title": "dir", "url": f"https://www.{host}/biz/acme"},
        {"title": "real", "url": "https://acmeroofing.com/"},
    ]})
    assert run(e._find_website("Acme", "roofing")) == "https://acmeroofing.com/"


def test_find_website_returns_a_www_url_when_that_is_all_there_is(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": [
        {"title": "x", "url": "https://www.acmeroofing.com/"}]})
    assert run(e._find_website("Acme", "roofing")) == "https://www.acmeroofing.com/"


def test_find_website_returns_none_when_only_directories_match(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": [
        {"title": "dir", "url": "https://www.yelp.com/biz/acme"}]})
    assert run(e._find_website("Acme", "roofing")) is None


def test_find_website_returns_none_on_empty_results(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": []})
    assert run(e._find_website("Acme", "roofing")) is None


def test_find_website_issues_a_second_query_including_the_trade(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": []})
    run(e._find_website("Acme Roofing", "roofing", "Austin"))
    assert [b["query"] for b in rec.bodies("POST", "/search")] == [
        "Acme Roofing Austin",
        "Acme Roofing roofing Austin",
    ]


def test_find_website_skips_the_trade_query_when_trade_is_empty(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": []})
    run(e._find_website("Acme Roofing", ""))
    assert len(rec.bodies("POST", "/search")) == 1


def test_find_website_survives_an_http_error(wired):
    e, rec = wired
    rec.add("POST", "/search", {"error": "boom"}, status=500)
    assert run(e._find_website("Acme", "roofing")) is None


def test_find_website_survives_a_malformed_response(wired):
    e, rec = wired
    rec.add("POST", "/search", raw="<html>not json</html>")
    assert run(e._find_website("Acme", "roofing")) is None


def test_find_website_is_none_without_a_client(vault):
    e = ExaEnricher()
    assert run(e._find_website("Acme", "roofing")) is None


# ── enrich() ────────────────────────────────────────────────────────────────
CONTENT_WITH_ALL = {
    "results": [{
        "text": ("Reach us at info@acmeroofing.com or call 512-555-0142. "
                 "We are located at 1200 Congress Ave, Austin, TX 78701. "
                 "Founded in 2009 and we employ 12 employees."),
        "highlights": [],
    }]
}


def test_enrich_scrapes_email_phone_and_address_from_page_text(wired):
    e, rec = wired
    rec.add("POST", "/contents", CONTENT_WITH_ALL)
    r = run(e.enrich("Acme Roofing", "roofing", website="https://acmeroofing.com"))
    assert r.email == "info@acmeroofing.com"
    assert r.phone == "512-555-0142"
    assert r.address is not None and "1200 Congress Ave" in r.address
    assert "exa:email" in r.sources and "exa:phone" in r.sources
    assert "exa:address" in r.sources
    assert "exa_enricher" in r.sources
    assert r.website == "https://acmeroofing.com"
    assert r.confidence >= 0.3
    assert r.error is None


def test_enrich_requests_the_right_contents_body(wired):
    e, rec = wired
    rec.add("POST", "/contents", CONTENT_WITH_ALL)
    run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    body = rec.last_body("POST", "/contents")
    assert body["ids"] == ["https://acmeroofing.com"]
    assert body["text"] is True
    assert body["highlights"] == {"numSentences": 3}


def test_enrich_includes_highlight_text_in_the_scan(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"results": [
        {"text": "no contact info here",
         "highlights": ["reach us: sales@acmeroofing.com"]}]})
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email == "sales@acmeroofing.com"


def test_enrich_resolves_the_website_first_when_missing(wired):
    e, rec = wired
    rec.add("POST", "/search", {"results": [
        {"title": "Acme", "url": "https://acmeroofing.com/"}]})
    rec.add("POST", "/contents", CONTENT_WITH_ALL)
    r = run(e.enrich("Acme Roofing", "roofing", location="Austin"))
    assert r.website == "https://acmeroofing.com/"
    assert rec.bodies("POST", "/contents")[0]["ids"] == ["https://acmeroofing.com/"]


def test_enrich_never_searches_when_a_website_was_supplied(wired):
    e, rec = wired
    rec.add("POST", "/contents", CONTENT_WITH_ALL)
    run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert rec.bodies("POST", "/search") == []


def test_enrich_with_page_containing_no_contact_details_yields_nothing_fake(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"results": [
        {"text": "We build beautiful kitchens. Serving Central Texas.",
         "highlights": []}]})
    r = run(e.enrich("Acme Kitchens", "kitchen", website="https://acmekitchens.com"))
    assert r.email is None, r
    assert r.phone is None
    assert r.address is None
    assert r.contact_name is None
    assert r.error is None
    # 0.3 is the flat "we fetched and scanned a page" floor, not a contact hit
    assert r.confidence == 0.3
    assert r.sources == ["exa_enricher"]
    assert "acmekitchens.com" not in (r.email or "")


def test_enrich_survives_a_401_from_the_contents_endpoint(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"error": "unauthorized"}, status=401)
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email is None and r.phone is None
    assert r.website == "https://acmeroofing.com"
    assert r.error is None, "exa content failure is a soft miss, not a hard error"


def test_enrich_survives_a_429_from_the_contents_endpoint(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"error": "rate limited"}, status=429)
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email is None
    assert r.sources == ["exa_enricher"]


def test_enrich_handles_a_contents_error_field_in_a_200_response(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"error": "crawl failed", "results": [
        {"text": "info@acmeroofing.com", "highlights": []}]})
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email is None, "an errored payload must not be mined for an email"
    assert r.sources == ["exa_enricher"]


def test_enrich_handles_ok_false_in_a_200_response(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"ok": False, "results": [
        {"text": "info@acmeroofing.com", "highlights": []}]})
    assert run(e.enrich("Acme", "roofing", website="https://a.com")).email is None


def test_enrich_handles_empty_results_list(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"results": []})
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email is None
    assert r.confidence == 0.0


def test_enrich_handles_a_result_with_null_text_and_null_highlights(wired):
    e, rec = wired
    rec.add("POST", "/contents", {"results": [{"text": None, "highlights": None}]})
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email is None and r.phone is None
    assert r.sources == ["exa_enricher"]


def test_enrich_survives_malformed_contents_json(wired):
    e, rec = wired
    rec.add("POST", "/contents", raw="<<not json>>")
    r = run(e.enrich("Acme", "roofing", website="https://acmeroofing.com"))
    assert r.email is None
    assert r.sources == ["exa_enricher"]


def test_enrich_never_fabricates_from_the_domain_when_nothing_is_found(wired):
    """The strongest no-fabrication guarantee: with a real website and a page
    that has zero contact data, nothing contact-shaped may appear."""
    e, rec = wired
    rec.add("POST", "/contents", {"results": [
        {"text": "Acme Roofing — quality work since 2009.", "highlights": []}]})
    r = run(e.enrich("Acme Roofing", "roofing", website="https://acmeroofing.com"))
    assert r.email is None
    assert r.phone is None
    assert r.address is None
    assert r.contact_name is None
    assert r.error is None
    # raw_data must not smuggle a synthesised contact value in either
    import re
    snippet = r.raw_data.get("exa_content_snippet", "")
    assert snippet.strip() == "Acme Roofing — quality work since 2009."
    assert not re.search(r"[\w.+-]+@[\w.-]+\.\w+", snippet)
    assert "512" not in snippet and "555" not in snippet
