"""Tests for engine/trades/platforms.py.

No internet. Two real, local transports are used:

  * The Exa-backed searchers are driven by a REAL ``ExaSearchProvider`` whose
    ``base_url`` points at a stdlib ``http.server`` on an ephemeral port, so
    request-building (query text, numResults, includeDomains), JSON parsing,
    HTTP-error handling and hit→TradeLead conversion all run end to end.
  * ``search_apollo`` hardcodes ``https://api.apollo.io/...`` and builds its
    own ``httpx.AsyncClient``. Rather than fake the client, we redirect
    ``httpx.AsyncHTTPTransport.handle_async_request`` at the transport layer,
    so the real client still builds and sends the real JSON body.

Every assertion is on observable behaviour of the code under test (returned
leads, request bodies the server actually received, return values on failure).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from engine.trades import platforms as P
from engine.trades.base import TradeLead


# Guard: a stale `leadgen-pro` copy of `engine` lives in site-packages. If it
# ever wins the import race these tests would be exercising a different build.
def test_tests_target_the_repository_copy_of_platforms():
    assert "home-improvement-lead-gen" in P.__file__, P.__file__


# ── local Exa server ───────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        state = type(self).state
        state["requests"].append({
            "path": self.path,
            "body": json.loads(raw or b"{}"),
            "headers": dict(self.headers),
        })
        payload = state["payload"] if state["status"] == 200 else {"error": "upstream boom"}
        body = json.dumps(payload).encode()
        self.send_response(state["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    _Handler_state = None


_Handler.state = {"requests": [], "payload": {"results": []}, "status": 200}


@pytest.fixture
def exa_server():
    _Handler.state = {"requests": [], "payload": {"results": []}, "status": 200}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Handler.state["base"] = f"http://127.0.0.1:{srv.server_port}"
    try:
        yield _Handler.state
    finally:
        srv.shutdown()
        srv.server_close()


def hit(title, url="http://x/1", text="snippet", **kw):
    d = {"title": title, "url": url, "text": text}
    d.update(kw)
    return d


@pytest.fixture
def exa(exa_server):
    """A real ExaSearchProvider pointed at the local server, installed globally."""
    from engine.search.exa import ExaSearchProvider

    provider = ExaSearchProvider(api_key="test-exa-key", base_url=exa_server["base"])
    P.set_exa_provider(provider)
    try:
        yield provider
    finally:
        P.set_exa_provider(None)


def run(coro):
    import asyncio

    return asyncio.run(coro)


def queries_sent(state):
    return [r["body"]["query"] for r in state["requests"]]


def header(req, name):
    """urllib capitalizes header names ('x-api-key' -> 'X-api-key')."""
    lowered = {k.lower(): v for k, v in req["headers"].items()}
    return lowered.get(name.lower())


# ── provider selection ─────────────────────────────────────────────────────
def test_get_provider_builds_real_exa_provider_when_none_installed(monkeypatch):
    """With no injected provider the searcher must construct one itself."""
    built = []

    class Fake:
        name = "exa"

        def __init__(self):
            built.append(self)

        async def search(self, query, **kw):
            from engine.search.base import SearchResult

            return SearchResult(query=query, hits=[], provider="exa")

    monkeypatch.setattr(P, "_exa_provider", None, raising=False)
    monkeypatch.setattr("engine.search.exa.ExaSearchProvider", Fake)
    assert run(P.search_houzz("roofing", "Austin")) == []
    assert len(built) == 1, "searcher did not construct an ExaSearchProvider"


def test_installed_provider_is_reused_across_searchers(exa, exa_server):
    run(P.search_houzz("roofing", "Austin"))
    run(P.search_instagram("roofing", "Austin"))
    assert len(exa_server["requests"]) == 2
    assert all(header(r, "x-api-key") == "test-exa-key" for r in exa_server["requests"])


# ── google_maps ────────────────────────────────────────────────────────────
def test_google_maps_sends_three_queries_and_no_domain_filter(exa, exa_server):
    exa_server["payload"] = {"results": []}
    assert run(P.search_google_maps("plumber", "Austin")) == []
    assert queries_sent(exa_server) == [
        "best plumber in Austin",
        "plumber near Austin",
        "top rated plumber Austin",
    ], "the 4th query is sliced off by queries[:3] and must not be sent"
    assert all("includeDomains" not in r["body"] for r in exa_server["requests"])


def test_google_maps_keeps_only_titles_naming_the_trade(exa, exa_server):
    exa_server["payload"] = {"results": [
        hit("Austin plumber services", "http://x/keep"),
        hit("Unrelated Bakery", "http://x/drop"),
    ]}
    leads = run(P.search_google_maps("plumber", "Austin"))
    assert [x.business_name for x in leads] == ["Austin plumber services"]


def test_google_maps_trade_match_is_case_insensitive(exa, exa_server):
    exa_server["payload"] = {"results": [hit("JOE'S PLUMBING & DRAIN", "http://x/1")]}
    leads = run(P.search_google_maps("plumbing", "Austin"))
    assert len(leads) == 1
    assert leads[0].business_name == "JOE'S PLUMBING & DRAIN"


def test_google_maps_ignores_hits_with_no_title(exa, exa_server):
    exa_server["payload"] = {"results": [hit("", "http://x/1")]}
    assert run(P.search_google_maps("plumber", "Austin")) == []


def test_google_maps_truncates_notes_to_300_chars(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Austin plumber", "http://x/1", text="z" * 900)]}
    lead = run(P.search_google_maps("plumber", "Austin"))[0]
    assert lead.notes == "z" * 300, len(lead.notes)


def test_google_maps_dedupes_same_url_across_queries(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Austin plumber", "http://x/dup")]}
    leads = run(P.search_google_maps("plumber", "Austin"))
    assert len(leads) == 1, f"same URL returned {len(leads)} times"


def test_google_maps_dedupes_on_title_when_url_missing(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Austin plumber", url="")]}
    leads = run(P.search_google_maps("plumber", "Austin"))
    assert len(leads) == 1
    assert leads[0].website == ""


def test_non_matching_hit_still_consumes_its_dedupe_slot(exa, exa_server):
    """The title filter runs after `seen.add`, so a rejected hit is not retried
    by the next query. Pinning this so a future reorder is a conscious change."""
    exa_server["payload"] = {"results": [
        hit("Bakery", "http://x/1"),
        hit("Plumbing Co", "http://x/1"),
    ]}
    assert run(P.search_google_maps("plumber", "Austin")) == []


# ── per-platform parsing ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "func,expected_source,title,expected_name,include_domain",
    [
        (P.search_homeadvisor, "homeadvisor", "Ace Plumbing - HomeAdvisor", "Ace Plumbing", "homeadvisor.com"),
        (P.search_yelp, "yelp", "Ace Plumbing - Yelp", "Ace Plumbing", "yelp.com"),
        (P.search_angi, "angi", "Ace Plumbing | Angi", "Ace Plumbing", "angi.com"),
        (P.search_facebook, "facebook", "Ace Plumbing Co", "Ace Plumbing Co", "facebook.com"),
        (P.search_nextdoor, "nextdoor", "Ace Plumbing Co", "Ace Plumbing Co", "nextdoor.com"),
        (P.search_instagram, "instagram", "Ace Plumbing Co", "Ace Plumbing Co", "instagram.com"),
        (P.search_houzz, "houzz", "Ace Plumbing Co", "Ace Plumbing Co", "houzz.com"),
        (P.search_zillow, "zillow", "5 Acre Lot - Zillow", "5 Acre Lot", "zillow.com"),
        (P.search_loopnet, "loopnet", "5 Acre Lot - LoopNet", "5 Acre Lot", "loopnet.com"),
        (P.search_landwatch, "landwatch", "5 Acre Lot - LandWatch", "5 Acre Lot", "landwatch.com"),
    ],
)
def test_platform_strips_its_own_brand_suffix(
    exa, exa_server, func, expected_source, title, expected_name, include_domain
):
    exa_server["payload"] = {"results": [hit(title, f"http://{include_domain}/1")]}
    leads = run(func("plumbing", "Austin"))
    assert len(leads) == 1
    lead = leads[0]
    assert lead.business_name == expected_name
    assert lead.source == expected_source
    assert lead.trade == "plumbing"
    assert lead.website == f"http://{include_domain}/1"
    assert all(r["body"]["includeDomains"] == [include_domain]
               for r in exa_server["requests"]), exa_server["requests"]


@pytest.mark.parametrize("suffix", [" | Zillow", " | LoopNet", " | LandWatch"])
def test_land_platforms_strip_pipe_variant(exa, exa_server, suffix):
    func = {" | Zillow": P.search_zillow,
            " | LoopNet": P.search_loopnet,
            " | LandWatch": P.search_landwatch}[suffix]
    exa_server["payload"] = {"results": [hit(f"17 Acre Parcel{suffix}", "http://x/1")]}
    leads = run(func("land_developer", "Austin"))
    assert leads[0].business_name == "17 Acre Parcel"


def test_angi_takes_text_before_first_pipe(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Ace Plumbing | Angi | Austin TX", "http://x/1")]}
    leads = run(P.search_angi("plumbing", "Austin"))
    assert leads[0].business_name == "Ace Plumbing"


def test_angi_without_pipe_keeps_whole_title(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Ace Plumbing", "http://x/1")]}
    assert run(P.search_angi("plumbing", "Austin"))[0].business_name == "Ace Plumbing"


# ── every searcher's own failure path ──────────────────────────────────────
_EXA_BACKED = [
    P.search_google_maps, P.search_homeadvisor, P.search_angi, P.search_yelp,
    P.search_facebook, P.search_nextdoor, P.search_instagram, P.search_houzz,
    P.search_linkedin, P.search_zillow, P.search_loopnet, P.search_landwatch,
]


@pytest.mark.parametrize("func", _EXA_BACKED, ids=lambda f: f.__name__)
def test_every_exa_searcher_swallows_an_upstream_exception(exa, exa_server, monkeypatch, func):
    """Each searcher wraps its loop in its own try/except and logs. This proves
    all 12 handlers are present and none re-raises to the caller."""
    async def boom(query, **kw):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(exa, "search", boom)
    assert run(func("plumbing", "Austin")) == []


@pytest.mark.parametrize("func", _EXA_BACKED, ids=lambda f: f.__name__)
def test_every_exa_searcher_logs_the_failure(exa, exa_server, monkeypatch, caplog, func):
    async def boom(query, **kw):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(exa, "search", boom)
    name = func.__name__.replace("search_", "")
    with caplog.at_level("WARNING", logger="engine.trades.platforms"):
        run(func("plumbing", "Austin"))
    assert any(f"{name} search error" in r.message for r in caplog.records), \
        f"{func.__name__} logged {[r.message for r in caplog.records]}"


@pytest.mark.parametrize("func", [P.search_instagram, P.search_houzz], ids=lambda f: f.__name__)
def test_single_query_platforms_dedupe_repeats_within_one_response(exa, exa_server, func):
    """Their lone query can still return the same URL twice."""
    exa_server["payload"] = {"results": [
        hit("Ace Plumbing", "http://x/dup"),
        hit("Ace Plumbing 2", "http://x/dup"),
    ]}
    assert len(run(func("plumbing", "Austin"))) == 1


# ── query counts per platform ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "func,expected",
    [
        (P.search_homeadvisor, 2),
        (P.search_angi, 2),
        (P.search_yelp, 2),
        (P.search_facebook, 2),
        (P.search_nextdoor, 2),
        (P.search_instagram, 1),
        (P.search_houzz, 1),
        (P.search_linkedin, 3),
        (P.search_zillow, 3),
        (P.search_loopnet, 3),
        (P.search_landwatch, 2),
    ],
)
def test_each_platform_issues_its_expected_number_of_queries(exa, exa_server, func, expected):
    exa_server["payload"] = {"results": []}
    run(func("plumbing", "Austin"))
    assert len(exa_server["requests"]) == expected, queries_sent(exa_server)


def test_single_query_platforms_actually_use_site_operator(exa, exa_server):
    exa_server["payload"] = {"results": []}
    run(P.search_houzz("kitchen_and_bath", "Denver"))
    assert queries_sent(exa_server) == ["site:houzz.com kitchen_and_bath Denver"]


def test_linkedin_uses_three_of_four_queries(exa, exa_server):
    exa_server["payload"] = {"results": []}
    run(P.search_linkedin("land_developer", "Austin"))
    assert queries_sent(exa_server) == [
        "site:linkedin.com/company land_developer Austin",
        "site:linkedin.com/in land_developer developer Austin",
        "site:linkedin.com/company land acquisition Austin",
    ]
    assert not any("real estate development" in q for q in queries_sent(exa_server))


def test_land_platforms_search_for_land_not_the_trade_slug(exa, exa_server):
    exa_server["payload"] = {"results": []}
    run(P.search_zillow("land_developer", "Austin"))
    sent = queries_sent(exa_server)
    assert sent == [
        "site:zillow.com land for sale Austin",
        "site:zillow.com lots for sale Austin",
        "site:zillow.com vacant land Austin",
    ], sent


# ── linkedin name cleanup ──────────────────────────────────────────────────
@pytest.mark.parametrize("suffix", [" | LinkedIn", " - LinkedIn", " |linkedin", " on LinkedIn"])
def test_linkedin_strips_every_documented_suffix(exa, exa_server, suffix):
    exa_server["payload"] = {"results": [hit(f"Acme Land{suffix}", "http://x/1")]}
    leads = run(P.search_linkedin("land_developer", "Austin"))
    assert leads[0].business_name == "Acme Land"


def test_linkedin_strips_repeated_suffixes_in_one_pass(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Acme | LinkedIn | LinkedIn", "http://x/1")]}
    leads = run(P.search_linkedin("land_developer", "Austin"))
    assert leads[0].business_name == "Acme"


# ── max_results propagation ────────────────────────────────────────────────
@pytest.mark.parametrize("max_results,expected", [(3, 3), (10, 10), (25, 10), (500, 10)])
def test_num_results_is_capped_at_ten(exa, exa_server, max_results, expected):
    exa_server["payload"] = {"results": []}
    run(P.search_yelp("plumbing", "Austin", max_results=max_results))
    assert all(r["body"]["numResults"] == expected for r in exa_server["requests"])


def test_default_max_results_is_ten_per_query(exa, exa_server):
    exa_server["payload"] = {"results": []}
    run(P.search_yelp("plumbing", "Austin"))
    assert {r["body"]["numResults"] for r in exa_server["requests"]} == {10}


# ── upstream failure handling ──────────────────────────────────────────────
def test_upstream_500_yields_no_leads_and_no_crash(exa, exa_server):
    exa_server["status"] = 500
    exa_server["payload"] = {"results": [hit("Austin plumber", "http://x/1")]}
    assert run(P.search_google_maps("plumber", "Austin")) == []


def test_empty_hits_field_yields_no_leads(exa, exa_server):
    exa_server["payload"] = {"results": []}
    assert run(P.search_google_maps("plumber", "Austin")) == []


def test_null_hits_attribute_is_tolerated(exa, exa_server):
    """Exa's SearchResult.hits can be None; `result.hits or []` must absorb it."""
    from engine.search.base import SearchResult

    class NullHits:
        async def search(self, query, **kw):
            return SearchResult(query=query, hits=None, provider="exa")

    P.set_exa_provider(NullHits())
    assert run(P.search_zillow("land_developer", "Austin")) == []


def test_searcher_exception_is_swallowed_and_other_queries_still_run(exa, exa_server, monkeypatch):
    """One bad query must not abort the whole platform sweep."""
    calls = {"n": 0}
    real = exa.search

    async def flaky(query, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("rate limited")
        return await real(query, **kw)

    exa_server["payload"] = {"results": [hit("Austin plumber", "http://x/1")]}
    monkeypatch.setattr(exa, "search", flaky)
    leads = run(P.search_zillow("land_developer", "Austin"))
    assert len(leads) == 1, "later queries should still produce leads"
    assert calls["n"] == 3


def test_searcher_exception_while_no_provider_key_returns_empty(exa, exa_server, monkeypatch):
    async def boom(query, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(exa, "search", boom)
    assert run(P.search_landwatch("land_developer", "Austin")) == []


def test_exa_without_api_key_returns_no_leads(exa_server, monkeypatch):
    from engine.search.exa import ExaSearchProvider

    P.set_exa_provider(ExaSearchProvider(api_key="", base_url=exa_server["base"]))
    assert run(P.search_houzz("roofing", "Austin")) == []


# ── search_apollo ──────────────────────────────────────────────────────────
@pytest.fixture
def apollo_server(monkeypatch):
    """Real httpx client, real JSON body — only the destination host is swapped."""
    state = {"requests": [], "payload": {"people": []}, "status": 200}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            state["requests"].append({
                "path": self.path,
                "body": json.loads(raw or b"{}"),
                "headers": dict(self.headers),
            })
            body = json.dumps(state["payload"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    state["base"] = base

    original = httpx.AsyncHTTPTransport.handle_async_request

    def reroute(self, request):
        if request.url.host.endswith("apollo.io"):
            request.url = httpx.URL(base + request.url.path)
        return original(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reroute)
    try:
        yield state
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def apollo_key(monkeypatch):
    from engine.key_vault import KeyVault

    monkeypatch.setattr(KeyVault, "get", staticmethod(lambda service: "apollo-key-123"))
    return "apollo-key-123"


def test_apollo_skips_entirely_when_no_key(apollo_server, monkeypatch):
    """No credential => no HTTP request at all, not a failed one."""
    from engine.key_vault import KeyVault

    monkeypatch.setattr(KeyVault, "get", staticmethod(lambda service: None))
    assert run(P.search_apollo("land_developer", "Austin")) == []
    assert apollo_server["requests"] == []


def test_apollo_posts_expected_request(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": []}
    run(P.search_apollo("land_developer", "Austin, TX", max_results=15))
    assert len(apollo_server["requests"]) == 1
    req = apollo_server["requests"][0]
    assert req["path"] == "/v1/mixed_people/search", req["path"]
    assert req["headers"]["Host"] == "api.apollo.io", req["headers"]["Host"]
    assert req["body"]["api_key"] == apollo_key
    assert req["body"]["q_keywords"] == "land_developer Austin, TX"
    assert req["body"]["per_page"] == 15
    assert req["body"]["page"] == 1
    assert req["body"]["organization_locations"] == ["Austin, TX"]
    assert "VP Land Acquisition" in req["body"]["person_titles"]


def test_apollo_uses_default_titles_for_other_trades(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": []}
    run(P.search_apollo("plumbing", "Austin"))
    titles = apollo_server["requests"][0]["body"]["person_titles"]
    assert titles == ["President", "CEO", "Owner", "VP Acquisitions", "Director of Development"]


def test_apollo_omits_location_filter_when_blank(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": []}
    run(P.search_apollo("land_developer", ""))
    assert "organization_locations" not in apollo_server["requests"][0]["body"]


def test_apollo_per_page_capped_at_25(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": []}
    run(P.search_apollo("land_developer", "Austin", max_results=500))
    assert apollo_server["requests"][0]["body"]["per_page"] == 25


def test_apollo_sends_no_cache_headers(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": []}
    run(P.search_apollo("land_developer", "Austin"))
    h = apollo_server["requests"][0]["headers"]
    assert h["Content-Type"] == "application/json"
    assert h["Cache-Control"] == "no-cache"


def test_apollo_parses_org_name_as_business_name(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": [{
        "first_name": "Ada", "last_name": "Lovelace",
        "organization": {"name": "Acme Land Co", "primary_domain": "acme.com"},
        "title": "VP Land Acquisition", "email": "ada@acme.com",
        "phone_numbers": ["555-0100"],
    }]}
    lead = run(P.search_apollo("land_developer", "Austin"))[0]
    assert lead.business_name == "Acme Land Co"
    assert lead.website == "acme.com"
    assert lead.email == "ada@acme.com"
    assert lead.phone == "555-0100"
    assert lead.notes == "VP Land Acquisition at Acme Land Co"
    assert lead.source == "apollo"
    assert lead.trade == "land_developer"


def test_apollo_falls_back_to_person_name_without_org(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": [
        {"first_name": "Bob", "last_name": "Builder", "organization": None},
    ]}
    lead = run(P.search_apollo("land_developer", "Austin"))[0]
    assert lead.business_name == "Bob Builder"
    assert lead.website == ""
    assert lead.notes == "N/A at N/A"


def test_apollo_falls_back_to_website_url_when_no_primary_domain(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": [{
        "first_name": "Cal", "last_name": "C",
        "organization": {"name": "Cal Co", "website_url": "https://cal.example"},
    }]}
    assert run(P.search_apollo("land_developer", "Austin"))[0].website == "https://cal.example"


def test_apollo_skips_half_named_person_in_name_fallback(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": [
        {"first_name": "Solo", "last_name": "", "organization": {}},
    ]}
    assert run(P.search_apollo("land_developer", "Austin"))[0].business_name == "Solo"


def test_apollo_dedupes_by_resolved_name(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": [
        {"first_name": "Ada", "last_name": "L", "organization": {"name": "Acme"}},
        {"first_name": "Other", "last_name": "X", "organization": {"name": "Acme"}},
    ]}
    leads = run(P.search_apollo("land_developer", "Austin"))
    assert len(leads) == 1 and leads[0].business_name == "Acme"


def test_apollo_blank_email_and_phone_become_empty_strings(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": [
        {"first_name": "Dee", "last_name": "D", "organization": {"name": "Dee Co"},
         "email": None, "phone_numbers": []},
    ]}
    lead = run(P.search_apollo("land_developer", "Austin"))[0]
    assert lead.email == ""
    assert lead.phone == ""


def test_apollo_object_phone_entries_are_stored_verbatim(apollo_server, apollo_key):
    """Apollo's real payload uses [{'raw_number': ...}] objects and the code
    indexes [0] without unwrapping, so lead.phone becomes a dict. Real defect,
    pinned here so the fix is deliberate rather than silent."""
    apollo_server["payload"] = {"people": [{
        "first_name": "Eve", "last_name": "E", "organization": {"name": "Eve Co"},
        "phone_numbers": [{"raw_number": "+15550100"}],
    }]}
    lead = run(P.search_apollo("land_developer", "Austin"))[0]
    assert lead.phone == {"raw_number": "+15550100"}


def test_apollo_ignores_missing_people_key(apollo_server, apollo_key):
    apollo_server["payload"] = {"error": "quota exceeded"}
    assert run(P.search_apollo("land_developer", "Austin")) == []


def test_apollo_empty_people_list(apollo_server, apollo_key):
    apollo_server["payload"] = {"people": []}
    assert run(P.search_apollo("land_developer", "Austin")) == []


def test_apollo_http_401_is_swallowed_and_returns_no_leads(apollo_server, apollo_key):
    apollo_server["status"] = 401
    apollo_server["payload"] = {"people": [
        {"first_name": "Ada", "last_name": "L", "organization": {"name": "Acme"}},
    ]}
    assert run(P.search_apollo("land_developer", "Austin")) == []


def test_apollo_connection_failure_is_swallowed(monkeypatch, apollo_key):
    async def boom(self, *a, **kw):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", boom)
    assert run(P.search_apollo("land_developer", "Austin")) == []


def test_apollo_invalid_json_is_swallowed(apollo_server, apollo_key, monkeypatch):
    class BadJSON:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    async def handler(self, request):
        return httpx.Response(200, text="<html>not json</html>")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handler)
    assert run(P.search_apollo("land_developer", "Austin")) == []


# ── registry ───────────────────────────────────────────────────────────────
def test_every_searcher_in_the_registry_is_callable_with_the_documented_signature():
    """discovery.py calls searcher(trade, location, max_per_platform)."""
    import inspect

    for slug, fn in P.PLATFORM_SEARCHERS.items():
        params = list(inspect.signature(fn).parameters)
        assert params == ["trade", "location", "max_results"], (slug, params)
        assert inspect.iscoroutinefunction(fn), slug


def test_registry_has_no_duplicate_searchers():
    fns = list(P.PLATFORM_SEARCHERS.values())
    assert len(fns) == len(set(fns))


@pytest.mark.parametrize("slug", [
    "google_maps", "homeadvisor", "angi", "yelp", "facebook", "nextdoor",
    "instagram", "houzz", "linkedin", "apollo", "zillow", "loopnet", "landwatch",
])
def test_registry_covers_every_documented_platform(slug):
    assert slug in P.PLATFORM_SEARCHERS


def test_set_exa_provider_overwrites_previous_provider():
    class A:
        pass

    class B:
        pass

    try:
        P.set_exa_provider(A())
        assert isinstance(P._get_provider(), A)
        P.set_exa_provider(B())
        assert isinstance(P._get_provider(), B)
    finally:
        P.set_exa_provider(None)


def test_returned_objects_are_trade_leads(exa, exa_server):
    exa_server["payload"] = {"results": [hit("Austin plumber", "http://x/1")]}
    lead = run(P.search_google_maps("plumber", "Austin"))[0]
    assert isinstance(lead, TradeLead)
    assert lead.status == "new"
    assert lead.converted is False
    assert lead.platforms_found == ["google_maps"]
