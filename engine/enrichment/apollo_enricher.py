from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode

import httpx

from .base import EnrichmentProvider, EnrichmentResult
from ..key_vault import KeyVault

logger = logging.getLogger(__name__)

APOLLO_BASE = "https://api.apollo.io/v1"


class ApolloEnricher(EnrichmentProvider):
    name = "apollo_enricher"
    input_preferences = ["business_name", "website", "location"]
    input_required = []
    priority = 0

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._api_key: Optional[str] = None

    def _get_key(self) -> Optional[str]:
        if self._api_key:
            return self._api_key
        key = KeyVault.get("apollo")
        if key:
            self._api_key = key
        return self._api_key

    def is_available(self) -> bool:
        return bool(self._get_key())

    async def _mixed_people_search(self, keywords: str,
                                    organization_name: Optional[str] = None,
                                    page: int = 1,
                                    per_page: int = 5) -> List[Dict[str, Any]]:
        api_key = self._get_key()
        if not api_key:
            return []

        body: Dict[str, Any] = {
            "api_key": api_key,
            "q_keywords": keywords,
            "page": page,
            "per_page": per_page,
        }
        if organization_name:
            body["q_organization_names"] = [organization_name]

        person_titles = self.config.get("person_titles")
        if person_titles:
            body["person_titles"] = person_titles

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{APOLLO_BASE}/mixed_people/search",
                    json=body,
                    headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("people", [])[:per_page]
        except Exception as e:
            logger.warning("Apollo people search error: %s", e)
            return []

    async def _organization_enrich(self, domain: str) -> Optional[Dict[str, Any]]:
        api_key = self._get_key()
        if not api_key:
            return None

        body = {
            "api_key": api_key,
            "domain": domain,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{APOLLO_BASE}/organizations/enrich",
                    json=body,
                    headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("organization", data)
        except Exception as e:
            logger.debug("Apollo org enrich error for %s: %s", domain, e)
            return None

    async def enrich(self, business_name: str, trade: str,
                     location: Optional[str] = None,
                     website: Optional[str] = None,
                     **kwargs) -> EnrichmentResult:
        result = EnrichmentResult(business_name=business_name, trade=trade)
        if not self._get_key():
            result.error = "Apollo API key not configured"
            return result

        keywords_parts = [business_name]
        if trade:
            keywords_parts.append(trade)
        if location:
            keywords_parts.append(location)
        keywords = " ".join(keywords_parts)

        people = await self._mixed_people_search(
            keywords=keywords,
            organization_name=business_name if business_name else None,
        )

        if people:
            person = people[0]
            result.contact_name = " ".join(filter(None, [
                person.get("first_name", ""),
                person.get("last_name", ""),
            ])) or None
            result.title = person.get("title") or person.get("subtitle") or None
            result.email = person.get("email") or None
            result.phone = person.get("phone_numbers", [""])[0] if person.get("phone_numbers") else None

            org = person.get("organization", {}) or {}
            if org:
                if not result.website:
                    result.website = org.get("primary_domain") or org.get("website_url") or None
                if not result.employee_count:
                    raw_count = org.get("employee_count")
                    if raw_count:
                        try:
                            result.employee_count = int(raw_count)
                        except (ValueError, TypeError):
                            pass
                result.revenue = org.get("annual_revenue_printed") or None
                if not result.revenue:
                    revenue = org.get("annual_revenue")
                    if revenue:
                        try:
                            result.revenue = f"${int(revenue):,}"
                        except (ValueError, TypeError):
                            pass
                org_name = org.get("name", "")
                if org_name and not result.contact_name:
                    result.contact_name = org_name

            result.confidence = min(1.0, 0.4 + (0.2 if result.email else 0) + (0.2 if result.phone else 0) + (0.2 if result.website else 0))
            result.sources.append("apollo:people_search")
            result.raw_data["apollo_person"] = {
                "id": person.get("id"),
                "name": result.contact_name,
                "title": result.title,
                "email": result.email,
                "organization": org.get("name") if org else None,
            }

        if website and not result.website:
            from urllib.parse import urlparse
            parsed = urlparse(website)
            domain = parsed.netloc.replace("www.", "") if parsed.netloc else website
            org_data = await self._organization_enrich(domain)
            if org_data:
                result.website = org_data.get("primary_domain") or website
                if not result.employee_count:
                    raw = org_data.get("employee_count")
                    if raw:
                        try:
                            result.employee_count = int(raw)
                        except (ValueError, TypeError):
                            pass
                if not result.revenue:
                    result.revenue = org_data.get("annual_revenue_printed") or None
                result.sources.append("apollo:org_enrich")
                result.raw_data["apollo_org"] = {
                    "name": org_data.get("name"),
                    "domain": org_data.get("primary_domain"),
                    "employees": org_data.get("employee_count"),
                }

        if not result.sources:
            result.confidence = 0.0
            result.error = "No results found in Apollo"

        return result