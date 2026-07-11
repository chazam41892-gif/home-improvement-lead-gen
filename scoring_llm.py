from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx

from engine.key_vault import KeyVault

ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
COMETAPI_MODEL = "claude-sonnet-4-20250514"

PROMPT_TEMPLATE = """
You are an expert lead‑qualification analyst.

Lead Data:
{lead_json}

Instructions:
1. Produce a single numeric score from 0 (worst) to 100 (best).
2. Provide a short 1‑2 sentence rationale.
3. Return the result as valid JSON with keys: `score`, `rationale`.

Example output:
{{
  "score": 87,
  "rationale": "Strong contact completeness and clear industry match; website present."
}}
"""


async def _score_via_anthropic(lead: Dict[str, Any], model: str) -> Dict[str, Any]:
    api_key = KeyVault.get("anthropic")
    if not api_key:
        return {"score": 0, "rationale": "ANTHROPIC_API_KEY not set"}
    payload = {
        "model": model,
        "max_tokens": 512,
        "temperature": 0.1,
        "messages": [
            {"role": "user", "content": PROMPT_TEMPLATE.format(lead_json=json.dumps(lead, indent=2))}
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
        if resp.status_code != 200:
            return {"score": 0, "rationale": f"Anthropic error {resp.status_code}"}
        data = resp.json()
        content = data.get("content", [{}])[0].get("text", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"score": 0, "rationale": "Anthropic returned malformed JSON"}


async def _score_via_cometapi(lead: Dict[str, Any], model: str) -> Dict[str, Any]:
    api_key = KeyVault.get("cometapi")
    if not api_key:
        api_key = os.environ.get("COMETAPI_API_KEY")
    if not api_key:
        return {"score": 0, "rationale": "COMETAPI_API_KEY not set"}
    payload = {
        "model": model,
        "max_tokens": 512,
        "temperature": 0.1,
        "messages": [
            {"role": "user", "content": PROMPT_TEMPLATE.format(lead_json=json.dumps(lead, indent=2))}
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post("https://api.cometapi.com/v1/chat/completions", json=payload, headers=headers)
        if resp.status_code != 200:
            return {"score": 0, "rationale": f"CometAPI error {resp.status_code}"}
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"score": 0, "rationale": "CometAPI returned malformed JSON"}


async def llm_score_lead(lead: Dict[str, Any], *,
                         provider: str = "anthropic",
                         model: Optional[str] = None) -> Dict[str, Any]:
    if provider == "cometapi":
        return await _score_via_cometapi(lead, model or COMETAPI_MODEL)
    return await _score_via_anthropic(lead, model or ANTHROPIC_MODEL)


async def score_leads_batch(leads: List[Dict[str, Any]], *,
                            provider: str = "anthropic",
                            model: Optional[str] = None) -> List[Dict[str, Any]]:
    import asyncio
    tasks = [llm_score_lead(lead, provider=provider, model=model) for lead in leads]
    return await asyncio.gather(*tasks)
