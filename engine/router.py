from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("SmartRouter")


DEFAULT_ROUTING_CONFIG: Dict[str, Any] = {
    "steps": [
        {
            "name": "dedup",
            "label": "Deduplicate",
            "description": "Skip leads with duplicate URLs",
            "enabled": True,
            "config": {},
        },
        {
            "name": "score",
            "label": "Rule-Based Scoring",
            "description": "5-dimension scoring (contact, business, industry, location, enrichment)",
            "enabled": True,
            "config": {"min_score": 30},
        },
        {
            "name": "enrich",
            "label": "Apollo / Exa Enrichment",
            "description": "Enrich leads with email, phone, company data via Apollo, Exa, and LLM",
            "enabled": False,
            "keys_required": [],
            "config": {"batch_size": 25},
        },
        {
            "name": "llm_score",
            "label": "LLM Confidence Scoring",
            "description": "Score top leads through Claude AI for deep qualification",
            "enabled": False,
            "keys_required": ["ANTHROPIC_API_KEY"],
            "config": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "max_leads": 10,
                "min_rule_score": 50,
                "temperature": 0.1,
            },
        },
        {
            "name": "crm_push",
            "label": "CRM Auto-Push",
            "description": "Auto-push high-scoring leads to HubSpot / GoHighLevel",
            "enabled": False,
            "keys_required": [],
            "config": {
                "provider": "hubspot",
                "min_score": 70,
                "max_per_batch": 25,
            },
        },
    ],
}


@dataclass
class RoutingStep:
    name: str
    label: str
    description: str
    enabled: bool
    config: Dict[str, Any]
    keys_required: List[str] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "enabled": self.enabled,
            "config": self.config,
            "keys_required": self.keys_required,
        }


class SmartRouter:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._steps: Dict[str, RoutingStep] = {}
        self._env: Dict[str, str] = {}
        self._routing_history: List[Dict[str, Any]] = []
        self._enrich_fn = None
        self._llm_score_fn = None
        self._notify_fn = None
        self.load_config(config or DEFAULT_ROUTING_CONFIG)

    def load_config(self, config: Dict[str, Any]):
        self._steps.clear()
        for step_data in config.get("steps", []):
            step = RoutingStep(
                name=step_data["name"],
                label=step_data.get("label", step_data["name"]),
                description=step_data.get("description", ""),
                enabled=step_data.get("enabled", True),
                config=step_data.get("config", {}),
                keys_required=step_data.get("keys_required", []),
            )
            self._steps[step.name] = step

    def get_config(self) -> Dict[str, Any]:
        return {
            "steps": [s.as_dict() for s in self._steps.values()],
        }

    def update_step(self, name: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        step = self._steps.get(name)
        if not step:
            return None
        if "enabled" in updates:
            step.enabled = bool(updates["enabled"])
        if "config" in updates and isinstance(updates["config"], dict):
            step.config.update(updates["config"])
        return step.as_dict()

    def set_env(self, env: Dict[str, str]):
        self._env = env

    def register_enrichment_fn(self, fn):
        self._enrich_fn = fn

    def register_llm_score_fn(self, fn):
        self._llm_score_fn = fn

    def register_crm_push_fn(self, fn):
        self._crm_push_fn = fn

    def _check_keys(self, step: RoutingStep) -> List[str]:
        if step.name == "llm_score":
            provider = step.config.get("provider", "anthropic")
            if provider == "cometapi":
                if not (self._env.get("COMETAPI_API_KEY") or ""):
                    return ["COMETAPI_API_KEY"]
            else:
                if not (self._env.get("ANTHROPIC_API_KEY") or ""):
                    return ["ANTHROPIC_API_KEY"]
            return []

        missing = []
        for key in step.keys_required:
            val = self._env.get(key) or ""
            if not val:
                missing.append(key)
        return missing

    async def route_leads(self, leads: List[Dict[str, Any]],
                          search_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        t0 = time.time()
        pipeline_log: Dict[str, Any] = {
            "input_count": len(leads),
            "steps_run": [],
            "steps_skipped": [],
            "errors": [],
        }

        current = list(leads)

        step_order = ["dedup", "score", "enrich", "llm_score", "crm_push"]

        for step_name in step_order:
            step = self._steps.get(step_name)
            if not step or not step.enabled:
                pipeline_log["steps_skipped"].append(step_name)
                continue

            missing_keys = self._check_keys(step)
            if missing_keys:
                logger.warning(f"Step '{step_name}' skipped: missing keys {missing_keys}")
                pipeline_log["steps_skipped"].append(f"{step_name} (missing: {missing_keys})")
                continue

            try:
                if step_name == "dedup":
                    current = self._run_dedup(current)
                elif step_name == "score":
                    current = await self._run_score(current, step, search_config)
                elif step_name == "enrich":
                    current = await self._run_enrich(current, step)
                elif step_name == "llm_score":
                    current = await self._run_llm_score(current, step)
                elif step_name == "crm_push":
                    current = await self._run_crm_push(current, step)

                step.results = {"output_count": len(current)}
                pipeline_log["steps_run"].append(step_name)
                logger.info(f"Step '{step_name}': {len(current)} leads")
            except Exception as e:
                logger.error(f"Step '{step_name}' error: {e}")
                pipeline_log["errors"].append(f"{step_name}: {e}")

        elapsed = time.time() - t0
        pipeline_log["output_count"] = len(current)
        pipeline_log["elapsed_sec"] = round(elapsed, 2)
        self._routing_history.append(pipeline_log)

        return {
            "leads": current,
            "pipeline": pipeline_log,
        }

    def _run_dedup(self, leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: Set[str] = set()
        deduped = []
        for lead in leads:
            url = (lead.get("url") or "").rstrip("/")
            title = (lead.get("title") or "").lower().strip()
            key = url or title
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(lead)
        return deduped

    async def _run_score(self, leads: List[Dict[str, Any]], step: RoutingStep,
                         search_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        min_score = step.config.get("min_score", 0)
        filtered = [l for l in leads if (l.get("score") or 0) >= min_score]
        return filtered

    async def _run_enrich(self, leads: List[Dict[str, Any]], step: RoutingStep) -> List[Dict[str, Any]]:
        if not self._enrich_fn:
            logger.warning("Enrich step enabled but no enrichment function registered")
            return leads
        batch_size = step.config.get("batch_size", 25)
        enriched = []
        for i in range(0, len(leads), batch_size):
            batch = leads[i:i + batch_size]
            tasks = [self._enrich_fn(lead) for lead in batch]
            import asyncio
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for lead, result in zip(batch, results):
                if isinstance(result, dict):
                    lead["enriched"] = True
                    for k, v in result.items():
                        if v and k not in ("url", "id", "score"):
                            lead[k] = v
                enriched.append(lead)
        return enriched

    async def _run_llm_score(self, leads: List[Dict[str, Any]], step: RoutingStep) -> List[Dict[str, Any]]:
        if not self._llm_score_fn:
            logger.warning("LLM scoring enabled but no llm_score function registered")
            return leads
        max_leads = step.config.get("max_leads", 10)
        min_rule_score = step.config.get("min_rule_score", 50)
        provider = step.config.get("provider", "anthropic")
        model = step.config.get("model")

        candidates = [l for l in leads if (l.get("score") or 0) >= min_rule_score]
        candidates.sort(key=lambda l: l.get("score", 0), reverse=True)
        to_score = candidates[:max_leads]

        if not to_score:
            return leads

        scores = await self._llm_score_fn(to_score, provider=provider, model=model)
        for lead, llm_result in zip(to_score, scores):
            lead["llm_score"] = llm_result.get("score", 0)
            lead["llm_rationale"] = llm_result.get("rationale", "")
            lead["llm_provider"] = provider
            if lead.get("llm_score") and lead.get("score"):
                lead["score"] = round((lead["score"] * 0.6 + lead["llm_score"] * 0.4), 1)

        return leads

    async def _run_crm_push(self, leads: List[Dict[str, Any]], step: RoutingStep) -> List[Dict[str, Any]]:
        min_score = step.config.get("min_score", 70)
        max_per = step.config.get("max_per_batch", 25)
        provider = step.config.get("provider", "hubspot")

        to_push = [l for l in leads if (l.get("score") or 0) >= min_score][:max_per]
        if to_push:
            logger.info("CRM push (%s): %d leads ready", provider, len(to_push))
            fn = getattr(self, "_crm_push_fn", None)
            if fn:
                try:
                    await fn(to_push, {"provider": provider, "min_score": min_score})
                    logger.info("CRM push (%s): completed for %d leads", provider, len(to_push))
                except Exception as e:
                    logger.error("CRM push (%s) failed: %s", provider, e)
            else:
                logger.warning("CRM push function not registered — leads not pushed")

        return leads

    def get_routing_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._routing_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        total_input = sum(h.get("input_count", 0) for h in self._routing_history)
        total_output = sum(h.get("output_count", 0) for h in self._routing_history)
        total_errors = sum(len(h.get("errors", [])) for h in self._routing_history)
        return {
            "runs": len(self._routing_history),
            "total_input": total_input,
            "total_output": total_output,
            "total_errors": total_errors,
            "enabled_steps": [s.name for s in self._steps.values() if s.enabled],
        }
