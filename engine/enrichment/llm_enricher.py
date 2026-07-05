from __future__ import annotations

import json
import logging
from typing import Optional, Dict, Any, List

from .base import EnrichmentProvider, EnrichmentResult
from ..key_vault import KeyVault

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class LLMEnricher(EnrichmentProvider):
    name = "llm_enricher"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._provider = None
        self._api_key = None

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

    async def _call_llm(self, system: str, prompt: str) -> Optional[str]:
        import urllib.request, urllib.error
        import json as j

        self._setup()
        if not self._provider:
            return None

        if self._provider == "anthropic":
            body = j.dumps({
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 2000,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(ANTHROPIC_URL, data=body, headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = j.loads(resp.read())
                    return data.get("content", [{}])[0].get("text", "")
            except urllib.error.HTTPError as e:
                logger.warning("Anthropic API error: %s", e.read().decode()[:200])
                return None

        if self._provider == "openai":
            body = j.dumps({
                "model": "gpt-4o-mini",
                "max_tokens": 2000,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }).encode()
            req = urllib.request.Request(OPENAI_URL, data=body, headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = j.loads(resp.read())
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            except urllib.error.HTTPError as e:
                logger.warning("OpenAI API error: %s", e.read().decode()[:200])
                return None

        return None

    async def enrich(self, business_name: str, trade: str,
                     location: Optional[str] = None,
                     website: Optional[str] = None,
                     raw_text: Optional[str] = None,
                     **kwargs) -> EnrichmentResult:
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
            for field in ("contact_name", "title", "phone", "email", "address", "city", "state", "zip", "revenue", "website"):
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
