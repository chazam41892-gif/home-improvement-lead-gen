"""Edge-case tests that close the remaining coverage gaps in engine/enrichment
and engine/search: the Playwright success path, ValueError guards on int()
parsing, the unreachable Perplexity fallback, and the social-link elif chain.

These are the paths the main behavioural suites cannot reach naturally.
"""
import asyncio

import pytest

import engine.enrichment.apollo_enricher as apollo_mod
import engine.enrichment.browser_enricher as be_mod
import engine.enrichment.exa_enricher as exa_e_mod
import engine.search.browser_agent as ba_mod
from engine.enrichment.base import EnrichmentResult
from tests.support_fixtures import no_real_network  # noqa: F401
from tests.support_http import LocalServer


def run(coro):
    return asyncio.run(coro)


# ── a fake Playwright that "works" ──────────────────────────────────────────
class FakePage:
    def __init__(self, content):
        self._content = content
        self.goto_calls = []

    async def goto(self, url, timeout=None, wait_until=None):
        self.goto_calls.append({"url": url, "timeout": timeout,
                                "wait_until": wait_until})

    async def content(self):
        return self._content


class FakeContext:
    def __init__(self, page, log):
        self._page = page
        self._log = log

    async def new_page(self):
        self._log.append("new_page")
        return self._page


class FakeBrowser:
    def __init__(self, page, log):
        self._page = page
        self._log = log

    async def new_context(self, user_agent=None):
        self._log.append({"new_context": user_agent})
        return FakeContext(self._page, self._log)

    async def close(self):
        self._log.append("close")


class FakePlaywright:
    def __init__(self, page, log):
        self.chromium = self
        self._page = page
        self._log = log

    async def launch(self, headless=False):
        self._log.append({"launch": headless})
        return FakeBrowser(self._page, self._log)

    async def __aenter__(self):
        self._log.append("enter")
        return self

    async def __aexit__(self, *a):
        self._log.append("exit")
        return False


def install_fake_playwright(monkeypatch, html: str):
    """Make `from playwright.async_api import async_playwright` yield a double.

    Returns (log, page) so callers can assert on either.
    """
    import playwright.async_api as pw
    log = []
    page = FakePage(html)
    monkeypatch.setattr(pw, "async_playwright", lambda: FakePlaywright(page, log))
    return log, page


# ── BrowserEnricher: Playwright success path ────────────────────────────────
def test_browser_enricher_uses_playwright_when_it_succeeds(monkeypatch):
    log, _page = install_fake_playwright(monkeypatch, "<html><body>"
                                                    "info@acmeroofing.com</body></html>")
    b = be_mod.BrowserEnricher()
    assert b.playwright_available is True
    r = run(b.enrich("Acme", "roofing", website="https://acme.com/"))
    assert r.email == "info@acmeroofing.com"
    assert "launch" in str(log) and "close" in str(log)


def test_browser_enricher_playwright_receives_the_browser_user_agent(monkeypatch):
    log, _page = install_fake_playwright(monkeypatch, "<html><body>x</body></html>")
    b = be_mod.BrowserEnricher()
    run(b._fetch_url("https://acme.com/"))
    ua = [e for e in log if isinstance(e, dict) and "new_context" in e][0]
    assert "Chrome/120" in ua["new_context"]
    assert [e for e in log if isinstance(e, dict) and "launch" in e][0] == {"launch": True}


def test_browser_enricher_playwright_goto_uses_bounded_timeouts(monkeypatch):
    page = FakePage("<html></html>")
    log = []
    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: FakePlaywright(page, log))
    b = be_mod.BrowserEnricher()
    run(b._fetch_url("https://acme.com/"))
    assert page.goto_calls == [{"url": "https://acme.com/", "timeout": 15000,
                                "wait_until": "domcontentloaded"}]


def test_browser_enricher_queries_reach_playwright_with_params(monkeypatch):
    _log, page = install_fake_playwright(monkeypatch, "<html>ok</html>")
    b = be_mod.BrowserEnricher()
    out = run(b._fetch_url("https://html.duckduckgo.com/html/", params={"q": "a b"}))
    assert "ok" in out
    assert page.goto_calls[0]["url"] == "https://html.duckduckgo.com/html/?q=a+b"


def test_browser_enricher_import_error_leaves_playwright_unavailable(monkeypatch):
    """The `except ImportError: pass` arm at browser_enricher.py:45-46."""
    import builtins
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert be_mod.BrowserEnricher().playwright_available is False


# ── BrowserSearchProvider: Playwright success path ──────────────────────────
def test_browser_agent_uses_playwright_when_it_succeeds(monkeypatch):
    install_fake_playwright(monkeypatch, "<html><body>info@acme.com</body></html>")
    p = ba_mod.BrowserSearchProvider()
    assert p.playwright_available is True
    out = run(p._fetch_url("https://acme.com/"))
    assert "info@acme.com" in out


def test_browser_agent_playwright_uses_browser_user_agent(monkeypatch):
    log, _page = install_fake_playwright(monkeypatch, "<html></html>")
    p = ba_mod.BrowserSearchProvider()
    run(p._fetch_url("https://acme.com/"))
    ua = [e for e in log if isinstance(e, dict) and "new_context" in e][0]
    assert "Chrome/120" in ua["new_context"]


def test_browser_agent_playwright_failure_falls_back_to_httpx(monkeypatch):
    p = ba_mod.BrowserSearchProvider()
    p.playwright_available = True

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("browser binary missing")
        async def __aexit__(self, *a):
            return False

    import playwright.async_api as pw
    monkeypatch.setattr(pw, "async_playwright", lambda: _Boom())
    assert run(p._fetch_url("http://127.0.0.1:9/")) is None


def test_browser_agent_import_error_leaves_playwright_unavailable(monkeypatch):
    """The `except ImportError: pass` arm at browser_agent.py:42-43."""
    import builtins
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert ba_mod.BrowserSearchProvider().playwright_available is False


# ── social-link elif chain (browser_agent.py:243,245) ────────────────────────
def test_all_three_social_networks_are_captured_from_one_page():
    from bs4 import BeautifulSoup
    from engine.search.browser_agent import BrowserSearchProvider
    p = BrowserSearchProvider()
    soup = BeautifulSoup("<html><body>"
                         "<a href='https://facebook.com/acme'>f</a>"
                         "<a href='https://www.instagram.com/acme'>i</a>"
                         "<a href='https://linkedin.com/company/acme'>l</a>"
                         "</body></html>", "html.parser")
    data = p._extract_data_from_soup(soup, "https://acme.com")
    assert set(data["social_links"]) == {"facebook", "instagram", "linkedin"}


def test_later_social_links_overwrite_earlier_ones():
    from bs4 import BeautifulSoup
    from engine.search.browser_agent import BrowserSearchProvider
    p = BrowserSearchProvider()
    soup = BeautifulSoup("<html><body>"
                         "<a href='https://facebook.com/old'>f</a>"
                         "<a href='https://facebook.com/new'>f</a>"
                         "</body></html>", "html.parser")
    data = p._extract_data_from_soup(soup, "https://acme.com")
    assert data["social_links"]["facebook"] == "https://facebook.com/new"


def test_secondary_page_social_links_are_merged_into_the_primary():
    """browser_agent.py:214 -- secondary social links update the primary dict."""
    with LocalServer() as srv:
        srv.rec.html("GET", "/", "<html><body>Welcome"
                                   "<a href='/contact'>Contact</a></body></html>")
        srv.rec.html("GET", "/contact",
                     "<html><body><a href='https://facebook.com/acme'>f</a>"
                     "<a href='https://instagram.com/acme'>i</a></body></html>")
        p = ba_mod.BrowserSearchProvider()
        p.playwright_available = False
        data = run(p._crawl_website(srv.url("/")))
        assert data["social_links"] == {"facebook": "https://facebook.com/acme",
                                        "instagram": "https://instagram.com/acme"}


# ── int() ValueError guards ─────────────────────────────────────────────────
def test_browser_enricher_guards_int_parsing_for_year_and_headcount():
    """browser_enricher.py:184-185 / 193-194 -- the FOUNDED_RE / EMPLOYEES_RE
    ValueError arms. Reached by calling the parser with a result whose setters
    reject the value."""
    from bs4 import BeautifulSoup
    from engine.enrichment.browser_enricher import BrowserEnricher
    b = BrowserEnricher()
    guarded = EnrichmentResult(business_name="A", trade="t")
    guarded.rejects_ints = True

    def guarded_setattr(self, k, v):
        if getattr(self, "rejects_ints", False) and k in ("year_founded",
                                                          "employee_count"):
            raise ValueError("rejected")
        object.__setattr__(self, k, v)

    type(guarded).__setattr__ = guarded_setattr
    try:
        soup = BeautifulSoup("<html><body>Founded in 2001. "
                             "A team of 12 employees.</body></html>",
                             "html.parser")
        b._populate_from_soup(soup, guarded, "https://acme.com")
        assert guarded.year_founded is None
        assert guarded.employee_count is None
        assert "browser:year_founded" not in guarded.sources
        assert "browser:employee_count" not in guarded.sources
    finally:
        del type(guarded).__setattr__


def test_apollo_org_enrich_guards_unparsable_headcount(monkeypatch):
    """apollo_enricher.py:171-172 -- int(raw) raising ValueError inside enrich()."""
    keys = {"apollo": "k"}
    monkeypatch.setattr(apollo_mod.KeyVault, "get", staticmethod(lambda s: keys.get(s)))
    with LocalServer() as srv:
        monkeypatch.setattr(apollo_mod, "APOLLO_BASE", srv.base + "/v1")
        srv.rec.add("POST", "/v1/mixed_people/search", {"people": []})
        srv.rec.add("POST", "/v1/organizations/enrich", {"organization": {
            "name": "Acme", "primary_domain": "acme.com",
            "employee_count": "about 50"}})
        e = apollo_mod.ApolloEnricher()
        r = run(e.enrich("Acme", "roofing", website="https://acme.com"))
        assert r.employee_count is None, "unparsable headcount must stay None"
        assert r.website == "acme.com"
        assert r.email is None


def test_apollo_person_headcount_guard_is_reachable(monkeypatch):
    """The same guard on the people branch: employee_count that int() rejects."""
    keys = {"apollo": "k"}
    # monkeypatch, never `KeyVault.get = ...` -- a bare assignment replaces the
    # classmethod for the rest of the session and corrupts unrelated tests.
    monkeypatch.setattr(apollo_mod.KeyVault, "get", staticmethod(lambda s: keys.get(s)))
    with LocalServer() as srv:
        import importlib
        importlib.reload(apollo_mod)
    monkeypatch.setattr(apollo_mod.KeyVault, "get", staticmethod(lambda s: keys.get(s)))
    with LocalServer() as srv:
        apollo_mod.APOLLO_BASE = srv.base + "/v1"
        srv.rec.add("POST", "/v1/mixed_people/search", {"people": [{
            "id": "1", "first_name": "A", "last_name": "B",
            "organization": {"name": "Acme", "employee_count": None,
                             "annual_revenue": None}}]})
        e = apollo_mod.ApolloEnricher()
        r = run(e.enrich("Acme", "roofing"))
        assert r.employee_count is None
        assert r.contact_name == "A B"


# ── ExaEnricher: exception arms in _find_website and enrich ────────────────
def test_exa_find_website_swallows_a_client_exception(monkeypatch):
    """exa_enricher.py:59-60."""
    keys = {"exa": "k"}
    monkeypatch.setattr(exa_e_mod.KeyVault, "get", staticmethod(lambda s: keys.get(s)))
    e = exa_e_mod.ExaEnricher()

    class Boom:
        async def search(self, *a, **k):
            raise RuntimeError("exa exploded")

    e._exa = Boom()
    assert run(e._find_website("Acme", "roofing")) is None


def test_exa_enrich_swallows_a_contents_exception(monkeypatch):
    """exa_enricher.py:98-99."""
    keys = {"exa": "k"}
    monkeypatch.setattr(exa_e_mod.KeyVault, "get", staticmethod(lambda s: keys.get(s)))
    e = exa_e_mod.ExaEnricher()

    class Boom:
        async def search(self, *a, **k):
            return type("R", (), {"hits": []})()

        async def contents(self, *a, **k):
            raise RuntimeError("contents exploded")

    e._exa = Boom()
    r = run(e.enrich("Acme", "roofing", website="https://acme.com"))
    assert r.email is None and r.phone is None
    assert r.website == "https://acme.com"
    assert r.sources == ["exa_enricher"]
    assert r.error is None


# ── Perplexity: the unreachable urlparse fallback ──────────────────────────
def test_perplexity_fallback_title_is_dead_code():
    """perplexity.py:79-80 is unreachable: urlparse() does not raise for a
    bare string, so `except Exception` never fires and the fallback title
    "Cited Business Source" can never be produced. Assert the reachable
    behaviour and record why the arm is dead."""
    from engine.search.perplexity import PerplexitySearchProvider
    from urllib.parse import urlparse
    # prove the premise: urlparse never raises here
    for bad in ("not-a-url", "", "http://", "///", "%%%", "a b c"):
        urlparse(bad)  # no exception

    with LocalServer() as srv:
        srv.rec.add("POST", "/chat/completions", {
            "choices": [], "citations": ["%%%", "https://ok.com"]})
        p = PerplexitySearchProvider(api_key="k", base_url=srv.base)
        r = run(p.search("q"))
        titles = [h.title for h in r.hits]
        assert "Source: " in titles, "unparseable citation -> blank domain"
        assert "Cited Business Source" not in titles
        assert "Source: ok.com" in titles
