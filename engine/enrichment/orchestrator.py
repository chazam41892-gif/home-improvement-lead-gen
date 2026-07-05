from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Dict, Any

from .base import EnrichmentResult
from .exa_enricher import ExaEnricher
from .llm_enricher import LLMEnricher
from ..key_vault import KeyVault

logger = logging.getLogger(__name__)


class EnrichOrchestrator:
    def __init__(self):
        self.providers = []
        self._init_providers()

    def _init_providers(self):
        exa = ExaEnricher()
        llm = LLMEnricher()
        if exa.is_available():
            self.providers.append(exa)
        if llm.is_available():
            self.providers.append(llm)

    def list_providers(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.name,
                "available": p.is_available(),
            }
            for p in [ExaEnricher(), LLMEnricher()]
        ]

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
