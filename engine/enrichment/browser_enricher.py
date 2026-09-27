from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import EnrichmentProvider, EnrichmentResult

logger = logging.getLogger("BrowserEnricher")

# Regex pattern compilation
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
STREET_RE = re.compile(
    r"\d+\s+[A-Za-z0-9\s,]{2,40}\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Circle|Cir|Place|Pl|Suite|Ste|#)\b",
    re.IGNORECASE,
)
FOUNDED_RE = re.compile(r"\b(?:founded|established|since|est\.)\s*(?:in\s+)?(\d{4})\b", re.IGNORECASE)
EMPLOYEES_RE = re.compile(
    r"\b(?:team\s+of|employs|has)\s*(\d{1,3})\s*(?:employees|people|staff)\b", re.IGNORECASE
)

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
    Every attribute read here is href/content, which is never multi-valued, so
    this is a pure typing narrowing: a str passes through as the same object.
    """
    return value if isinstance(value, str) else str(value)


class BrowserEnricher(EnrichmentProvider):
    name = "browser_enricher"
    input_preferences = ["website", "business_name", "location"]
    input_required = []
    priority = 3

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.playwright_available = False
        try:
            # Availability probe, not a use: importing the symbol proves the
            # package is installed. Annotated so the intent survives lint.
            from playwright.async_api import async_playwright as _  # noqa: F401

            self.playwright_available = True
        except ImportError:
            pass

    def is_available(self) -> bool:
        # Key-less scraper is always available!
        return True

    async def _resolve_website_ddg(self, name: str, location: str | None) -> str | None:
        """Query DDG to find the primary business website if website URL is missing."""
        query = f"{name} {location or ''}".strip()
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}

        try:
            html = await self._fetch_url(url, params=params)
            if not html:
                return None

            soup = BeautifulSoup(html, "html.parser")
            results = soup.find_all("div", class_="result")
            for r in results:
                a = r.find("a", class_="result__url")
                if not a:
                    continue
                href = _attr_str(a["href"])
                # Resolve redirect
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

                parsed_href = urlparse(href)
                domain = parsed_href.netloc.lower()

                # Skip common business directories/aggregators
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
                        "twitter.com",
                        "linkedin.com",
                        "duckduckgo.com",
                    )
                ):
                    continue

                if domain:
                    return href
        except Exception as e:
            logger.debug("Failed to resolve website via DDG: %s", e)
        return None

    async def enrich(
        self,
        business_name: str,
        trade: str,
        location: str | None = None,
        website: str | None = None,
        phone: str | None = None,
        **kwargs,
    ) -> EnrichmentResult:
        # `phone` is declared for LSP compliance with EnrichmentProvider.enrich
        # (a keyless scraper has no use for it). It is intentionally unused.
        result = EnrichmentResult(business_name=business_name, trade=trade)

        target_url = website
        if not target_url:
            logger.debug("Website missing for enrichment. Resolving website for: %s", business_name)
            target_url = await self._resolve_website_ddg(business_name, location)

        if not target_url:
            result.error = "Could not resolve business website for crawling"
            return result

        result.website = target_url

        # Crawl the home page
        home_html = await self._fetch_url(target_url)
        if not home_html:
            result.error = f"Failed to retrieve content from website: {target_url}"
            return result

        soup = BeautifulSoup(home_html, "html.parser")
        self._populate_from_soup(soup, result, target_url)

        # Check if we got email, phone, and address
        if result.email and result.phone and result.address:
            result.confidence = 1.0
            result.sources.append("browser_enricher")
            return result

        # Seek out contact or about page for secondary crawl
        secondary_url = None
        for a in soup.find_all("a", href=True):
            raw_href = _attr_str(a["href"])
            href = raw_href.lower()
            text = a.get_text(strip=True).lower()
            if any(k in href or k in text for k in ("contact", "about", "info", "contact-us", "about-us")):
                secondary_url = urllib.parse.urljoin(target_url, raw_href)
                break

        if secondary_url and secondary_url != target_url:
            logger.debug("Crawling secondary page for enrichment: %s", secondary_url)
            contact_html = await self._fetch_url(secondary_url)
            if contact_html:
                contact_soup = BeautifulSoup(contact_html, "html.parser")
                self._populate_from_soup(contact_soup, result, secondary_url)

        # Calculate final confidence score
        fields_filled = sum(
            1 for f in ("contact_name", "phone", "email", "address", "website") if getattr(result, f)
        )
        result.confidence = min(1.0, 0.3 + 0.15 * fields_filled)
        result.sources.append("browser_enricher")

        return result

    def _populate_from_soup(self, soup: BeautifulSoup, result: EnrichmentResult, url: str):
        text = soup.get_text(" ", strip=True)

        emails = list(set(EMAIL_RE.findall(text)))
        phones = list(set(PHONE_RE.findall(text)))

        # skips wix/boostrap PNGs that look like emails
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

        if emails and not result.email:
            result.email = emails[0]
            result.sources.append("browser:email")
        if phones and not result.phone:
            result.phone = phones[0]
            result.sources.append("browser:phone")
        if addresses and not result.address:
            result.address = addresses[0]
            result.sources.append("browser:address")

        # Parse founded date
        founded_match = FOUNDED_RE.search(text)
        if founded_match and result.year_founded is None:
            try:
                result.year_founded = int(founded_match.group(1))
                result.sources.append("browser:year_founded")
            except ValueError:
                pass

        # Parse employee count
        employees_match = EMPLOYEES_RE.search(text)
        if employees_match and result.employee_count is None:
            try:
                result.employee_count = int(employees_match.group(1))
                result.sources.append("browser:employee_count")
            except ValueError:
                pass

        # Extract social links
        for a in soup.find_all("a", href=True):
            raw_href = _attr_str(a["href"])
            href = raw_href.lower()
            if "facebook.com/" in href and "facebook" not in result.social_links:
                result.social_links["facebook"] = raw_href
            elif "instagram.com/" in href and "instagram" not in result.social_links:
                result.social_links["instagram"] = raw_href
            elif "linkedin.com/" in href and "linkedin" not in result.social_links:
                result.social_links["linkedin"] = raw_href

        # Parse descriptions/about text as raw data snippet
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            result.raw_data["about_snippet"] = meta_desc.get("content")
        else:
            paragraphs = [
                p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 30
            ]
            if paragraphs:
                result.raw_data["about_snippet"] = " ".join(paragraphs[:2])[:400]

    async def _fetch_url(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        if self.playwright_available:
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(user_agent=HEADERS["User-Agent"])
                    page = await context.new_page()
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    content = await page.content()
                    await browser.close()
                    return content
            except Exception as e:
                logger.debug("Playwright fetch failed in browser enricher: %s", e)

        # Fallback to HTTPX AsyncClient
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            logger.debug("HTTPX fetch failed in browser enricher: %s", e)
        return None
