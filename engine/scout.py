from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .router import SmartRouter
from .search.browser_agent import BrowserSearchProvider
from .search.exa import ExaSearchProvider
from .search.perplexity import PerplexitySearchProvider
from .utils.export import export_to_csv, export_to_json
from .utils.scoring import LeadScore, score_lead

logger = logging.getLogger("LeadScout")


@dataclass
class SearchConfig:
    query: str = ""
    industry: str = ""
    location: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    num_results: int = 25
    min_score: float = 30.0
    search_type: str = "auto"
    provider: str = "exa"
    include_domains: list[str] = field(default_factory=lambda: [
        "yelp.com", "bbb.org", "angi.com", "homeadvisor.com",
        "maps.google.com", "linkedin.com", "facebook.com",
    ])
    exclude_domains: list[str] = field(default_factory=lambda: [
        "pinterest.com", "amazon.com", "wikipedia.org",
        "instagram.com", "tiktok.com",
    ])

    def build_search_query(self) -> str:
        parts = []
        if self.industry:
            parts.append(self.industry)
        if self.query:
            parts.append(self.query)
        else:
            parts.extend(["contractors", "services", "business"])
        if self.location:
            parts.append(f"in {self.location}")
        elif self.city and self.state:
            parts.append(f"in {self.city}, {self.state}")
        elif self.city:
            parts.append(f"in {self.city}")
        elif self.zip_code:
            parts.append(f"near {self.zip_code}")
        return " ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "industry": self.industry,
            "location": self.location,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "num_results": self.num_results,
            "min_score": self.min_score,
            "search_type": self.search_type,
        }


@dataclass
class LeadResult:
    id: str
    title: str
    url: str
    snippet: str
    industry: str
    location: str
    source: str
    score: LeadScore
    found_at: str
    email: str = ""
    phone: str = ""
    notes: str = ""
    # CRITICAL (audit 2026-09-27): these fields were missing here, but
    # LeadScoutEngine.update_lead() admits them in its allowlist and then gates on
    # `hasattr(lead, key)`. A search-discovered lead therefore silently DISCARDED
    # every PATCH of status / first_name / consent fields and answered 200, so the
    # UI showed the new value and a reload lost it. They mirror _CaptureLead in
    # engine/capture.py, which is the shape the leads table was written for.
    first_name: str = ""
    last_name: str = ""
    address: str = ""
    project_description: str = ""
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    status: str = "new"
    sms_consent: int = 1
    email_consent: int = 1
    call_consent: int = 1
    consent_source: str = "form"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet[:300],
            "industry": self.industry,
            "location": self.location,
            "source": self.source,
            "score": self.score.total,
            "contact_score": self.score.contact_completeness,
            "business_score": self.score.business_presence,
            "industry_score": self.score.industry_relevance,
            "location_score": self.score.location_match,
            "enrichment_score": self.score.enrichment_potential,
            "score_breakdown": self.score.as_dict(),
            "found_at": self.found_at,
            "email": self.email,
            "phone": self.phone,
            "notes": self.notes,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "address": self.address,
            "project_description": self.project_description,
            "utm_source": self.utm_source,
            "utm_medium": self.utm_medium,
            "utm_campaign": self.utm_campaign,
            "status": self.status,
            "sms_consent": self.sms_consent,
            "email_consent": self.email_consent,
            "call_consent": self.call_consent,
            "consent_source": self.consent_source,
        }


class LeadScoutEngine:
    def __init__(self, exa_api_key: str | None = None,
                 perplexity_api_key: str | None = None):
        self._exa: ExaSearchProvider | None = None
        self._perplexity: PerplexitySearchProvider | None = None
        self._browser = BrowserSearchProvider()
        if exa_api_key:
            self._exa = ExaSearchProvider(api_key=exa_api_key)
        if perplexity_api_key:
            self._perplexity = PerplexitySearchProvider(api_key=perplexity_api_key)
        self._leads: dict[str, LeadResult] = {}
        self._search_history: list[dict[str, Any]] = []
        self._router = SmartRouter()
        self._env: dict[str, str] = {}
        self._router.set_env(self._env)

    def set_exa_key(self, api_key: str):
        self._exa = ExaSearchProvider(api_key=api_key)

    def set_perplexity_key(self, api_key: str):
        self._perplexity = PerplexitySearchProvider(api_key=api_key)

    def set_env(self, env: dict[str, str]):
        self._env.update(env)
        self._router.set_env(self._env)

    def set_routing_config(self, config: dict[str, Any]):
        self._router.load_config(config)

    def get_routing_config(self) -> dict[str, Any]:
        return self._router.get_config()

    def update_routing_step(self, name: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        return self._router.update_step(name, updates)

    def get_routing_stats(self) -> dict[str, Any]:
        return self._router.get_stats()

    def get_routing_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._router.get_routing_history(limit=limit)

    def register_enrichment_fn(self, fn):
        self._router.register_enrichment_fn(fn)

    def register_llm_score_fn(self, fn):
        self._router.register_llm_score_fn(fn)

    @property
    def has_exa_key(self) -> bool:
        return self._exa is not None and bool(self._exa.api_key)

    @property
    def has_perplexity_key(self) -> bool:
        return self._perplexity is not None and bool(self._perplexity.api_key)

    async def search(self, config: SearchConfig) -> dict[str, Any]:
        provider_name = config.provider or "exa"

        if provider_name == "perplexity":
            if not self._perplexity or not self._perplexity.api_key:
                return {"ok": False, "error": "Perplexity API key not configured. Add it in Settings.", "leads": [], "count": 0}
            search_fn = self._perplexity.search
            logger.info(f"Searching (Perplexity): {config.build_search_query()}")
        elif provider_name == "browser":
            search_fn = self._browser.search
            logger.info(f"Searching (Browser): {config.build_search_query()}")
        else:
            if not self.has_exa_key:
                return {"ok": False, "error": "Exa API key not configured. Add it in Settings.", "leads": [], "count": 0}
            search_fn = self._exa.search
            logger.info(f"Searching (Exa): {config.build_search_query()}")

        query = config.build_search_query()
        t0 = time.time()

        result = await search_fn(
            query=query,
            num_results=config.num_results,
            search_type=config.search_type,
        )

        elapsed = time.time() - t0

        if result.error:
            logger.error(f"Search error: {result.error}")
            return {"ok": False, "error": result.error, "leads": [], "count": 0, "elapsed_sec": elapsed}

        leads: list[LeadResult] = []
        seen_urls: set[str] = set()

        for hit in result.hits:
            clean_url = hit.url.rstrip("/")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            ls = score_lead(
                title=hit.title,
                snippet=hit.snippet,
                url=hit.url,
                target_industry=config.industry or None,
                target_city=config.city or None,
                target_state=config.state or None,
                target_zip=config.zip_code or None,
            )

            if ls.total < config.min_score:
                continue

            lead = LeadResult(
                id=str(uuid.uuid4())[:12],
                title=hit.title,
                url=hit.url,
                snippet=hit.snippet,
                industry=config.industry or "general",
                location=config.location or f"{config.city}, {config.state}".strip(", "),
                source=result.provider,
                score=ls,
                found_at=datetime.now().isoformat(),
            )
            leads.append(lead)

        leads.sort(key=lambda lead: lead.score.total, reverse=True)

        for lead in leads:
            self._leads[lead.id] = lead

        search_record = {
            "timestamp": datetime.now().isoformat(),
            "config": config.as_dict(),
            "query": query,
            "results_count": len(leads),
            "elapsed_sec": round(elapsed, 2),
        }
        self._search_history.append(search_record)

        logger.info(f"Found {len(leads)} qualified leads in {elapsed:.1f}s")

        lead_dicts = [lead.as_dict() for lead in leads]

        route_result = await self._router.route_leads(
            lead_dicts,
            search_config=config.as_dict(),
        )

        for routed_lead in route_result["leads"]:
            lid = routed_lead.get("id")
            existing = self._leads.get(lid) if lid else None
            if existing:
                if routed_lead.get("enriched"):
                    existing.notes = routed_lead.get("notes") or existing.notes
                if routed_lead.get("llm_score"):
                    pass

        return {
            "ok": True,
            "query": query,
            "count": len(route_result["leads"]),
            "elapsed_sec": round(elapsed, 2),
            "total_hits": len(result.hits),
            "leads": route_result["leads"],
            "pipeline": route_result["pipeline"],
        }

    async def search_natural(self, natural_query: str, num_results: int = 25,
                             min_score: float = 30.0, provider: str = "exa") -> dict[str, Any]:
        parsed = self._parse_natural_query(natural_query)

        config = SearchConfig(
            query=parsed.get("query", natural_query),
            industry=parsed.get("industry", ""),
            location=parsed.get("location", ""),
            city=parsed.get("city", ""),
            state=parsed.get("state", ""),
            zip_code=parsed.get("zip_code", ""),
            num_results=num_results,
            min_score=min_score,
            provider=provider,
        )

        return await self.search(config)

    def _parse_natural_query(self, text: str) -> dict[str, str]:
        lower = text.lower()
        result: dict[str, str] = {}

        industry_keywords = {
            "roofing": ["roof", "roofing", "roofer", "shingle"],
            "plumbing": ["plumb", "plumber", "pipe", "drain"],
            "hvac": ["hvac", "heating", "cooling", "ac", "air conditioning", "furnace"],
            "electrical": ["electric", "electrical", "electrician", "wiring"],
            "construction": ["construction", "contractor", "builder", "general contractor"],
            "landscaping": ["landscap", "lawn", "garden", "tree service"],
            "solar": ["solar", "panel"],
            "painting": ["paint", "painter"],
            "windows": ["window", "siding", "door"],
            "kitchen & bath": ["kitchen", "bathroom", "remodel", "cabinet"],
            "fencing": ["fence", "deck"],
            "concrete": ["concrete", "paving", "asphalt"],
            "cleaning": ["clean", "janitorial", "pressure wash"],
            "pest control": ["pest", "exterminat", "termite"],
            "moving": ["moving", "mover"],
            "real estate": ["real estate", "realtor", "real estate agent", "property"],
            "land_developer": ["land developer", "land acquisition", "land buyer", "property developer",
                               "subdivision", "lot builder", "home builder", "tract home",
                               "developer buying land", "land investment", "master planned"],
            "church": ["church", "ministry", "worship"],
        }

        found_industries = []
        for ind, keywords in industry_keywords.items():
            if any(kw in lower for kw in keywords):
                found_industries.append(ind)

        if found_industries:
            result["industry"] = found_industries[0]

        state_abbrs = [
            "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
            "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
            "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
            "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
            "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
        ]

        location = text
        for ind in found_industries:
            location = location.replace(ind, "", 1).strip()
        for prefix in ["find me", "find", "search for", "get me", "i need", "look for", "show me"]:
            if location.startswith(prefix):
                location = location[len(prefix):].strip()
        location = location.replace(" in ", "|").replace(" near ", "|").replace(" around ", "|")
        parts = [p.strip() for p in location.split("|") if p.strip()]
        if parts:
            result["location"] = parts[-1]
            loc_lower = result["location"].lower()
            for abbr in state_abbrs:
                pattern = f" {abbr}"
                if pattern in loc_lower or loc_lower.endswith(abbr):
                    result["state"] = abbr.upper()
                    city_part = loc_lower.replace(abbr, "").strip().strip(",").strip()
                    if city_part:
                        result["city"] = city_part.title()
                    break

            if not result.get("state"):
                us_states_full = [
                    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
                    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
                    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
                    "maine", "maryland", "massachusetts", "michigan", "minnesota",
                    "mississippi", "missouri", "montana", "nebraska", "nevada",
                    "new hampshire", "new jersey", "new mexico", "new york",
                    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
                    "pennsylvania", "rhode island", "south carolina", "south dakota",
                    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
                    "west virginia", "wisconsin", "wyoming",
                ]
                for full in us_states_full:
                    if full in loc_lower:
                        result["state"] = full.title()

        zip_pattern = r'\b(\d{5})\b'
        import re
        zip_match = re.search(zip_pattern, text)
        if zip_match:
            result["zip_code"] = zip_match.group(1)

        if not found_industries and not result.get("location"):
            result["query"] = text

        return result

    def get_leads(self, limit: int = 100, min_score: float = 0) -> list[dict[str, Any]]:
        sorted_leads = sorted(
            self._leads.values(),
        key=lambda lead: lead.score.total,
            reverse=True,
        )
        filtered = [lead for lead in sorted_leads if lead.score.total >= min_score]
        return [lead.as_dict() for lead in filtered[:limit]]

    def get_lead_by_id(self, lead_id: str) -> dict[str, Any] | None:
        lead = self._leads.get(lead_id)
        return lead.as_dict() if lead else None

    def update_lead(self, lead_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        lead = self._leads.get(lead_id)
        if not lead:
            return None
        allowed = {
            "title", "snippet", "industry", "location", "source", "email", "phone",
            "notes", "status", "first_name", "last_name", "address", "project_description",
            "utm_source", "utm_medium", "utm_campaign",
            "sms_consent", "email_consent", "call_consent", "consent_source",
        }
        for key, val in updates.items():
            if key in allowed and hasattr(lead, key):
                setattr(lead, key, val)
        # Persist updated lead to DB
        try:
            from engine.persistence import save_leads
            save_leads({lead_id: lead})
        except Exception as e:
            logger.error("Failed to persist updated lead: %s", e)
        return lead.as_dict()

    def delete_lead(self, lead_id: str) -> bool:
        ok = self._leads.pop(lead_id, None) is not None
        try:
            from engine.database import Database
            with Database.get_connection() as conn:
                conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
                conn.commit()
        except Exception as e:
            logger.error("Failed to delete lead from database: %s", e)
        return ok

    def clear_leads(self):
        self._leads.clear()
        try:
            from engine.database import Database
            with Database.get_connection() as conn:
                conn.execute("DELETE FROM leads")
                conn.commit()
        except Exception as e:
            logger.error("Failed to clear leads from database: %s", e)

    def export_csv(self, min_score: float = 0) -> str:
        leads = self.get_leads(min_score=min_score)
        return export_to_csv(leads)

    def export_json(self, min_score: float = 0) -> str:
        leads = self.get_leads(min_score=min_score)
        return export_to_json(leads)

    def get_stats(self) -> dict[str, Any]:
        if not self._leads:
            return {"total": 0, "avg_score": 0, "by_industry": {}, "searches_run": len(self._search_history)}

        scores = [lead.score.total for lead in self._leads.values()]
        by_industry: dict[str, int] = {}
        for lead in self._leads.values():
            ind = lead.industry or "unknown"
            by_industry[ind] = by_industry.get(ind, 0) + 1

        return {
            "total": len(self._leads),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "max_score": round(max(scores), 1) if scores else 0,
            "by_industry": by_industry,
            "searches_run": len(self._search_history),
        }

    def get_search_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._search_history[-limit:]
