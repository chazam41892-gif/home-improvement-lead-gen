"""Tests for the live HTTP scrapers in engine/discovery.py (audit 2026-09-27).

discovery.py hardcodes its upstream hosts (google.com, reddit.com, api.github.com,
api.exa.ai, api.tavily.com) and talks aiohttp, so the network seam is faked at the
ClientSession level rather than with a live server: `_Recorder.handler()` returns a
stand-in session that records every (method, url, kwargs) and answers from a route
table of real response objects. Everything downstream of the fake — URL building,
query encoding, status branching, JSON parsing, BeautifulSoup extraction, the
per-query sleep cadence — is the production code path.

The inter-request `asyncio.sleep(1.5)` calls are collapsed to `asyncio.sleep(0)` by
`fast_sleep` so the suite is quick while keeping the real await points intact.
"""
import asyncio

import pytest

import engine.discovery as disc
from engine.discovery import (
    scrape_craigslist,
    scrape_exa,
    scrape_github,
    scrape_google_maps,
    scrape_reddit,
    scrape_tavily,
    scrape_url,
)


# ── aiohttp stand-in ───────────────────────────────────────────────────────
class _Resp:
    """The slice of aiohttp's response API that discovery.py actually uses."""

    def __init__(self, status=200, body="", payload=None):
        self.status = status
        self._body = body
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._body

    async def json(self, content_type=None):
        if self._payload is None:
            raise ValueError("response has no JSON body")
        return self._payload


class _Recorder:
    """Route table + request log for a fake aiohttp.ClientSession."""

    def __init__(self, routes=None, default=None):
        self.routes = routes or {}
        self.default = default if default is not None else _Resp(404, "no route")
        self.session_headers = {}
        self.requests = []

    def handler(self):
        rec = self

        class _Session:
            def __init__(self, headers=None, **kw):
                rec.session_headers = dict(headers or {})

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def _build(self, method, url, kwargs):
                rec.requests.append((method, url, kwargs))
                for frag, resp in rec.routes.items():
                    if frag in url:
                        return resp() if callable(resp) else resp
                return rec.default

            def get(self, url, **kw):
                return self._build("GET", url, kw)

            def post(self, url, **kw):
                return self._build("POST", url, kw)

        return _Session

    def urls(self, method=None):
        return [u for m, u, _ in self.requests if method is None or m == method]

    def payload_for(self, frag):
        """The json= body of the first request whose URL contains `frag`."""
        for _, url, kw in self.requests:
            if frag in url:
                return kw.get("json")
        raise AssertionError(f"no request matched {frag!r}; saw {self.urls()}")


@pytest.fixture
def rec():
    return _Recorder()


@pytest.fixture
def fake_aiohttp(monkeypatch, rec):
    """Point aiohttp.ClientSession at the recorder and zero out the sleep cadence."""
    monkeypatch.setattr(disc.aiohttp, "ClientSession", rec.handler())
    real_sleep = asyncio.sleep

    async def _instant(_delay, *a, **k):
        return await real_sleep(0, *a, **k)

    monkeypatch.setattr(asyncio, "sleep", _instant)
    return rec


#: Comfortably past discovery.py's 200-char "this is a JS shell, not leads" guard.
LONG_HTML = (
    "<html><head><title>Roofing Contractors</title></head><body>"
    "<h1>Roofing contractors in Austin TX</h1>"
    "<div class='bio'>Trusted roofers since 1998, free estimates, licensed and insured. "
    "We handle replacements, repairs, storm damage and gutter work across the metro area, "
    "and we offer financing on every job over five thousand dollars.</div>"
    "<p>Call now for a quote. Free inspections, same-day estimates, and a five year "
    "workmanship guarantee on every roof we install in Travis and Williamson counties.</p>"
    "</body></html>"
)


# ── Google Maps ────────────────────────────────────────────────────────────
async def test_google_maps_keeps_a_server_rendered_page(fake_aiohttp):
    fake_aiohttp.routes["/maps/search/"] = _Resp(200, LONG_HTML)
    out = await scrape_google_maps(["roofing Austin"])
    assert len(out) == 1, out
    assert out[0].source == "google_maps"
    assert "Trusted roofers" in out[0].text
    assert out[0].url.startswith("https://www.google.com/maps/search/roofing%20Austin")
    assert out[0].metadata == {"query": "roofing Austin"}


async def test_google_maps_encodes_the_query_in_the_path(fake_aiohttp):
    fake_aiohttp.routes["/maps/search/"] = _Resp(200, LONG_HTML)
    await scrape_google_maps(["roof & gutter repair"])
    assert "roof%20%26%20gutter%20repair" in fake_aiohttp.urls()[0], fake_aiohttp.urls()


async def test_google_maps_skips_non_200_without_raising(fake_aiohttp):
    fake_aiohttp.routes["/maps/search/"] = _Resp(429, "rate limited")
    assert await scrape_google_maps(["roofing Austin"]) == []
    assert len(fake_aiohttp.requests) == 1


async def test_google_maps_survives_a_transport_exception(fake_aiohttp, monkeypatch):
    class _Bad:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        def get(self, *a, **k):
            raise OSError("DNS failure")

    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Bad)
    assert await scrape_google_maps(["roofing Austin"]) == []


async def test_google_maps_without_bs4_returns_empty(fake_aiohttp, monkeypatch):
    monkeypatch.setattr(disc, "_BS4", False)
    assert await scrape_google_maps(["roofing Austin"]) == []
    assert fake_aiohttp.requests == [], "no HTTP at all when the parser is missing"


async def test_google_maps_caps_queries_at_five(fake_aiohttp):
    fake_aiohttp.routes["/maps/search/"] = _Resp(200, LONG_HTML)
    await scrape_google_maps([f"q{i}" for i in range(9)])
    assert len(fake_aiohttp.requests) == 5, fake_aiohttp.urls()


# ── Reddit ─────────────────────────────────────────────────────────────────
REDDIT_OK = {
    "data": {"children": [
        {"data": {"title": "Need a roofer badly, leak in the ceiling",
                  "selftext": "Water stain spreading across the drywall every storm.",
                  "permalink": "/r/HomeImprovement/comments/abc123/"}},
        {"data": {"title": "short", "selftext": "", "permalink": "/x"}},
    ]}
}


async def test_reddit_extracts_posts_with_substantial_text(fake_aiohttp):
    fake_aiohttp.routes["/search.json"] = _Resp(200, "", REDDIT_OK)
    out = await scrape_reddit(["roofer"], subreddits=["HomeImprovement"])
    assert len(out) == 1, out
    assert out[0].source == "reddit"
    assert "Need a roofer badly" in out[0].text
    assert out[0].url == "https://reddit.com/r/HomeImprovement/comments/abc123/"
    assert out[0].metadata == {"subreddit": "HomeImprovement", "query": "roofer"}


async def test_reddit_uses_an_identifiable_user_agent(fake_aiohttp):
    """Reddit 403s browser-spoofing UAs; the scraper must announce itself."""
    fake_aiohttp.routes["/search.json"] = _Resp(200, "", REDDIT_OK)
    await scrape_reddit(["roofer"], subreddits=["DIY"])
    ua = fake_aiohttp.session_headers["User-Agent"]
    assert ua == "linux:leadgen.discovery:v1.0 (by /u/leviathan)", ua


async def test_reddit_403_records_a_block_error_instead_of_a_silent_empty(fake_aiohttp):
    """AUDIT 2026-09-27: 'blocked' and 'no matching posts' must not look identical."""
    fake_aiohttp.routes["/search.json"] = _Resp(403, "Blocked")
    disc.last_reddit_error = ""
    out = await scrape_reddit(["roofer"], subreddits=["DIY"])
    assert out == []
    assert "403" in disc.last_reddit_error and "datacenter" in disc.last_reddit_error


async def test_reddit_stops_immediately_on_403(fake_aiohttp):
    fake_aiohttp.routes["/search.json"] = _Resp(403, "Blocked")
    disc.last_reddit_error = ""
    await scrape_reddit(["a", "b", "c"], subreddits=["DIY", "Roofing"])
    assert len(fake_aiohttp.requests) == 1, "403 must abort, not hammer the API"


async def test_reddit_ignores_other_non_200_statuses(fake_aiohttp):
    fake_aiohttp.routes["/search.json"] = _Resp(502, "bad gateway")
    disc.last_reddit_error = ""
    assert await scrape_reddit(["a"], subreddits=["DIY"]) == []
    assert disc.last_reddit_error == "", "a 5xx is not a block"


async def test_reddit_clears_a_stale_block_error_on_a_healthy_run(fake_aiohttp):
    fake_aiohttp.routes["/search.json"] = _Resp(200, "", REDDIT_OK)
    disc.last_reddit_error = "HTTP 403 Blocked (stale)"
    await scrape_reddit(["roofer"], subreddits=["DIY"])
    assert disc.last_reddit_error == ""


async def test_reddit_limits_to_five_subs_and_three_queries(fake_aiohttp):
    fake_aiohttp.routes["/search.json"] = _Resp(200, "", REDDIT_OK)
    await scrape_reddit([f"q{i}" for i in range(6)], subreddits=[f"s{i}" for i in range(8)])
    assert len(fake_aiohttp.requests) == 15, len(fake_aiohttp.requests)


async def test_reddit_uses_the_default_subreddit_list(fake_aiohttp):
    fake_aiohttp.routes["/search.json"] = _Resp(200, "", REDDIT_OK)
    await scrape_reddit(["roofer"], subreddits=None)
    urls = fake_aiohttp.urls()
    # _SUBREDDITS is sliced to its first 5; one query each => 5 requests.
    assert len(urls) == 5, urls
    assert "/r/HomeImprovement/search.json" in urls[0], urls[0]
    assert "/r/Entrepreneur/search.json" in urls[-1], urls[-1]


# ── GitHub ─────────────────────────────────────────────────────────────────
GH_USERS = {"items": [{"login": "octocat"}]}
GH_USER_DETAIL = {"login": "octocat", "name": "Mona Lisa Octocat", "company": "GitHub",
                  "email": "mona@github.com", "location": "SF", "bio": "hi",
                  "hireable": True, "blog": "https://example.test",
                  "public_repos": 12, "html_url": "https://github.com/octocat"}
GH_REPOS = {"items": [{"full_name": "octocat/hello", "description": "d",
                       "owner": {"login": "octocat"}, "topics": ["a", "b"],
                       "stargazers_count": 9,
                       "html_url": "https://github.com/octocat/hello"}]}


async def test_github_collects_user_and_repo_leads(fake_aiohttp):
    fake_aiohttp.routes["/search/users"] = _Resp(200, "", GH_USERS)
    fake_aiohttp.routes["/users/octocat"] = _Resp(200, "", GH_USER_DETAIL)
    fake_aiohttp.routes["/search/repositories"] = _Resp(200, "", GH_REPOS)
    out = await scrape_github(["roofing"])
    by_source = {}
    for r in out:
        by_source.setdefault(r.url, r)
    user = next(r for r in out if r.url == "https://github.com/octocat")
    assert "Mona Lisa Octocat" in user.text
    assert "GitHub" in user.text and "octocat" in user.metadata["username"]
    repo = next(r for r in out if r.url == "https://github.com/octocat/hello")
    assert "octocat/hello" in repo.text
    assert repo.metadata == {"repo": "octocat/hello", "query": "roofing"}


async def test_github_sends_a_token_header_when_keyed(fake_aiohttp):
    fake_aiohttp.routes["/search/users"] = _Resp(200, "", {"items": []})
    fake_aiohttp.routes["/search/repositories"] = _Resp(200, "", {"items": []})
    await scrape_github(["roofing"], api_key="ghp_secret")
    assert fake_aiohttp.session_headers["Authorization"] == "token ghp_secret"
    assert fake_aiohttp.session_headers["Accept"] == "application/vnd.github.v3+json"


async def test_github_sends_no_authorization_header_when_unkeyed(fake_aiohttp, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    fake_aiohttp.routes["/search/users"] = _Resp(200, "", {"items": []})
    fake_aiohttp.routes["/search/repositories"] = _Resp(200, "", {"items": []})
    await scrape_github(["roofing"])
    assert "Authorization" not in fake_aiohttp.session_headers


async def test_github_falls_back_to_the_login_url_and_name_when_html_url_missing(fake_aiohttp):
    detail = dict(GH_USER_DETAIL)
    detail.pop("html_url")
    detail["name"] = None  # GitHub leaves this null for accounts with no display name
    fake_aiohttp.routes["/search/users"] = _Resp(200, "", GH_USERS)
    fake_aiohttp.routes["/users/octocat"] = _Resp(200, "", detail)
    fake_aiohttp.routes["/search/repositories"] = _Resp(404, "gone")
    out = await scrape_github(["roofing"])
    assert out[0].url == "https://github.com/octocat"
    assert "GitHub User: octocat" in out[0].text


async def test_github_skips_a_user_whose_detail_fetch_fails(fake_aiohttp):
    fake_aiohttp.routes["/search/users"] = _Resp(200, "", GH_USERS)
    fake_aiohttp.routes["/users/octocat"] = _Resp(401, "rate limited")
    fake_aiohttp.routes["/search/repositories"] = _Resp(404, "gone")
    assert await scrape_github(["roofing"]) == []


async def test_github_survives_a_per_query_exception(fake_aiohttp, monkeypatch):
    class _Bad:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        def get(self, *a, **k):
            raise OSError("connection reset")

    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Bad)
    assert await scrape_github(["roofing", "plumbing"]) == []


# ── Craigslist ─────────────────────────────────────────────────────────────
CL_HTML = (
    "<html><body>"
    "<div class='cl-static-search-result'><a href='https://eugene.craigslist.org/BBB/x1'>"
    "<span class='title'>Need roofing repair</span></a></div>"
    "<div class='cl-static-search-result'><a href='https://eugene.craigslist.org/BBB/x2'>"
    "<span class='title'>Need a plumber</span></a></div>"
    "<div class='cl-static-search-result'><a href='https://eugene.craigslist.org/BBB/x3'>"
    "<span class='title'></span></a></div>"
    "</body></html>"
)


async def test_craigslist_extracts_titled_results(fake_aiohttp):
    fake_aiohttp.routes["/search/bbb"] = _Resp(200, CL_HTML)
    out = await scrape_craigslist(["need roofing"], cities=["eugene"])
    titles = [r.text for r in out]
    assert titles == ["Need roofing repair", "Need a plumber"], titles
    assert out[0].url == "https://eugene.craigslist.org/BBB/x1"
    assert out[0].metadata == {"city": "eugene", "query": "need roofing"}


async def test_craigslist_builds_a_city_scoped_bbb_url(fake_aiohttp):
    fake_aiohttp.routes["/search/bbb"] = _Resp(200, CL_HTML)
    await scrape_craigslist(["need roofing"], cities=["portland"])
    assert fake_aiohttp.urls()[0].startswith("https://portland.craigslist.org/search/bbb?query=need%20roofing")


async def test_craigslist_ignores_a_result_with_no_title(fake_aiohttp):
    fake_aiohttp.routes["/search/bbb"] = _Resp(200, CL_HTML)
    out = await scrape_craigslist(["x"])
    assert all(r.text for r in out)


async def test_craigslist_without_bs4_returns_empty(fake_aiohttp, monkeypatch):
    monkeypatch.setattr(disc, "_BS4", False)
    assert await scrape_craigslist(["need roofing"], cities=["eugene"]) == []
    assert fake_aiohttp.requests == []


async def test_craigslist_defaults_to_two_cities(fake_aiohttp):
    fake_aiohttp.routes["/search/bbb"] = _Resp(200, CL_HTML)
    await scrape_craigslist(["x"], cities=None)
    assert "eugene.craigslist.org" in fake_aiohttp.urls()[0]
    assert "portland.craigslist.org" in fake_aiohttp.urls()[-1]


async def test_craigslist_caps_queries_at_three(fake_aiohttp):
    fake_aiohttp.routes["/search/bbb"] = _Resp(200, CL_HTML)
    await scrape_craigslist([f"q{i}" for i in range(6)], cities=["eugene"])
    assert len(fake_aiohttp.requests) == 3


# ── Exa ────────────────────────────────────────────────────────────────────
EXA_OK = {"results": [{"title": "Roofing Co", "text": "We fix roofs in Austin",
                       "url": "https://roofingco.test"}, {"title": "x", "text": ""}]}


async def test_exa_collects_results_over_thirty_chars(fake_aiohttp):
    fake_aiohttp.routes["/search"] = _Resp(200, "", EXA_OK)
    out = await scrape_exa(["roofing"], api_key="exa-key")
    assert len(out) == 1, out
    assert out[0].source == "exa"
    assert out[0].url == "https://roofingco.test"
    assert out[0].metadata == {"query": "roofing", "ai_agent": "exa"}


async def test_exa_sends_the_key_and_payload(fake_aiohttp):
    fake_aiohttp.routes["/search"] = _Resp(200, "", EXA_OK)
    await scrape_exa(["roofing"], api_key="exa-key")
    method, url, kw = fake_aiohttp.requests[0]
    assert method == "POST" and url == "https://api.exa.ai/search"
    assert kw["headers"]["x-api-key"] == "exa-key"
    assert fake_aiohttp.payload_for("api.exa.ai") == {
        "query": "roofing", "numResults": 5, "type": "auto"}


async def test_exa_strips_surrounding_quotes_from_the_env_key(fake_aiohttp, monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", '"quoted-key"')
    fake_aiohttp.routes["/search"] = _Resp(200, "", EXA_OK)
    await scrape_exa(["roofing"])
    assert fake_aiohttp.requests[0][2]["headers"]["x-api-key"] == "quoted-key"


async def test_exa_without_a_key_makes_no_request(fake_aiohttp, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    assert await scrape_exa(["roofing"], api_key="") == []
    assert fake_aiohttp.requests == []


async def test_exa_falls_back_to_the_highlight_field(fake_aiohttp):
    fake_aiohttp.routes["/search"] = _Resp(200, "", {
        "results": [{"title": "Roofing Co summary",
                     "highlight": "highlighted summary text", "url": "u"}]})
    out = await scrape_exa(["roofing"], api_key="k")
    assert len(out) == 1, out
    assert "highlighted summary text" in out[0].text


async def test_exa_survives_a_failed_request(fake_aiohttp, monkeypatch):
    class _Bad:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        def post(self, *a, **k):
            raise OSError("connection reset")

    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Bad)
    assert await scrape_exa(["roofing"], api_key="k") == []


# ── Tavily ─────────────────────────────────────────────────────────────────
TAVILY_OK = {"results": [{"title": "Roofing Co", "content": "We fix roofs in Austin",
                          "url": "https://roofingco.test"}]}


async def test_tavily_collects_results(fake_aiohttp):
    fake_aiohttp.routes["/search"] = _Resp(200, "", TAVILY_OK)
    out = await scrape_tavily(["roofing"], api_key="tvly-key")
    assert len(out) == 1
    assert out[0].source == "tavily"
    assert out[0].metadata == {"query": "roofing", "ai_agent": "tavily"}


async def test_tavily_sends_the_key_in_the_payload_not_a_header(fake_aiohttp):
    fake_aiohttp.routes["/search"] = _Resp(200, "", TAVILY_OK)
    await scrape_tavily(["roofing"], api_key="tvly-key")
    method, url, _ = fake_aiohttp.requests[0]
    assert method == "POST" and url == "https://api.tavily.com/search"
    assert fake_aiohttp.payload_for("tavily.com") == {
        "api_key": "tvly-key", "query": "roofing", "max_results": 5}


async def test_tavily_without_a_key_makes_no_request(fake_aiohttp, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert await scrape_tavily(["roofing"], api_key="") == []
    assert fake_aiohttp.requests == []


async def test_tavily_skips_thin_results(fake_aiohttp):
    fake_aiohttp.routes["/search"] = _Resp(200, "", {"results": [{"title": "T", "content": ""}]})
    assert await scrape_tavily(["roofing"], api_key="k") == []


# ── single URL ─────────────────────────────────────────────────────────────
async def test_scrape_url_strips_script_nav_and_footer(fake_aiohttp):
    html = ("<html><head><script>var secret=1;</script><style>.a{}</style></head>"
            "<body><nav>NAVIGATION</nav><main>Roofing Co repairs roofs in Austin</main>"
            "<footer>FOOTER TEXT</footer><script>more()</script></body></html>")
    fake_aiohttp.routes["roofingco.test"] = _Resp(200, html)
    out = await scrape_url("https://roofingco.test")
    assert out is not None
    assert out.source == "web"
    assert out.url == "https://roofingco.test"
    assert "Roofing Co repairs roofs in Austin" in out.text
    assert "var secret" not in out.text
    assert "NAVIGATION" not in out.text
    assert "FOOTER TEXT" not in out.text


async def test_scrape_url_truncates_at_8000_chars(fake_aiohttp):
    fake_aiohttp.routes["big.test"] = _Resp(200, "x" * 50000)
    out = await scrape_url("https://big.test")
    assert len(out.text) == 8000, len(out.text)


async def test_scrape_url_returns_none_when_the_fetch_raises(fake_aiohttp, monkeypatch):
    class _Bad:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        def get(self, *a, **k):
            raise OSError("unreachable host")

    monkeypatch.setattr(disc.aiohttp, "ClientSession", _Bad)
    assert await scrape_url("https://nope.test") is None


async def test_scrape_url_without_bs4_returns_none(fake_aiohttp, monkeypatch):
    monkeypatch.setattr(disc, "_BS4", False)
    assert await scrape_url("https://roofingco.test") is None
