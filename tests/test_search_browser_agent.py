"""Tests for engine/search/browser_agent.py.

BrowserSearchProvider crawls DuckDuckGo HTML then each result site. DuckDuckGo's
URL is hard-coded, so tests wrap _fetch_url to retarget only that host at a
local server; the result-site crawls go straight there. All BeautifulSoup
parsing, uddg-unwrap, dedup, intent scoring, directory filtering, throttle
semaphore and the secondary contact-page crawl run for real.
"""
import asyncio

import pytest

from engine.search.base import SearchHit
from engine.search.browser_agent import BrowserSearchProvider
from tests.support_fixtures import no_real_network  # noqa: F401
from tests.support_http import LocalServer, closed_port

DDG = "https://html.duckduckgo.com/html/"


def run(coro):
    return asyncio.run(coro)


def ddg_page(*entries: str) -> str:
    """Build a DuckDuckGo-shaped result page."""
    return "<html><body>" + "".join(entries) + "</body></html>"


def result(url: str, title: str, snippet: str = "") -> str:
    return (f'<div class="result">'
            f'<a class="result__url" href="{url}">{title}</a>'
            f'<a class="result__snippet">{snippet}</a>'
            f'</div>')


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def ba():
    b = BrowserSearchProvider()
    b.playwright_available = False  # deterministic httpx path
    return b


@pytest.fixture
def wired(ba, srv):
    """Retarget only the hard-coded DDG host at the local server."""
    real = ba._fetch_url

    async def patched(url, params=None):
        if url.startswith(DDG):
            url = srv.url("/ddg")
        return await real(url, params=params)

    ba._fetch_url = patched
    return ba, srv.rec


# ── construction ────────────────────────────────────────────────────────────
def test_provider_needs_no_api_key():
    b = BrowserSearchProvider()
    assert b.name == "browser"
    assert b.is_available() if hasattr(b, "is_available") else True
    assert b.api_key is None
    assert isinstance(b.playwright_available, bool)


# ── DuckDuckGo result parsing ───────────────────────────────────────────────
def test_search_sends_the_query_to_duckduckgo(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page())
    run(ba.search("roofers Austin"))
    assert rec.query_of("/ddg") == {"q": ["roofers Austin"]}


def test_search_parses_title_url_and_snippet(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        result("https://acmeroofing.com/", "Acme Roofing", "Roofing in Austin")))
    r = run(ba.search("roofers Austin"))
    assert r.provider == "browser"
    assert r.total_results == 1
    assert len(r.hits) == 1
    assert r.hits[0].url == "https://acmeroofing.com/"
    assert r.hits[0].extras["high_intent"] == 0
    # the crawl of a real host fails cleanly -> no "crawled" flag, hit survives
    assert "crawled" not in r.hits[0].extras


def test_uddg_redirect_is_unwrapped_protocol_relative(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(result(
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Facmeroofing.com%2F", "Acme")))
    r = run(ba.search("q"))
    assert r.hits[0].url == "https://acmeroofing.com/"


def test_uddg_redirect_is_unwrapped_relative(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(result(
        "/l/?uddg=https%3A%2F%2Facmeroofing.com%2F", "Acme")))
    r = run(ba.search("q"))
    assert r.hits[0].url == "https://acmeroofing.com/"


def test_plain_urls_pass_through_untouched(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(result("https://acme.com/", "Acme")))
    assert run(ba.search("q")).hits[0].url == "https://acme.com/"


def test_duplicate_urls_are_collapsed(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        result("https://acme.com/", "Acme"),
        result("https://acme.com/", "Acme again"),
        result("https://other.com/", "Other")))
    r = run(ba.search("q"))
    assert [h.url for h in r.hits] == ["https://acme.com/", "https://other.com/"]


def test_yjs_ad_redirects_are_skipped(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        result("https://duckduckgo.com/y.js?ad=1", "Ad"),
        result("https://acme.com/", "Acme")))
    r = run(ba.search("q"))
    assert [h.url for h in r.hits] == ["https://acme.com/"]


def test_results_missing_a_link_or_title_are_skipped(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        '<div class="result"><span>no link</span></div>',
        '<div class="result"><a class="result__url" href="https://x.com/"></a></div>',
        result("https://acme.com/", "Acme")))
    r = run(ba.search("q"))
    assert [h.url for h in r.hits] == ["https://acme.com/"]


def test_num_results_caps_the_hit_list(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        *[result(f"https://s{i}.com/", f"S{i}") for i in range(10)]))
    r = run(ba.search("q", num_results=3))
    assert len(r.hits) == 3


def test_empty_ddg_response_yields_zero_hits_not_an_error(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page())
    r = run(ba.search("q"))
    assert r.hits == [] and r.error is None and r.total_results == 0


def test_unreachable_ddg_yields_zero_hits_not_an_exception(ba):
    async def fail(url, params=None):
        return None
    ba._fetch_url = fail
    r = run(ba.search("roofers"))
    assert r.hits == []
    assert r.error is None, "a failed search engine is an empty result, not an error field"


# ── intent scoring ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("title", ["I need a roofer", "Looking for a plumber",
                                   "Need an estimate", "Roof repair quotes"])
def test_high_intent_titles_score_high(wired, title):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(result("https://acme.com/", title)))
    h = run(ba.search("q")).hits[0]
    assert h.extras["high_intent"] == 1


def test_intent_detected_in_the_snippet(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        result("https://acme.com/", "Acme Roofing", "Need a quote? call us")))
    assert run(ba.search("q")).hits[0].extras["high_intent"] == 1


def test_neutral_titles_score_lower(wired):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        result("https://acme.com/", "Acme Roofing Company", "About our services")))
    h = run(ba.search("q")).hits[0]
    assert h.extras["high_intent"] == 0


# ── website enrichment ──────────────────────────────────────────────────────
def test_crawl_populates_extras_with_email_phone_and_address(ba, srv):
    srv.rec.html("GET", "/", """
      <html><head><meta name="description" content="Acme Roofing, Austin."></head>
      <body>info@acmeroofing.com 512-555-0142 1200 Congress Ave
      <a href="https://www.facebook.com/acme">fb</a></body></html>""")
    hit = SearchHit(title="Acme", url=srv.url("/"), snippet="old")
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(3)))
    assert out.extras["email"] == "info@acmeroofing.com"
    assert out.extras["phone"] == "512-555-0142"
    assert "1200 Congress Ave" in out.extras["address"]
    assert out.extras["crawled"] is True
    assert out.extras["social_links"]["facebook"].endswith("facebook.com/acme")
    assert out.snippet == "Acme Roofing, Austin."
    assert out.score == pytest.approx(0.95)  # 0.5 + 0.15 * 3


def test_partial_crawl_data_lowers_the_score(ba, srv):
    srv.rec.html("GET", "/", "<html><body>info@acmeroofing.com</body></html>")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    assert run(ba._enrich_website_task(hit, asyncio.Semaphore(1))).score == pytest.approx(0.65)


def test_uncrawlable_site_leaves_the_hit_untouched(ba, srv):
    srv.rec.html("GET", "/", "gone", status=500)
    hit = SearchHit(title="Acme", url=srv.url("/"), snippet="original", score=0.95)
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert out.snippet == "original"
    assert out.score == 0.95
    assert "crawled" not in out.extras


def test_secondary_contact_page_is_crawled_and_merged(ba, srv):
    srv.rec.html("GET", "/", "<html><body>Welcome<a href='/contact'>Contact</a>"
                              "</body></html>")
    srv.rec.html("GET", "/contact", "<html><body>info@acme.com 512-555-0142"
                                    "</body></html>")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert out.extras["email"] == "info@acme.com"
    assert out.extras["phone"] == "512-555-0142"
    assert "/contact" in srv.rec.paths("GET")


def test_full_contact_data_skips_the_secondary_crawl(ba, srv):
    srv.rec.html("GET", "/", """<html><body>info@acme.com 512-555-0142
      1200 Congress Ave<a href='/contact'>Contact</a></body></html>""")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert srv.rec.count("GET") == 1
    assert out.extras["email"] == "info@acme.com"


def test_directory_hits_are_not_crawled(ba, srv):
    """Yelp/BBB etc. are returned as-is -- no wasted fetch."""
    for host in ("yelp.com", "yellowpages.com", "bbb.org", "angi.com",
                 "homeadvisor.com", "facebook.com", "instagram.com", "nextdoor.com"):
        hit = SearchHit(title="d", url=f"https://www.{host}/biz/acme", snippet="s")
        out = run(ba._fake_enrich(hit))
        assert out is hit
        assert "crawled" not in out.extras
    assert srv.rec.count() == 0


def test_search_does_not_crawl_directory_results(wired, srv):
    ba, rec = wired
    rec.html("GET", "/ddg", ddg_page(
        result("https://www.yelp.com/biz/acme", "Acme on Yelp")))
    srv.rec.html("GET", "/", "<html>should not be fetched</html>")
    r = run(ba.search("q"))
    assert len(r.hits) == 1
    assert "crawled" not in r.hits[0].extras
    # the only request must be the DDG search itself, not a crawl of the directory
    assert srv.rec.paths("GET") == ["/ddg"], srv.rec.paths("GET")


def test_concurrent_crawls_are_throttled_to_three(ba, srv):
    """asyncio.Semaphore(3) caps parallel crawls to at most 3 in flight.

    Each route is served with a delay, so if the semaphore were absent the
    server would see more than 3 concurrent requests.
    """
    import threading
    for i in range(9):
        srv.rec.html("GET", f"/s{i}", "<html><body>info@acme.com</body></html>",
                     delay=0.15)
    inflight = 0
    peak = 0
    lock = threading.Lock()

    real_fetch = ba._fetch_url

    async def counted(url, params=None):
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        try:
            return await real_fetch(url, params)
        finally:
            with lock:
                inflight -= 1

    ba._fetch_url = counted

    async def go():
        hits = [SearchHit(title=f"S{i}", url=srv.url(f"/s{i}")) for i in range(9)]
        sem = asyncio.Semaphore(3)  # same bound the provider uses
        return await asyncio.gather(*(ba._enrich_website_task(h, sem) for h in hits))

    out = run(go())
    assert len(out) == 9
    assert all(h.extras.get("crawled") for h in out)
    assert peak <= 3, f"throttle leaked: peak concurrency was {peak}"


def test_crawl_exception_is_swallowed_and_the_hit_survives(ba, srv):
    async def boom(url, params=None):
        raise RuntimeError("network exploded")
    ba._fetch_url = boom
    hit = SearchHit(title="Acme", url="https://acme.com/", snippet="s", score=0.8)
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert out is hit
    assert out.snippet == "s"
    assert "crawled" not in out.extras


# ── extraction hygiene ──────────────────────────────────────────────────────
def test_icon_filenames_are_not_treated_as_emails(ba, srv):
    srv.rec.html("GET", "/", "<html><body>logo@2x.png bootstrap@3x.jpeg"
                              " wix@4x.gif</body></html>")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    assert run(ba._enrich_website_task(hit, asyncio.Semaphore(1))).extras["email"] == ""


def test_a_website_without_contact_data_yields_empty_strings_not_guesses(ba, srv):
    """The key data-integrity rule for the crawler: absence is reported as ""."""
    srv.rec.html("GET", "/", "<html><body>Quality roofing since 2009."
                              "</body></html>")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert out.extras["email"] == ""
    assert out.extras["phone"] == ""
    assert out.extras["address"] == ""
    assert out.extras["social_links"] == {}
    # "since 2009" is not a phone number and must not become one
    assert "2009" not in out.extras["phone"]
    assert out.score == pytest.approx(0.5), "nothing found -> baseline score"


def test_description_falls_back_to_long_paragraphs(ba, srv):
    srv.rec.html("GET", "/", "<html><body><p>" + "A" * 40 + "</p><p>short</p>"
                              "</body></html>")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert out.snippet == "A" * 40


def test_empty_html_document_is_handled(ba, srv):
    srv.rec.html("GET", "/", "<html></html>")
    hit = SearchHit(title="Acme", url=srv.url("/"))
    out = run(ba._enrich_website_task(hit, asyncio.Semaphore(1)))
    assert out.extras["email"] == ""
    assert out.extras["crawled"] is True


# ── _fetch_url ──────────────────────────────────────────────────────────────
def test_fetch_url_returns_none_for_non_200(ba, srv):
    srv.rec.html("GET", "/", "x", status=404)
    assert run(ba._fetch_url(srv.url("/"))) is None


def test_fetch_url_returns_none_when_nothing_is_listens(ba, closed_port):
    assert run(ba._fetch_url(closed_port + "/")) is None


def test_fetch_url_appends_encoded_params(ba, srv):
    srv.rec.html("GET", "/ddg", "<html>ok</html>")
    run(ba._fetch_url(srv.url("/ddg"), params={"q": "a b&c"}))
    assert srv.rec.query_of("/ddg") == {"q": ["a b&c"]}


def test_fetch_url_falls_back_to_httpx_when_playwright_fails(ba, srv, monkeypatch):
    ba.playwright_available = True
    srv.rec.html("GET", "/", "<html>httpx won</html>")

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("no browser installed")
        async def __aexit__(self, *a):
            return False

    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: _Boom())
    assert "httpx won" in run(ba._fetch_url(srv.url("/")))


# ── _crawl_website directly ─────────────────────────────────────────────────
def test_crawl_website_returns_empty_dict_for_a_dead_url(ba, closed_port):
    assert run(ba._crawl_website(closed_port + "/")) == {}


def test_crawl_website_returns_the_description_key(ba, srv):
    srv.rec.html("GET", "/", """<html><head>
      <meta name="description" content="Best roofer."></head><body>x</body></html>""")
    data = run(ba._crawl_website(srv.url("/")))
    assert data["description"] == "Best roofer."
    assert set(data) == {"email", "phone", "address", "social_links", "description"}
