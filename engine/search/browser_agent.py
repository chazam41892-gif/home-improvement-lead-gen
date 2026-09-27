from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import SearchHit, SearchProvider, SearchResult

logger = logging.getLogger("BrowserAgentSearch")

# Regex pattern compilation for quick scanning
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
STREET_RE = re.compile(
    r"\d+\s+[A-Za-z0-9\s,]{2,40}\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Circle|Cir|Place|Pl|Suite|Ste|#)\b",
    re.IGNORECASE,
)

# Realistic headers to mimic standard web browsers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}


def _attr_str(value: object) -> str:
    """Narrow a BeautifulSoup attribute value to str.

    bs4 types ``tag[key]`` as ``str | AttributeValueList`` because a handful of
    HTML attributes (class, rel, headers, ...) are whitespace-separated lists.
    Every attribute read here is href, which is never multi-valued, so this is
    a pure typing narrowing: a str passes through as the same object.
    """
    return value if isinstance(value, str) else str(value)


class BrowserSearchProvider(SearchProvider):
    name = "browser"

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0):
        super().__init__(api_key=api_key, timeout=timeout)
        self.playwright_available = False
        try:
            # Availability probe, not a use: importing the symbol proves the
            # package is installed. Annotated so the intent survives lint.
            from playwright.async_api import async_playwright as _  # noqa: F401

            self.playwright_available = True
        except ImportError:
            pass

    async def search(self, query: str, *, num_results: int = 15, **kwargs) -> SearchResult:
        import time

        t0 = time.time()
        logger.info("Browser search started for query: %s", query)

        # 1. Search DuckDuckGo HTML without API keys
        hits = await self._search_duckduckgo(query, num_results)

        # 2. Enrich found leads by crawling their websites concurrently (throttled)
        sem = asyncio.Semaphore(3)
        tasks = []
        for hit in hits:
            # Skip directory domains for crawling to save time, but keep them as hits
            parsed = urlparse(hit.url)
            domain = parsed.netloc.lower()
            if any(
                skip in domain
                for skip in (
                    "yelp.com",
                    "yellowpages.com",
                    "bbb.org",
                    "angi.com",
                    "homeadvisor.com",
                    "facebook.com",
                    "instagram.com",
                    "nextdoor.com",
                )
            ):
                tasks.append(self._fake_enrich(hit))
            else:
                tasks.append(self._enrich_website_task(hit, sem))

        enriched_hits = await asyncio.gather(*tasks)

        elapsed = time.time() - t0
        logger.info("Browser search complete. Found %d leads in %.2fs", len(enriched_hits), elapsed)

        return SearchResult(
            query=query,
            hits=enriched_hits,
            provider=self.name,
            elapsed_sec=elapsed,
            total_results=len(enriched_hits),
        )

    async def _fake_enrich(self, hit: SearchHit) -> SearchHit:
        # Just return directories as-is
        return hit

    async def _search_duckduckgo(self, query: str, num_results: int) -> list[SearchHit]:
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        hits: list[SearchHit] = []

        html = await self._fetch_url(url, params=params)
        if not html:
            logger.warning("Failed to retrieve DuckDuckGo search results")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results = soup.find_all("div", class_="result")

        seen_urls = set()
        for r in results:
            if len(hits) >= num_results:
                break

            a = r.find("a", class_="result__url")
            snippet_el = r.find("a", class_="result__snippet")

            title = a.get_text(strip=True) if a else ""
            href = _attr_str(a["href"]) if a else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            if not href or not title:
                continue

            # Resolve DuckDuckGo redirection link
            if href.startswith("//duckduckgo.com/l/?uddg="):
                parsed = urlparse("https:" + href)
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    href = qs["uddg"][0]
            elif href.startswith("/l/?uddg="):
                parsed = urlparse("https://duckduckgo.com" + href)
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    href = qs["uddg"][0]

            clean_url = href.rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            # Skip obvious non-business search ads redirections
            if "duckduckgo.com/y.js" in clean_url:
                continue

            intent_triggers = [
                "recommendation",
                "recommend",
                "looking for",
                "hire",
                "need",
                "estimate",
                "quote",
                "repair",
                "install",
                "help",
            ]
            has_intent = any(
                trigger in title.lower() or trigger in snippet.lower() for trigger in intent_triggers
            )

            hits.append(
                SearchHit(
                    title=title,
                    url=href,
                    snippet=snippet,
                    score=0.95 if has_intent else 0.8,
                    extras={"high_intent": 1 if has_intent else 0},
                )
            )

        return hits

    async def _enrich_website_task(self, hit: SearchHit, sem: asyncio.Semaphore) -> SearchHit:
        async with sem:
            try:
                enrichment = await self._crawl_website(hit.url)
                if enrichment:
                    # Update snippet with crawled description or needs
                    desc = enrichment.get("description")
                    if desc:
                        hit.snippet = desc[:400]
                    # Put extracted contact info into extras
                    hit.extras.update(
                        {
                            "email": enrichment.get("email", ""),
                            "phone": enrichment.get("phone", ""),
                            "address": enrichment.get("address", ""),
                            "social_links": enrichment.get("social_links", {}),
                            "crawled": True,
                        }
                    )
                    # Adjust score based on completeness
                    completeness = sum(1 for k in ("email", "phone", "address") if enrichment.get(k))
                    hit.score = min(1.0, 0.5 + 0.15 * completeness)
            except Exception as e:
                logger.debug("Failed to crawl website %s: %s", hit.url, e)
            return hit

    async def _crawl_website(self, url: str) -> dict[str, Any]:
        """Crawl the website, fetching home page and optionally contact page."""
        home_html = await self._fetch_url(url)
        if not home_html:
            return {}

        soup = BeautifulSoup(home_html, "html.parser")
        data = self._extract_data_from_soup(soup, url)

        # Parse description/needs
        desc = ""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            desc = _attr_str(meta_desc.get("content"))
        else:
            # Fallback: extract first couple of paragraphs
            paragraphs = [
                p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20
            ]
            desc = " ".join(paragraphs[:2])
        data["description"] = desc

        # Check if we got everything we need (phone and email)
        if data.get("email") and data.get("phone") and data.get("address"):
            return data

        # Look for contact or about links to crawl as a secondary page
        contact_url = None
        for a in soup.find_all("a", href=True):
            raw_href = _attr_str(a["href"])
            href = raw_href.lower()
            text = a.get_text(strip=True).lower()
            if any(
                k in href or k in text
                for k in ("contact", "about", "info", "services", "contact-us", "about-us")
            ):
                contact_url = urllib.parse.urljoin(url, raw_href)
                break

        if contact_url and contact_url != url:
            logger.debug("Crawling secondary page: %s", contact_url)
            contact_html = await self._fetch_url(contact_url)
            if contact_html:
                contact_soup = BeautifulSoup(contact_html, "html.parser")
                secondary_data = self._extract_data_from_soup(contact_soup, contact_url)
                # Merge secondary details in-place
                for key in ("email", "phone", "address"):
                    if not data.get(key) and secondary_data.get(key):
                        data[key] = secondary_data[key]
                if secondary_data.get("social_links"):
                    data["social_links"].update(secondary_data["social_links"])

        return data

    def _extract_data_from_soup(self, soup: BeautifulSoup, url: str) -> dict[str, Any]:
        text = soup.get_text(" ", strip=True)

        emails = list(set(EMAIL_RE.findall(text)))
        phones = list(set(PHONE_RE.findall(text)))

        # Clean/filter emails to skip icons/images
        emails = [
            e
            for e in emails
            if not any(skip in e.lower() for skip in ("png", "jpg", "jpeg", "gif", "bootstrap", "wix"))
        ]

        # Clean phones/emails to avoid overlapping address matches
        temp_text = text
        for e in emails:
            temp_text = temp_text.replace(e, "")
        for p in phones:
            temp_text = temp_text.replace(p, "")

        addresses = list(set(STREET_RE.findall(temp_text)))

        # Extract social links
        social_links: dict[str, str] = {}
        for a in soup.find_all("a", href=True):
            raw_href = _attr_str(a["href"])
            href = raw_href.lower()
            if "facebook.com/" in href:
                social_links["facebook"] = raw_href
            elif "instagram.com/" in href:
                social_links["instagram"] = raw_href
            elif "linkedin.com/" in href:
                social_links["linkedin"] = raw_href

        return {
            "email": emails[0] if emails else "",
            "phone": phones[0] if phones else "",
            "address": addresses[0] if addresses else "",
            "social_links": social_links,
        }

    async def _fetch_url(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        """Fetch URL content using Playwright if available, otherwise fallback to HTTPX."""
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        if self.playwright_available:
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(user_agent=HEADERS["User-Agent"])
                    page = await context.new_page()
                    # Keep timeout reasonable
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    content = await page.content()
                    await browser.close()
                    return content
            except Exception as e:
                logger.debug("Playwright fetch failed for %s, falling back to HTTPX: %s", url, e)

        # Fallback to HTTPX AsyncClient
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            logger.debug("HTTPX fetch failed for %s: %s", url, e)
        return None
