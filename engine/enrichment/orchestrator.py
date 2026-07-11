from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .base import EnrichmentProvider, EnrichmentResult
from .apollo_enricher import ApolloEnricher
from .exa_enricher import ExaEnricher
from .llm_enricher import LLMEnricher
from ..key_vault import KeyVault

logger = logging.getLogger(__name__)


@dataclass
class ProviderRoute:
    provider: EnrichmentProvider
    suitability: float = 0.0
    selected: bool = False


class EnrichmentRouter:
    """Selects the best enrichment providers for a given lead's input fields."""

    def __init__(self, min_confidence: float = 0.3, fallthrough: bool = True):
        self.min_confidence = min_confidence
        self.fallthrough = fallthrough

    def rank_providers(self, providers: List[EnrichmentProvider],
                       input_fields: set) -> List[ProviderRoute]:
        scored = []
        for p in providers:
            score = p.suitability_score(input_fields)
            priority_boost = max(0, (10 - p.priority)) / 10.0
            combined = round(score * 0.7 + priority_boost * 0.3, 2)
            scored.append(ProviderRoute(provider=p, suitability=combined))
        scored.sort(key=lambda r: r.suitability, reverse=True)
        return scored

    def routing_plan(self, providers: List[EnrichmentProvider],
                     input_fields: set) -> List[ProviderRoute]:
        ranked = self.rank_providers(providers, input_fields)
        selected = False
        for route in ranked:
            if route.suitability <= 0:
                continue
            if route.suitability >= 0.3:
                route.selected = True
                selected = True
            elif not selected:
                route.selected = True
                selected = True
        return ranked

    def as_dict(self) -> Dict[str, Any]:
        return {
            "strategy": "suitability",
            "min_confidence": self.min_confidence,
            "fallthrough": self.fallthrough,
        }


class EnrichOrchestrator:
    def __init__(self, routing_mode: str = "parallel"):
        self.providers = []
        self.routing_mode = routing_mode
        self.router = EnrichmentRouter()
        self._provider_enabled: Dict[str, bool] = {}
        self._init_providers()

    def _init_providers(self):
        self.providers = []
        for cls, name in [(ApolloEnricher, "apollo_enricher"), (ExaEnricher, "exa_enricher"), (LLMEnricher, "llm_enricher")]:
            if not self._provider_enabled.get(name, True):
                continue
            instance = cls()
            if instance.is_available():
                self.providers.append(instance)

    def list_providers(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "available": p.is_available(),
                "enabled": self._provider_enabled.get(p.name, True),
                "priority": p.priority,
                "input_preferences": p.input_preferences,
                "input_required": p.input_required,
            }
            for p in [ApolloEnricher(), ExaEnricher(), LLMEnricher()]
        ]

    def set_provider_enabled(self, service: str, enabled: bool) -> bool:
        valid = {"apollo_enricher", "exa_enricher", "llm_enricher"}
        if service not in valid:
            return False
        self._provider_enabled[service] = enabled
        self._init_providers()
        return True

    def get_routing_info(self) -> Dict[str, Any]:
        input_fields = set()
        for p in self.providers:
            input_fields.update(p.input_preferences)
            input_fields.update(p.input_required)
        return {
            "routing_mode": self.routing_mode,
            "router": self.router.as_dict(),
            "providers": self.list_providers(),
            "known_input_fields": sorted(input_fields),
        }

    async def enrich(self, business_name: str, trade: str,
                     location: Optional[str] = None,
                     website: Optional[str] = None,
                     phone: Optional[str] = None,
                     **kwargs) -> EnrichmentResult:
        if not self.providers:
            logger.warning("No enrichment providers available")
            return EnrichmentResult(
                business_name=business_name,
                trade=trade,
                error="No enrichment providers available. Configure API keys in the Key Vault.",
            )

        if self.routing_mode == "smart":
            return await self._enrich_smart(
                business_name=business_name, trade=trade,
                location=location, website=website, phone=phone, **kwargs,
            )

        return await self._enrich_parallel(
            business_name=business_name, trade=trade,
            location=location, website=website, phone=phone, **kwargs,
        )

    async def _enrich_parallel(self, business_name: str, trade: str,
                               location: Optional[str] = None,
                               website: Optional[str] = None,
                               phone: Optional[str] = None,
                               **kwargs) -> EnrichmentResult:
        results = await asyncio.gather(
            *(p.enrich(business_name=business_name, trade=trade, location=location, website=website, phone=phone, **kwargs)
              for p in self.providers),
            return_exceptions=True,
        )
        merged = EnrichmentResult(business_name=business_name, trade=trade)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Enrichment provider error: %s", r)
                continue
            if isinstance(r, EnrichmentResult):
                merged = self._merge(merged, r)
        self._score_confidence(merged)
        return merged

    async def _enrich_smart(self, business_name: str, trade: str,
                            location: Optional[str] = None,
                            website: Optional[str] = None,
                            phone: Optional[str] = None,
                            **kwargs) -> EnrichmentResult:
        input_fields = {k for k, v in locals().items() if k != "self" and v is not None}
        if "kwargs" in input_fields:
            input_fields.remove("kwargs")
        input_fields.update(k for k, v in kwargs.items() if v is not None)

        plan = self.router.routing_plan(self.providers, input_fields)
        selected = [r for r in plan if r.selected]

        logger.info("Smart routing plan for %s: %s", business_name,
                     [{"provider": r.provider.name, "suitability": r.suitability, "selected": r.selected} for r in plan])

        if not selected:
            logger.warning("No suitable providers for lead %s (fields: %s)", business_name, input_fields)
            return EnrichmentResult(
                business_name=business_name, trade=trade,
                error=f"No suitable enrichment provider for available inputs: {sorted(input_fields)}",
            )

        merged = EnrichmentResult(business_name=business_name, trade=trade)
        for route in selected:
            if route.provider not in self.providers:
                continue
            result = await route.provider.enrich(
                business_name=business_name, trade=trade,
                location=location, website=website, phone=phone, **kwargs,
            )
            merged = self._merge(merged, result)
            if self.router.fallthrough and merged.confidence >= self.router.min_confidence:
                logger.info("Smart routing: %s reached confidence %.2f (>=%.2f), stopping",
                            route.provider.name, merged.confidence, self.router.min_confidence)
                break
        self._score_confidence(merged)
        return merged

    def _merge(self, target: EnrichmentResult, source: EnrichmentResult) -> EnrichmentResult:
        for field in ("contact_name", "title", "phone", "email", "address", "city", "state", "zip", "website", "revenue"):
            existing = getattr(target, field)
            new_val = getattr(source, field)
            if new_val and not existing:
                setattr(target, field, new_val)
            elif new_val and existing and new_val != existing:
                existing = str(existing)
                if len(str(new_val)) > len(existing):
                    setattr(target, field, new_val)
        for field in ("employee_count", "year_founded"):
            existing = getattr(target, field)
            new_val = getattr(source, field)
            if new_val is not None and existing is None:
                setattr(target, field, new_val)
        target.sources.extend(s for s in source.sources if s not in target.sources)
        if source.website and not target.website:
            target.website = source.website
        if source.confidence > target.confidence:
            target.confidence = source.confidence
        if source.error:
            target.error = source.error
        if source.raw_data:
            target.raw_data.update(source.raw_data)
        return target

    def _score_confidence(self, result: EnrichmentResult):
        fields = 0
        filled = 0
        for f in ("contact_name", "phone", "email", "address", "website", "employee_count"):
            fields += 1
            if getattr(result, f):
                filled += 1
        if fields > 0:
            result.confidence = max(result.confidence, round(filled / fields, 2))

    async def enrich_batch(self, leads: List[Dict[str, Any]]) -> List[EnrichmentResult]:
        return await asyncio.gather(
            *(self.enrich(**lead) for lead in leads),
            return_exceptions=True,
        )


_orchestrator: Optional[EnrichOrchestrator] = None


def get_orchestrator() -> EnrichOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EnrichOrchestrator()
    return _orchestrator


async def enrich_lead(business_name: str, trade: str,
                      location: Optional[str] = None,
                      website: Optional[str] = None,
                      phone: Optional[str] = None,
                      **kwargs) -> EnrichmentResult:
    return await get_orchestrator().enrich(
        business_name=business_name,
        trade=trade,
        location=location,
        website=website,
        phone=phone,
        **kwargs,
    )
