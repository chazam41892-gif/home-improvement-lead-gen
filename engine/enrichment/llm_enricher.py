from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..key_vault import KeyVault
from .base import EnrichmentProvider, EnrichmentResult

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class LLMEnricher(EnrichmentProvider):
    name = "llm_enricher"
    input_preferences = ["raw_text", "website", "business_name"]
    input_required = ["business_name"]
    priority = 2

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._provider: str | None = None
        self._api_key: str | None = None

    def is_available(self) -> bool:
        return bool(KeyVault.get("anthropic") or KeyVault.get("openai"))

    def _setup(self):
        if self._provider:
            return
        key = KeyVault.get("anthropic")
        if key:
            self._provider = "anthropic"
            self._api_key = key
            return
        key = KeyVault.get("openai")
        if key:
            self._provider = "openai"
            self._api_key = key

    def _model_name(self) -> str:
        if self._provider == "anthropic":
            return self.config.get("anthropic_model", "claude-sonnet-4-20250514")
        return self.config.get("openai_model", "gpt-4o-mini")

    async def _call_llm(self, system: str, prompt: str) -> str | None:
        self._setup()
        # _provider is only ever set in a branch that also assigns a truthy
        # _api_key, so this guard is a no-op on every reachable path; it exists
        # to narrow the optional key for the header dicts below.
        api_key = self._api_key
        if not self._provider or not api_key:
            return None

        async with httpx.AsyncClient(timeout=30.0) as client:
            if self._provider == "anthropic":
                body = {
                    "model": self._model_name(),
                    "max_tokens": 2000,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                }
                try:
                    resp = await client.post(
                        ANTHROPIC_URL,
                        json=body,
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # `or [{}]` not `, [{}]`: the default only applies when the
                    # key is ABSENT. Anthropic returns content:[] when a content
                    # filter trips, and the old form raised IndexError, which
                    # _call_llm does not catch -- so it escaped enrich().
                    return (data.get("content") or [{}])[0].get("text", "")
                except httpx.HTTPStatusError as e:
                    logger.warning("Anthropic API error: %s", e.response.text[:200])
                    return None

            if self._provider == "openai":
                body = {
                    "model": self._model_name(),
                    "max_tokens": 2000,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                }
                try:
                    resp = await client.post(
                        OPENAI_URL,
                        json=body,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # Same `or [{}]` reasoning as the Anthropic branch above:
                    # an empty choices list is a real API response, not a
                    # missing key.
                    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                except httpx.HTTPStatusError as e:
                    logger.warning("OpenAI API error: %s", e.response.text[:200])
                    return None

        return None

    async def enrich(
        self,
        business_name: str,
        trade: str,
        location: str | None = None,
        website: str | None = None,
        phone: str | None = None,
        raw_text: str | None = None,
        **kwargs,
    ) -> EnrichmentResult:
        # `phone` is declared for LSP compliance with EnrichmentProvider.enrich
        # (this provider reads raw page text, not a caller-supplied phone).
        # `raw_text` is provider-specific and must follow the base's parameters.
        result = EnrichmentResult(business_name=business_name, trade=trade)
        if not self.is_available():
            result.error = "No LLM API key configured (anthropic or openai)"
            return result

        prompt = f"""Extract structured contact information from the following business data.

Business Name: {business_name}
Trade: {trade}
Location: {location or "unknown"}

Raw Data:
{raw_text[:4000] if raw_text else "No raw data provided."}

Return ONLY a JSON object with these fields (use null for missing):
- contact_name
- title (position/role)
- phone
- email
- address
- city
- state
- zip
- employee_count (number)
- revenue (string like "$1M-$5M")
- year_founded (number)
- confidence (0.0 to 1.0 — how sure you are about this data)
"""

        system = "You are a business data extraction engine. Extract structured contact info from unstructured business data. Return ONLY valid JSON. No explanation."

        response = await self._call_llm(system, prompt)
        if not response:
            result.error = "LLM returned no response"
            return result

        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            data = json.loads(cleaned.strip())
            for field in (
                "contact_name",
                "title",
                "phone",
                "email",
                "address",
                "city",
                "state",
                "zip",
                "revenue",
                "website",
            ):
                val = data.get(field)
                if val:
                    setattr(result, field, str(val))
            for field in ("employee_count", "year_founded"):
                val = data.get(field)
                if val is not None:
                    setattr(result, field, int(val))
            conf = data.get("confidence")
            if conf is not None:
                result.confidence = float(conf)
            result.sources.append(f"llm:{self._provider}")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("LLM parsing error: %s", e)
            result.error = f"LLM output parse failed: {e}"
            result.raw_data["llm_raw_response"] = response[:500]

        return result
