"""Tests for engine/enrichment/apollo_enricher.py.

Apollo is hard-coded to https://api.apollo.io/v1, so we monkeypatch only the
module constant APOLLO_BASE to a real local HTTP server. Everything else —
request body construction, headers, status handling, JSON parsing, the
people->EnrichmentResult mapping — runs for real.
"""
import asyncio

import pytest

import engine.enrichment.apollo_enricher as apollo_mod
from engine.enrichment.apollo_enricher import ApolloEnricher
from tests.support_http import LocalServer
from tests.support_fixtures import no_real_network  # noqa: F401


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def vault(monkeypatch):
    """Control KeyVault.get() without touching the real vault/env."""
    keys = {}

    def fake_get(service):
        return keys.get(service)

    monkeypatch.setattr(apollo_mod.KeyVault, "get", staticmethod(fake_get))
    return keys


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def wired(vault, srv, monkeypatch):
    vault["apollo"] = "apollo-key-abc"
    # APOLLO_BASE is "https://api.apollo.io/v1" in prod; keep the /v1 prefix so
    # the paths under test are the real ones.
    monkeypatch.setattr(apollo_mod, "APOLLO_BASE", srv.base + "/v1")
    e = ApolloEnricher()
    e._api_key = None
    return e, srv.rec


# ── availability / key handling ─────────────────────────────────────────────
def test_is_available_false_without_key(vault):
    e = ApolloEnricher()
    assert e.is_available() is False


def test_is_available_true_with_key(vault):
    vault["apollo"] = "k"
    assert ApolloEnricher().is_available() is True


def test_key_is_cached_after_first_lookup(vault, monkeypatch):
    calls = []

    def counting(service):
        calls.append(service)
        return "k" if service == "apollo" else None

    # monkeypatch, not a bare assignment: `KeyVault.get = ...` replaces the
    # classmethod for the whole session and leaks into every later test.
    monkeypatch.setattr(apollo_mod.KeyVault, "get", staticmethod(counting))
    e = ApolloEnricher()
    assert e._get_key() == "k"
    assert e._get_key() == "k"
    assert calls == ["apollo"], "key must be cached, not re-read every call"


def test_enrich_without_key_returns_error_and_no_data(vault):
    r = run(ApolloEnricher().enrich("Acme Roofing", "roofing"))
    assert r.error == "Apollo API key not configured"
    assert r.email is None and r.phone is None
    assert r.sources == []
    assert r.confidence == 0.0


# ── people search request building ──────────────────────────────────────────
def test_people_search_posts_to_the_right_path_with_key_and_keywords(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    run(e._mixed_people_search(keywords="Acme Roofing"))
    assert rec.count("POST") == 1
    body = rec.last_body("POST", "/v1/mixed_people/search")
    assert body["api_key"] == "apollo-key-abc"
    assert body["q_keywords"] == "Acme Roofing"
    assert body["page"] == 1
    assert body["per_page"] == 5
    assert "q_organization_names" not in body


def test_people_search_sends_organization_names_and_titles(wired):
    e, rec = wired
    e.config["person_titles"] = ["Owner", "President"]
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    run(e._mixed_people_search(keywords="k", organization_name="Acme Roofing"))
    body = rec.last_body("POST", "/v1/mixed_people/search")
    assert body["q_organization_names"] == ["Acme Roofing"]
    assert body["person_titles"] == ["Owner", "President"]


def test_people_search_honours_per_page_cap_on_results(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search",
            {"people": [{"id": str(i)} for i in range(9)]})
    got = run(e._mixed_people_search(keywords="k", per_page=3))
    assert [p["id"] for p in got] == ["0", "1", "2"]


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_people_search_swallows_http_errors_and_returns_empty(wired, status):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"error": "nope"}, status=status)
    assert run(e._mixed_people_search(keywords="k")) == []


def test_people_search_survives_malformed_json(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", raw="{not json", status=200)
    assert run(e._mixed_people_search(keywords="k")) == []


def test_people_search_survives_a_transport_failure(monkeypatch, vault):
    vault["apollo"] = "k"
    monkeypatch.setattr(apollo_mod, "APOLLO_BASE", "http://127.0.0.1:9")
    e = ApolloEnricher()
    e._api_key = None
    assert run(e._mixed_people_search(keywords="k")) == []


def test_people_search_without_key_never_hits_the_network(vault, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no request must be made without a key")

    monkeypatch.setattr(apollo_mod.httpx.AsyncClient, "post", boom)
    assert run(ApolloEnricher()._mixed_people_search(keywords="k")) == []


# ── org enrich request building ─────────────────────────────────────────────
def test_organization_enrich_posts_domain(wired):
    e, rec = wired
    rec.add("POST", "/v1/organizations/enrich",
            {"organization": {"primary_domain": "acme.com"}})
    out = run(e._organization_enrich("acme.com"))
    assert out == {"primary_domain": "acme.com"}
    body = rec.last_body("POST", "/v1/organizations/enrich")
    assert body == {"api_key": "apollo-key-abc", "domain": "acme.com"}


def test_organization_enrich_falls_back_to_whole_body(wired):
    e, rec = wired
    rec.add("POST", "/v1/organizations/enrich", {"primary_domain": "acme.com"})
    assert run(e._organization_enrich("acme.com")) == {"primary_domain": "acme.com"}


def test_organization_enrich_returns_none_on_404(wired):
    e, rec = wired
    rec.add("POST", "/v1/organizations/enrich", {"error": "not found"}, status=404)
    assert run(e._organization_enrich("acme.com")) is None


def test_organization_enrich_without_key_short_circuits(vault, monkeypatch):
    monkeypatch.setattr(apollo_mod.httpx.AsyncClient, "post",
                        lambda *a, **k: pytest.fail("no request expected"))
    assert run(ApolloEnricher()._organization_enrich("acme.com")) is None


# ── enrich(): full parse of a real-shaped payload ───────────────────────────
PEOPLE_PAYLOAD = {
    "people": [{
        "id": "p1",
        "first_name": "Dana",
        "last_name": "Moxley",
        "title": "Owner",
        "subtitle": "President",
        "email": "dana@acmeroofing.com",
        "phone_numbers": ["+1 (555) 010-1234"],
        "organization": {
            "name": "Acme Roofing",
            "primary_domain": "acmeroofing.com",
            "employee_count": "42",
            "annual_revenue_printed": "$5M-$10M",
        },
    }]
}


def test_enrich_maps_a_people_hit_onto_the_result(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", PEOPLE_PAYLOAD)
    r = run(e.enrich("Acme Roofing", "roofing", location="Austin, TX"))
    assert r.contact_name == "Dana Moxley"
    assert r.title == "Owner"
    assert r.email == "dana@acmeroofing.com"
    assert r.phone == "+1 (555) 010-1234"
    assert r.website == "acmeroofing.com"
    assert r.employee_count == 42
    assert r.revenue == "$5M-$10M"
    assert "apollo:people_search" in r.sources
    assert r.error is None
    assert r.raw_data["apollo_person"]["id"] == "p1"
    # 0.4 base + email + phone + website
    assert r.confidence == pytest.approx(1.0)


def test_enrich_builds_keywords_from_name_trade_and_location(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    run(e.enrich("Acme Roofing", "roofing", location="Austin, TX"))
    body = rec.last_body("POST", "/v1/mixed_people/search")
    assert body["q_keywords"] == "Acme Roofing roofing Austin, TX"
    assert body["q_organization_names"] == ["Acme Roofing"]


def test_enrich_title_falls_back_to_subtitle(wired):
    e, rec = wired
    p = dict(PEOPLE_PAYLOAD["people"][0])
    p.pop("title")
    rec.add("POST", "/v1/mixed_people/search", {"people": [p]})
    assert run(e.enrich("Acme", "roofing")).title == "President"


def test_enrich_derives_contact_name_from_org_when_person_has_no_name(wired):
    e, rec = wired
    p = dict(PEOPLE_PAYLOAD["people"][0])
    p["first_name"] = ""
    p["last_name"] = ""
    rec.add("POST", "/v1/mixed_people/search", {"people": [p]})
    assert run(e.enrich("Acme", "roofing")).contact_name == "Acme Roofing"


def test_enrich_formats_numeric_revenue_as_currency(wired):
    e, rec = wired
    p = dict(PEOPLE_PAYLOAD["people"][0])
    org = dict(p["organization"])
    org.pop("annual_revenue_printed")
    org["annual_revenue"] = 7500000
    p["organization"] = org
    rec.add("POST", "/v1/mixed_people/search", {"people": [p]})
    assert run(e.enrich("Acme", "roofing")).revenue == "$7,500,000"


def test_enrich_tolerates_unparsable_revenue_and_headcount(wired):
    e, rec = wired
    p = dict(PEOPLE_PAYLOAD["people"][0])
    p["organization"] = {"name": "Acme", "employee_count": "many",
                          "annual_revenue": "n/a"}
    rec.add("POST", "/v1/mixed_people/search", {"people": [p]})
    r = run(e.enrich("Acme", "roofing"))
    assert r.employee_count is None
    assert r.revenue is None
    assert r.email == "dana@acmeroofing.com"  # unrelated fields survive


def test_enrich_handles_person_with_no_phone_list(wired):
    e, rec = wired
    p = dict(PEOPLE_PAYLOAD["people"][0])
    p["phone_numbers"] = []
    rec.add("POST", "/v1/mixed_people/search", {"people": [p]})
    assert run(e.enrich("Acme", "roofing")).phone is None


def test_enrich_handles_empty_organization_block(wired):
    e, rec = wired
    p = dict(PEOPLE_PAYLOAD["people"][0])
    p["organization"] = {}
    rec.add("POST", "/v1/mixed_people/search", {"people": [p]})
    r = run(e.enrich("Acme", "roofing"))
    assert r.website is None and r.employee_count is None and r.revenue is None
    assert r.email == "dana@acmeroofing.com"


# ── CRITICAL: never fabricate contact data ──────────────────────────────────
def test_enrich_invents_nothing_when_apollo_returns_no_people(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    r = run(e.enrich("Acme Roofing", "roofing", website="https://acmeroofing.com"))
    assert r.email is None, r
    assert r.phone is None
    assert r.contact_name is None
    assert r.website is None, "no org_enrich route was served"
    assert r.error == "No results found in Apollo"
    assert r.confidence == 0.0
    assert r.sources == []


def test_enrich_invents_nothing_when_apollo_errors_401(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"error": "unauthorized"}, status=401)
    r = run(e.enrich("Acme Roofing", "roofing"))
    assert r.email is None and r.phone is None and r.contact_name is None
    assert r.error == "No results found in Apollo"
    assert r.confidence == 0.0


def test_apollo_never_pattern_generates_an_email_from_the_domain(wired):
    """A domain is not a mailbox. No info@ / contact@ / owner@ fabrication."""
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    rec.add("POST", "/v1/organizations/enrich", {"organization": {"name": "Acme"}})
    r = run(e.enrich("Acme Roofing", "roofing", website="https://acmeroofing.com"))
    assert r.email is None
    assert not (r.email or "").endswith("@acmeroofing.com")
    assert r.sources == ["apollo:org_enrich"]


# ── org enrich branch inside enrich() ───────────────────────────────────────
def test_enrich_falls_through_to_org_enrich_when_website_given(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    rec.add("POST", "/v1/organizations/enrich", {"organization": {
        "name": "Acme Roofing", "primary_domain": "acmeroofing.com",
        "employee_count": 12, "annual_revenue_printed": "$1M-$5M"}})
    r = run(e.enrich("Acme Roofing", "roofing", website="https://www.acmeroofing.com/"))
    assert rec.bodies("POST", "/v1/organizations/enrich")[0]["domain"] == "acmeroofing.com"
    assert r.website == "acmeroofing.com"
    assert r.employee_count == 12
    assert r.revenue == "$1M-$5M"
    assert r.sources == ["apollo:org_enrich"]


def test_enrich_org_enrich_keeps_supplied_website_when_domain_missing(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    rec.add("POST", "/v1/organizations/enrich", {"organization": {"name": "Acme"}})
    r = run(e.enrich("Acme", "roofing", website="https://acme.com"))
    assert r.website == "https://acme.com"


def test_enrich_skips_org_enrich_when_website_already_resolved(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", PEOPLE_PAYLOAD)
    run(e.enrich("Acme Roofing", "roofing", website="https://ignored.com"))
    assert rec.bodies("POST", "/v1/organizations/enrich") == []


def test_enrich_org_enrich_401_keeps_the_no_results_error(wired):
    e, rec = wired
    rec.add("POST", "/v1/mixed_people/search", {"people": []})
    rec.add("POST", "/v1/organizations/enrich", {"error": "x"}, status=401)
    r = run(e.enrich("Acme", "roofing", website="https://acme.com"))
    assert r.error == "No results found in Apollo"
    assert r.email is None
