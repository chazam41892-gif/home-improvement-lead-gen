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


async def search_linkedin(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:linkedin.com/company {trade} {location}",
        f"site:linkedin.com/in {trade} developer {location}",
        f"site:linkedin.com/company land acquisition {location}",
        f"site:linkedin.com/company real estate development {location}",
    ]
    provider = _get_provider()
    for query in queries[:3]:
        try:
            result = await provider.search(query, include_domains=["linkedin.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                name = hit.title
                for suffix in (" | LinkedIn", " - LinkedIn", " |linkedin", " on LinkedIn"):
                    name = name.replace(suffix, "").strip()
                leads.append(TradeLead(
                    business_name=name,
                    website=hit.url,
                    source="linkedin",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("linkedin search error: %s", e)
    return leads


async def search_apollo(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    from ..key_vault import KeyVault
    import httpx

    api_key = KeyVault.get("apollo")
    if not api_key:
        logger.debug("Apollo API key not configured — skipping apollo platform search")
        return []

    title_map = {
        "land_developer": [
            "VP Land Acquisition", "Director of Land Acquisition", "Land Acquisition Manager",
            "VP of Development", "Director of Development", "Chief Development Officer",
            "Land Buyer", "VP Real Estate", "Director of Real Estate",
            "Land Entitlement Manager", "VP Acquisitions", "Director of Acquisitions",
            "President", "CEO", "Owner",
        ],
    }
    titles = title_map.get(trade, ["President", "CEO", "Owner", "VP Acquisitions", "Director of Development"])

    body = {
        "api_key": api_key,
        "q_keywords": f"{trade} {location}",
        "person_titles": titles,
        "per_page": min(max_results, 25),
        "page": 1,
    }
    if location:
        body["organization_locations"] = [location]

    leads = []
    seen = set()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/mixed_people/search",
                json=body,
                headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
            )
            resp.raise_for_status()
            data = resp.json()
        for person in data.get("people", []):
            org = person.get("organization", {}) or {}
            name = org.get("name") or " ".join(filter(None, [person.get("first_name", ""), person.get("last_name", "")]))
            if name in seen:
                continue
            seen.add(name)
            contact_name = " ".join(filter(None, [person.get("first_name", ""), person.get("last_name", "")]))
            lead = TradeLead(
                business_name=name,
                website=org.get("primary_domain") or org.get("website_url") or "",
                source="apollo",
                trade=trade,
                notes=f"{person.get('title', 'N/A')} at {org.get('name', 'N/A')}",
            )
            lead.email = person.get("email") or ""
            lead.phone = (person.get("phone_numbers") or [""])[0] if person.get("phone_numbers") else ""
            leads.append(lead)
    except Exception as e:
        logger.warning("apollo platform search error: %s", e)
    return leads


async def search_zillow(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:zillow.com land for sale {location}",
        f"site:zillow.com lots for sale {location}",
        f"site:zillow.com vacant land {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["zillow.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title.replace(" - Zillow", "").replace(" | Zillow", "").strip(),
                    website=hit.url,
                    source="zillow",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("zillow search error: %s", e)
    return leads


async def search_loopnet(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:loopnet.com land for sale {location}",
        f"site:loopnet.com development site {location}",
        f"site:loopnet.com vacant land {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["loopnet.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title.replace(" - LoopNet", "").replace(" | LoopNet", "").strip(),
                    website=hit.url,
                    source="loopnet",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("loopnet search error: %s", e)
    return leads


async def search_landwatch(trade: str, location: str, max_results: int = 25) -> list[TradeLead]:
    leads = []
    seen = set()
    queries = [
        f"site:landwatch.com land for sale {location}",
        f"site:landwatch.com developer lots {location}",
    ]
    provider = _get_provider()
    for query in queries:
        try:
            result = await provider.search(query, include_domains=["landwatch.com"], num_results=min(10, max_results))
            for hit in result.hits or []:
                key = hit.url or hit.title
                if key in seen:
                    continue
                seen.add(key)
                leads.append(TradeLead(
                    business_name=hit.title.replace(" - LandWatch", "").replace(" | LandWatch", "").strip(),
                    website=hit.url,
                    source="landwatch",
                    trade=trade,
                    notes=hit.snippet[:300],
                ))
        except Exception as e:
            logger.warning("landwatch search error: %s", e)
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
    "linkedin": search_linkedin,
    "apollo": search_apollo,
    "zillow": search_zillow,
    "loopnet": search_loopnet,
    "landwatch": search_landwatch,
}
