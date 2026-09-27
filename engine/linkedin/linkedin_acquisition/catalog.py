from copy import deepcopy

_CAPABILITIES = (
    ("S1", "authority_content", (
        ("hook_diagnostic", "Diagnose whether an opening earns attention without unsupported claims."),
        ("structure_editor", "Restructure an authority post for clarity, evidence, and audience relevance."),
        ("cta_rewriter", "Produce call-to-action alternatives matched to the approved offer."),
    )),
    ("S2", "prospect_intelligence", (
        ("signal_extractor", "Separate verified prospect signals from inference."),
        ("outreach_angle_ranker", "Rank evidence-backed outreach angles for operator review."),
        ("conversation_starter_builder", "Draft non-deceptive conversation starters from verified signals."),
    )),
    ("S3", "profile_conversion", (
        ("positioning_audit", "Audit profile positioning against the configured ICP and offer."),
        ("headline_rewriter", "Draft profile headline options grounded in supplied proof."),
        ("about_section_rewriter", "Draft an evidence-backed profile about section."),
    )),
    ("S4", "lead_magnet_builder", (
        ("concept_generator", "Generate lead-magnet concepts from supplied pains and evidence."),
        ("cta_builder", "Draft a lead-magnet call to action."),
        ("delivery_sequence_builder", "Draft an approval-gated delivery sequence."),
    )),
    ("S5", "market_positioning_intelligence", (
        ("pattern_mapper", "Map patterns in authorized competitor material with citations."),
        ("positioning_gap_finder", "Identify evidence-backed positioning gaps."),
        ("differentiation_builder", "Draft differentiated positioning options without fabricated proof."),
    )),
    ("S6", "outbound_optimizer", (
        ("performance_diagnostic", "Diagnose campaign performance without claiming unsupported causation."),
        ("fix_prioritizer", "Prioritize measurable campaign improvements."),
        ("value_followup_rewriter", "Draft value-led follow-ups for exact-payload approval."),
    )),
    ("S7", "discovery_to_proposal", (
        ("notes_structurer", "Structure authorized discovery notes while minimizing sensitive data."),
        ("proposal_angle_generator", "Generate proposal angles within supplied pricing rules."),
        ("objection_followup_builder", "Draft evidence-backed objection follow-ups."),
    )),
    ("S8", "content_engine", (
        ("authority_pillar_mapper", "Map authority pillars to the configured niche, ICP, and proof."),
        ("calendar_builder", "Build an approval-queued content calendar."),
        ("format_rotator", "Rotate content formats without repeating unsupported claims."),
    )),
    ("S9", "engagement_intelligence", (
        ("pattern_analyzer", "Analyze first-party engagement patterns and limitations."),
        ("timing_recommender", "Recommend timing experiments from first-party data."),
        ("opportunity_ranker", "Rank content opportunities by evidence and confidence."),
    )),
    ("S10", "acquisition_architect", (
        ("bottleneck_diagnostic", "Diagnose measurable funnel bottlenecks."),
        ("automation_mapper", "Map safe automation candidates and required approvals."),
        ("improvement_sequencer", "Sequence improvements by impact, evidence, and risk."),
    )),
)


def _method(capability_id, name, purpose):
    approval = "exact_payload" if any(token in name for token in ("rewriter", "builder", "generator")) else "operator_review"
    return {
        "method_id": f"{capability_id}.{name}",
        "version": "1.0.0",
        "purpose": purpose,
        "trigger": "authenticated_operator_request",
        "required_inputs": ["workspace_id", "evidence"],
        "optional_inputs": ["operator_context", "constraints"],
        "validation_rules": ["workspace_is_tenant_scoped", "evidence_has_provenance"],
        "process_steps": ["validate", "separate_facts_from_inference", "produce_structured_output", "verify"],
        "output_schema": {
            "observed_facts": "array",
            "inferences": "array",
            "missing_information": "array",
            "confidence": "number_0_to_1",
            "machine_output": "object",
            "human_draft": "string_or_null",
        },
        "scoring_rubric": {"version": "1.0.0", "dimensions": ["evidence", "relevance", "clarity"]},
        "uncertainty_policy": "State uncertainty and missing inputs; never promote inference to fact.",
        "verification_rules": ["claims_reference_evidence", "unsupported_claims_block_approval"],
        "approval_requirement": approval,
        "metrics": ["approval_rate", "human_edit_distance", "unsupported_claim_rate"],
        "failure_modes": ["missing_provenance", "insufficient_evidence", "policy_blocked", "model_unavailable"],
    }


CAPABILITY_CATALOG = tuple(
    {
        "id": capability_id,
        "name": name,
        "methods": tuple(_method(capability_id, method_name, purpose) for method_name, purpose in methods),
    }
    for capability_id, name, methods in _CAPABILITIES
)


def get_catalog():
    capabilities = deepcopy(CAPABILITY_CATALOG)
    return {
        "capability_count": len(capabilities),
        "method_count": sum(len(item["methods"]) for item in capabilities),
        "capabilities": capabilities,
    }
