from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from .base import EnrichmentProvider, EnrichmentResult
from ..key_vault import KeyVault

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
STREET_RE = re.compile(r"\d+\s+[A-Za-z0-9\s,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Circle|Cir|Place|Pl|Suite|Ste|#)\s*,?\s*[A-Za-z\s]+,?\s*[A-Z]{2}\s*\d{5}")


class ExaEnricher(EnrichmentProvider):
    name = "exa_enricher"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._exa = None

    def _get_exa(self):
        if self._exa is not None:
            return self._exa
        from ..search.exa import ExaSearchProvider
        api_key = KeyVault.get("exa")
        self._exa = ExaSearchProvider(api_key=api_key) if api_key else None
        return self._exa

    def is_available(self) -> bool:
        return KeyVault.get("exa") is not None

    async def _find_website(self, business: str, trade: str, location: Optional[str] = None) -> Optional[str]:
        exa = self._get_exa()
        if not exa:
            return None
        queries = [f"{business} {location or ''}".strip()]
        if trade:
            queries.append(f"{business} {trade} {location or ''}".strip())
        for q in queries[:2]:
            try:
                result = await exa.search(q, num_results=5, text=False)
                for hit in result.hits or []:
                    url = hit.url or ""
                    parsed = urlparse(url)
                    domain = parsed.netloc.lower()
                    if any(skip in domain for skip in ("facebook.com", "instagram.com", "yelp.com", "twitter.com", "linkedin.com", "angi.com", "homeadvisor.com", "nextdoor.com")):
                        continue
                    if domain and not domain.startswith("www."):
                        return url
                    if domain:
                        return url
            except Exception as e:
                logger.debug("website search error for %s: %s", business, e)
        return None

    async def enrich(self, business_name: str, trade: str,
                     location: Optional[str] = None,
                     website: Optional[str] = None,
                     **kwargs) -> EnrichmentResult:
        result = EnrichmentResult(business_name=business_name, trade=trade)
        exa = self._get_exa()
        if not exa:
            result.error = "Exa API key not configured"
            return result

        if not website:
            website = await self._find_website(business_name, trade, location)
        if website:
            result.website = website
            try:
                content_resp = await exa.contents([website], text=True, highlights=True)
                if content_resp.get("ok", True) and "error" not in content_resp:
                    results = content_resp.get("results", [])
                    if results:
                        text = (results[0].get("text") or "") + "\n" + " ".join(results[0].get("highlights") or [])
                        text = text[:5000]
                        emails = list(set(EMAIL_RE.findall(text)))
                        phones = list(set(PHONE_RE.findall(text)))
                        streets = list(set(STREET_RE.findall(text)))
                        if emails:
                            result.email = emails[0]
                            result.sources.append("exa:email")
                        if phones:
                            result.phone = phones[0]
                            result.sources.append("exa:phone")
                        if streets:
                            result.address = streets[0]
                            result.sources.append("exa:address")
                        result.raw_data["exa_content_snippet"] = text[:500]
                        result.confidence = max(result.confidence, 0.3)
            except Exception as e:
                logger.debug("content extract error for %s: %s", website, e)

        result.sources.append("exa_enricher")
        return result
