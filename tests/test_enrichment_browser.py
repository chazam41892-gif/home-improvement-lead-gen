"""Tests for engine/enrichment/browser_enricher.py.

The enricher crawls a real website with httpx (Playwright when installed). We
force playwright_available=False so the httpx path is deterministic and points
at a real local HTTP server, then separately exercise the Playwright branch by
injecting a failing async_playwright.

The one thing we cannot redirect is the hard-coded DuckDuckGo URL, so
_resolve_website_ddg tests wrap _fetch_url to rewrite only that host to the
local server — all parsing (BeautifulSoup, //duckduckgo.com/l/?uddg= unwrap,
directory filtering) still runs for real.
"""
import asyncio

import pytest

import engine.enrichment.browser_enricher as be_mod
from engine.enrichment.browser_enricher import BrowserEnricher
from tests.support_http import LocalServer
from tests.support_fixtures import no_real_network  # noqa: F401

DDG = "https://html.duckduckgo.com/html/"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def e():
    b = BrowserEnricher()
    b.playwright_available = False   # deterministic httpx path
    return b


FULL_PAGE = """
<html><head>
<meta name="description" content="Acme Roofing, serving Austin since 2009.">
</head><body>
<p>Acme Roofing has been serving Central Texas since 2009. A team of 12 employees.</p>
<p>Call us at 512-555-0142 or email info@acmeroofing.com.</p>
<p>1200 Congress Ave, Austin, TX 78701</p>
<a href="https://www.facebook.com/acmeroofing">fb</a>
<a href="https://www.instagram.com/acmeroofing">ig</a>
<a href="https://www.linkedin.com/company/acmeroofing">li</a>
</body></html>
"""


# ── availability ────────────────────────────────────────────────────────────
def test_is_always_available_with_no_api_key():
    assert BrowserEnricher().is_available() is True


def test_playwright_flag_reflects_the_environment():
    b = BrowserEnricher()
    assert isinstance(b.playwright_available, bool)


# ── happy path ──────────────────────────────────────────────────────────────
def test_enrich_extracts_email_phone_address_founded_and_headcount(e, srv):
    srv.rec.html("GET", "/", FULL_PAGE)
    r = run(e.enrich("Acme Roofing", "roofing", website=srv.url("/")))
    assert r.email == "info@acmeroofing.com"
    assert r.phone == "512-555-0142"
    assert r.address is not None and "1200 Congress Ave" in r.address
    assert r.year_founded == 2009
    assert r.employee_count == 12
    assert r.website == srv.url("/")
    assert r.confidence == 1.0
    assert "browser_enricher" in r.sources
    assert "browser:email" in r.sources
    assert r.error is None


def test_enrich_collects_social_links(e, srv):
    srv.rec.html("GET", "/", FULL_PAGE)
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.social_links["facebook"].endswith("facebook.com/acmeroofing")
    assert r.social_links["instagram"].endswith("instagram.com/acmeroofing")
    assert r.social_links["linkedin"].endswith("linkedin.com/company/acmeroofing")


def test_enrich_does_not_parse_the_bare_verb_employ(e, srv):
    """EMPLOYEES_RE needs team-of/employs/has. The bare verb "employ" is not
    matched, so headcount is left absent rather than guessed."""
    srv.rec.html("GET", "/", "<html><body>We employ 12 employees.</body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.employee_count is None


def test_enrich_parses_employs_for_headcount(e, srv):
    srv.rec.html("GET", "/", "<html><body>We employs 12 employees.</body></html>")
    assert run(e.enrich("Acme", "roofing", website=srv.url("/"))).employee_count == 12


def test_enrich_uses_the_meta_description_when_present(e, srv):
    srv.rec.html("GET", "/", FULL_PAGE)
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.raw_data["about_snippet"] == "Acme Roofing, serving Austin since 2009."


def test_enrich_falls_back_to_paragraphs_when_no_meta_description(e, srv):
    srv.rec.html("GET", "/",
                 "<html><body><p>" + "A" * 60 + "</p><p>" + "B" * 60 +
                 "</p><p>tiny</p></body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.raw_data["about_snippet"].startswith("A" * 60)
    assert "tiny" not in r.raw_data["about_snippet"]


def test_enrich_partial_page_scores_below_full(e, srv):
    srv.rec.html("GET", "/", "<html><body><p>info@acmeroofing.com</p></body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email == "info@acmeroofing.com"
    assert r.confidence < 1.0
    assert r.phone is None and r.address is None


# ── secondary (contact/about) crawl ─────────────────────────────────────────
def test_enrich_crawls_the_contact_page_when_home_lacks_details(e, srv):
    srv.rec.html("GET", "/", "<html><body><p>Welcome</p>"
                              "<a href='/contact'>Contact Us</a></body></html>")
    srv.rec.html("GET", "/contact", "<html><body><p>info@acmeroofing.com "
                                     "512-555-0142</p></body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email == "info@acmeroofing.com"
    assert r.phone == "512-555-0142"
    assert "/contact" in srv.rec.paths("GET")


def test_enrich_resolves_relative_contact_hrefs(e, srv):
    srv.rec.html("GET", "/", "<html><body><a href='/about-us'>About</a></body></html>")
    srv.rec.html("GET", "/about-us", "<html><body>info@acmeroofing.com</body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email == "info@acmeroofing.com"
    assert "/about-us" in srv.rec.paths("GET")
    assert srv.rec.count("GET") == 2


def test_enrich_skips_secondary_crawl_when_it_equals_the_target(e, srv):
    srv.rec.html("GET", "/", "<html><body><a href='/'>Contact</a></body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert srv.rec.count("GET") == 1
    assert r.email is None


def test_enrich_survives_a_failing_contact_page(e, srv):
    srv.rec.html("GET", "/", "<html><body><a href='/contact'>Contact</a></body></html>",
                 status=500)
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email is None
    assert r.website == srv.url("/")


# ── _fetch_url behaviour ────────────────────────────────────────────────────
def test_fetch_url_returns_none_for_non_200(e, srv):
    srv.rec.html("GET", "/", "nope", status=404)
    assert run(e._fetch_url(srv.url("/"))) is None


def test_fetch_url_returns_none_when_nothing_is_listening(e):
    assert run(e._fetch_url("http://127.0.0.1:9/")) is None


def test_fetch_url_appends_query_params(e, srv):
    srv.rec.html("GET", "/search", "<html>ok</html>")
    out = run(e._fetch_url(srv.url("/search"), params={"q": "acme roofing"}))
    assert "ok" in out
    assert srv.rec.query_of("/search") == {"q": ["acme roofing"]}


def test_fetch_url_url_encodes_params(e, srv):
    srv.rec.html("GET", "/search", "<html>ok</html>")
    run(e._fetch_url(srv.url("/search"), params={"q": "a b&c=d"}))
    assert srv.rec.query_of("/search") == {"q": ["a b&c=d"]}


def test_fetch_url_falls_back_to_httpx_when_playwright_launch_fails(e, srv, monkeypatch):
    """Playwright branch: a browser that cannot launch must fall back, not crash."""
    e.playwright_available = True
    srv.rec.html("GET", "/", "<html>httpx won</html>")

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("no browser binary installed")

        async def __aexit__(self, *a):
            return False

    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: _Boom())
    assert "httpx won" in run(e._fetch_url(srv.url("/")))


# ── DDG website resolution ──────────────────────────────────────────────────
def _redirect_ddg(e, srv):
    """Rewrite only the hard-coded DDG host to the local server."""
    real = e._fetch_url

    async def patched(url, params=None):
        if url.startswith(DDG):
            url = srv.url("/ddg")
        return await real(url, params=params)

    e._fetch_url = patched
    return e


def test_resolve_website_unwraps_the_uddg_redirect(e, srv):
    srv.rec.html("GET", "/ddg", """
      <div class="result"><a class="result__url"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Facmeroofing.com%2F">Acme</a></div>
    """)
    e2 = _redirect_ddg(e, srv)
    assert run(e2._resolve_website_ddg("Acme Roofing", "Austin")) == "https://acmeroofing.com/"


def test_resolve_website_unwraps_the_relative_uddg_redirect(e, srv):
    srv.rec.html("GET", "/ddg", """
      <div class="result"><a class="result__url"
        href="/l/?uddg=https%3A%2F%2Facmeroofing.com%2F">Acme</a></div>
    """)
    e2 = _redirect_ddg(e, srv)
    assert run(e2._resolve_website_ddg("Acme", "Austin")) == "https://acmeroofing.com/"


def test_resolve_website_returns_a_plain_url_untouched(e, srv):
    srv.rec.html("GET", "/ddg", """
      <div class="result"><a class="result__url"
        href="https://acmeroofing.com/">Acme</a></div>
    """)
    e2 = _redirect_ddg(e, srv)
    assert run(e2._resolve_website_ddg("Acme", None)) == "https://acmeroofing.com/"


@pytest.mark.parametrize("host", ["yelp.com", "yellowpages.com", "bbb.org",
                                 "angi.com", "homeadvisor.com", "facebook.com",
                                 "instagram.com", "twitter.com", "linkedin.com",
                                 "duckduckgo.com"])
def test_resolve_website_skips_every_directory_host(e, srv, host):
    srv.rec.html("GET", "/ddg", f"""
      <div class="result"><a class="result__url"
        href="https://www.{host}/biz/acme">dir</a></div>
      <div class="result"><a class="result__url"
        href="https://acmeroofing.com/">real</a></div>
    """)
    e2 = _redirect_ddg(e, srv)
    assert run(e2._resolve_website_ddg("Acme", "Austin")) == "https://acmeroofing.com/"


def test_resolve_website_skips_results_without_a_link(e, srv):
    srv.rec.html("GET", "/ddg", '<div class="result"><span>no link</span></div>')
    assert run(_redirect_ddg(e, srv)._resolve_website_ddg("Acme", None)) is None


def test_resolve_website_returns_none_on_no_html(e, srv):
    srv.rec.html("GET", "/ddg", "", status=500)
    assert run(_redirect_ddg(e, srv)._resolve_website_ddg("Acme", None)) is None


def test_resolve_website_returns_none_when_ddg_is_unreachable(e):
    real = e._fetch_url

    async def boom(url, params=None):
        return "http://127.0.0.1:9" in url or await real(url, params)

    async def fail(url, params=None):
        if url.startswith(DDG):
            raise ConnectionError("ddg down")
        return await real(url, params)

    e._fetch_url = fail
    assert run(e._resolve_website_ddg("Acme", None)) is None


def test_enrich_uses_ddg_when_no_website_supplied(e, srv):
    """Full flow: DDG resolves the website, then the enricher crawls it.

    The resolved href points at the LOCAL server so this test makes no real
    network request.
    """
    srv.rec.html("GET", "/ddg", f"""
      <div class="result"><a class="result__url"
        href="{srv.url('/found')}">Acme</a></div>
    """)
    srv.rec.html("GET", "/found", "<html><body>info@acmeroofing.com</body></html>")
    e2 = _redirect_ddg(e, srv)
    r = run(e2.enrich("Acme Roofing", "roofing", location="Austin"))
    assert r.website == srv.url("/found")
    assert r.email == "info@acmeroofing.com"
    assert "/ddg" in srv.rec.paths("GET")


def test_enrich_errors_when_no_website_can_be_resolved(e, srv):
    srv.rec.html("GET", "/ddg", "<html></html>")
    e2 = _redirect_ddg(e, srv)
    r = run(e2.enrich("Acme Roofing", "roofing", location="Austin"))
    assert r.error == "Could not resolve business website for crawling"
    assert r.email is None and r.phone is None
    assert r.website is None
    assert r.confidence == 0.0


# ── fetch failure paths ─────────────────────────────────────────────────────
def test_enrich_errors_when_the_site_is_unreachable(e):
    r = run(e.enrich("Acme", "roofing", website="http://127.0.0.1:9/"))
    assert r.error.startswith("Failed to retrieve content from website:")
    assert r.email is None and r.phone is None and r.address is None
    assert r.website == "http://127.0.0.1:9/"
    assert r.sources == []


def test_enrich_errors_when_the_site_returns_500(e, srv):
    srv.rec.html("GET", "/", "boom", status=500)
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.error.startswith("Failed to retrieve content from website:")
    assert r.email is None


# ── extraction hygiene ──────────────────────────────────────────────────────
def test_enrich_filters_icon_filenames_that_look_like_emails(e, srv):
    srv.rec.html("GET", "/", """
      <html><body>logo@2x.png and bootstrap@3x.jpeg are assets, not addresses</body></html>
    """)
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email is None, r.email
    assert r.sources == ["browser_enricher"]


def test_enrich_does_not_treat_a_phone_number_as_part_of_an_address(e, srv):
    srv.rec.html("GET", "/", """
      <html><body>Call 512-555-0142 today. 1200 Congress Ave, Austin, TX 78701</body></html>
    """)
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.phone == "512-555-0142"
    assert r.address == "1200 Congress Ave"


def test_enrich_merges_secondary_page_fields_into_the_result(e, srv):
    srv.rec.html("GET", "/", "<html><body>info@acmeroofing.com "
                              "<a href='/contact'>Contact</a></body></html>")
    srv.rec.html("GET", "/contact", "<html><body>512-555-0142</body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email == "info@acmeroofing.com"
    assert r.phone == "512-555-0142", "contact-page phone must be merged in"


def test_enrich_does_not_overwrite_a_field_already_found_on_the_home_page(e, srv):
    """Once email is set, the secondary crawl must not replace it."""
    e_result = BrowserEnricher()
    e_result.playwright_available = False
    srv.rec.html("GET", "/", "<html><body>info@acmeroofing.com"
                              "<a href='/contact'>Contact</a></body></html>")
    srv.rec.html("GET", "/contact", "<html><body>replaced@evil.example</body></html>")
    r = run(e_result.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email == "info@acmeroofing.com", r.email


def test_enrich_handles_an_empty_html_document(e, srv):
    srv.rec.html("GET", "/", "<html></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email is None and r.phone is None and r.address is None
    assert r.website == srv.url("/")
    assert r.confidence == pytest.approx(0.45)  # 0.3 + 0.15 * website only
    assert r.error is None


def test_enrich_handles_non_html_content(e, srv):
    srv.rec.add("GET", "/", payload={"error": "not a website"})
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    assert r.email is None
    assert r.error is None


# ── CRITICAL: never fabricate ───────────────────────────────────────────────
def test_browser_enricher_invents_nothing_on_an_empty_site(e, srv):
    srv.rec.html("GET", "/", "<html><body><p>Committed to quality.</p></body></html>")
    r = run(e.enrich("Acme Roofing", "roofing", website=srv.url("/")))
    assert r.email is None, r.email
    assert r.phone is None
    assert r.address is None
    assert r.contact_name is None
    assert r.year_founded is None
    assert r.employee_count is None
    assert r.raw_data == {}, r.raw_data
    assert r.social_links == {}


def test_browser_enricher_does_not_derive_an_email_from_the_website_url(e, srv):
    srv.rec.html("GET", "/", "<html><body>No contact page.</body></html>")
    r = run(e.enrich("Acme Roofing", "roofing",
                     website="https://info@acmeroofing.com/"))
    assert r.email is None


def test_browser_enricher_reports_no_email_rather_than_a_placeholder(e, srv):
    srv.rec.html("GET", "/", "<html><body>Call us today!</body></html>")
    r = run(e.enrich("Acme", "roofing", website=srv.url("/")))
    for bad in ("n/a", "N/A", "none", "None", "null", "unknown", "info@", "@"):
        assert r.email is None or bad not in r.email
    assert r.email is None
