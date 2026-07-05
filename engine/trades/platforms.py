import asyncio
import json
import logging
import os
from typing import Optional

from .base import TradeLead

logger = logging.getLogger(__name__)

_exa_provider: Optional["ExaSearchProvider"] = None


def set_exa_provider(provider: "ExaSearchProvider"):
    global _exa_provider
    _exa_provider = provider


def _get_provider():
    if _exa_provider is not None:
        return _exa_provider
    from ..search.exa import ExaSearchProvider
    return ExaSearchProvider()


async def search_google_maps(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    base_query = f"{trade} {location}"
    leads = []
    seen = set()
    queries = [
        f"best {trade} in {location}",
        f"{trade} near {location}",
        f"top rated {trade} {location}",
        f"{trade} services {location}",
    ]
    provider = _get_provider()
    for query in queries[:3]:
        try:
            result = await provider.search(query, num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                if hit.title and trade.lower() in hit.title.lower():
                    leads.append(TradeLead(
                        business_name=hit.title,
                        website=hit.url,
                        source="google_maps",
                        trade=trade,
                        notes=hit.snippet[:300],
                    ))
        except Exception as e:
            logger.warning("google_maps search error for %s: %s", query, e)
    return leads


async def search_homeadvisor(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:homeadvisor.com {trade} {location}",
        f"site:homeadvisor.com/cost {trade} {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["homeadvisor.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title.replace(" - HomeAdvisor", "").strip(),
                    website=hit.url,
                    source="homeadvisor",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("homeadvisor search error: %s", e)
    return leads


async def search_angi(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:angi.com {trade} {location}",
        f"site:angi.com/listing {trade} {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["angi.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title.split(" | ")[0].strip(),
                    website=hit.url,
                    source="angi",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("angi search error: %s", e)
    return leads


async def search_yelp(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:yelp.com {trade} {location}",
        f"best {trade} yelp {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["yelp.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title.replace(" - Yelp", "").strip(),
                    website=hit.url,
                    source="yelp",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("yelp search error: %s", e)
    return leads


async def search_facebook(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:facebook.com {trade} {location}",
        f"site:facebook.com/marketplace {trade} {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["facebook.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title,
                    website=hit.url,
                    source="facebook",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("facebook search error: %s", e)
    return leads


async def search_nextdoor(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:nextdoor.com {trade} {location}",
        f"site:nextdoor.com/pages {trade} {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["nextdoor.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title,
                    website=hit.url,
                    source="nextdoor",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("nextdoor search error: %s", e)
    return leads


async def search_instagram(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:instagram.com {trade} {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["instagram.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title,
                    website=hit.url,
                    source="instagram",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("instagram search error: %s", e)
    return leads


async def search_houzz(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:houzz.com {trade} {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["houzz.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title,
                    website=hit.url,
                    source="houzz",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("houzz search error: %s", e)
    return leads


PLATFORM_SEARCHERS = {
    "google_maps": search_google_maps,
    "homeadvisor": search_homeadvisor,
    "angi": search_angi,
    "yelp": search_yelp,
    "facebook": search_facebook,
    "nextdoor": search_nextdoor,
    "instagram": search_instagram,
    "houzz": search_houzz,
}
