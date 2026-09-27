import json
from collections.abc import Iterable
from typing import Any

from .prompts import render_prompt


class WorkflowContractError(RuntimeError):
    pass


def _parse_json_object(raw: Any, node: str) -> dict[str, Any]:
    cleaned = str(raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise WorkflowContractError(f"{node} returned invalid JSON") from error
    if not isinstance(parsed, dict):
        raise WorkflowContractError(f"{node} returned a non-object response")
    return parsed


class PromptWorkflow:
    def __init__(self, llm_func):
        self.llm_func = llm_func

    async def _run(self, node: str, payload: dict[str, Any], required: Iterable[str]):
        if not self.llm_func:
            raise WorkflowContractError(f"{node} requires a configured LLM")
        raw = await self.llm_func(
            render_prompt(node, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        )
        result = _parse_json_object(raw, node)
        missing = [key for key in required if key not in result]
        if missing:
            raise WorkflowContractError(f"{node} omitted required fields: {', '.join(missing)}")
        return result

    async def evaluate_post(self, post: dict[str, Any], target_profile: dict[str, Any]):
        return await self._run(
            "post_relevance", {"post": post, "target_profile": target_profile}, ("relevant", "reason")
        )

    async def select_sources(
        self, target_profile: dict[str, Any], candidate_accounts, existing_source_accounts
    ):
        return await self._run(
            "source_account_selection",
            {
                "target_profile": target_profile,
                "candidate_accounts": candidate_accounts,
                "existing_source_accounts": existing_source_accounts,
            },
            ("selected", "rejected"),
        )

    async def qualify(self, lead: dict[str, Any], post: dict[str, Any], target_profile: dict[str, Any]):
        return await self._run(
            "lead_qualification",
            {"lead": lead, "post": post, "target_profile": target_profile},
            ("qualified", "reason"),
        )

    async def match_offer(self, lead: dict[str, Any], offers):
        return await self._run(
            "offer_matching", {"lead": lead, "approved_offers": offers}, ("matched", "offer_id", "reason")
        )

    async def write_outreach(
        self, lead: dict[str, Any], post: dict[str, Any], offer: dict[str, Any], policy: dict[str, Any]
    ):
        return await self._run(
            "personalized_outreach",
            {"lead": lead, "post": post, "offer": offer, "sender_policy": policy},
            ("subject", "body_text", "requires_human_review"),
        )

    async def review_compliance(self, lead: dict[str, Any], draft: dict[str, Any], policy: dict[str, Any]):
        return await self._run(
            "compliance_review",
            {"lead": lead, "draft": draft, "policy": policy},
            ("approved", "violations", "lawful_basis_status"),
        )

    async def classify_reply(self, reply: dict[str, Any]):
        return await self._run(
            "reply_classification", reply, ("primary_label", "must_suppress", "requires_human")
        )

    async def extract_content(self, asset: dict[str, Any]):
        return await self._run("content_extraction", asset, ("ideas",))

    async def remix_content(self, insight: dict[str, Any]):
        return await self._run("content_remix", insight, ("drafts",))

    async def learn(self, metrics: dict[str, Any]):
        return await self._run("performance_learning", metrics, ("findings", "next_tests"))


class ComplianceGate:
    required_policy_fields = (
        "lawful_basis",
        "sender_name",
        "business_name",
        "postal_address",
        "opt_out_text",
    )

    def evaluate(self, lead: dict[str, Any], draft: dict[str, Any], policy: dict[str, Any]):
        missing = [field for field in self.required_policy_fields if not str(policy.get(field, "")).strip()]
        violations = []
        if str(lead.get("verification_status", "")).lower() not in {"ok", "valid", "verified"}:
            violations.append("email_not_verified")
        opt_out_text = str(policy.get("opt_out_text", "")).strip()
        if opt_out_text and opt_out_text.lower() not in str(draft.get("body_text", "")).lower():
            violations.append("opt_out_missing_from_body")
        if not str(draft.get("subject", "")).strip() or not str(draft.get("body_text", "")).strip():
            violations.append("draft_incomplete")
        return {"approved": not missing and not violations, "missing": missing, "violations": violations}
