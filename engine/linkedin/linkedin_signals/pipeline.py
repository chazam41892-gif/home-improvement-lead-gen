import json
from typing import Any

from .models import Engagement, deduplicate_engagements, score_post


class SignalPipeline:
    def __init__(
        self,
        store,
        linkedin,
        qualifier,
        waterfall,
        verifier,
        crm,
        workflow=None,
        compliance_gate=None,
        policy=None,
        offers=None,
        max_engagers: int = 500,
    ):
        self.store = store
        self.linkedin = linkedin
        self.qualifier = qualifier
        self.waterfall = waterfall
        self.verifier = verifier
        self.crm = crm
        self.workflow = workflow
        self.compliance_gate = compliance_gate
        self.policy = policy or {}
        self.offers = offers or []
        self.max_engagers = max(1, int(max_engagers))

    async def run_post(self, post_url: str, source_id: int | None = None) -> dict[str, Any]:
        result = await self.linkedin.collect_post(post_url)
        post = result["post"]
        viral = score_post(
            reactions=int(post.get("reactions", 0)),
            comments=int(post.get("comments", 0)),
            reposts=int(post.get("reposts", 0)),
            age_hours=float(post["age_hours"]) if post.get("age_hours") is not None else None,
        )
        self.store.upsert_post(
            post_urn=post["urn"],
            source_id=source_id,
            post_url=post.get("url", post_url),
            text=post.get("text", ""),
            weighted_engagement=viral.weighted_engagement,
            velocity=viral.velocity,
            raw=post.get("raw", {}),
        )
        stats = {
            "post_urn": post["urn"],
            "viral": viral.is_viral,
            "weighted_engagement": viral.weighted_engagement,
            "velocity": viral.velocity,
            "engagers": 0,
            "qualified": 0,
            "verified": 0,
            "crm_pushed": 0,
            "queued": 0,
            "awaiting_approval": 0,
        }
        if not viral.is_viral:
            self.store.record_run(post_url, "completed", stats)
            return stats
        if self.workflow:
            relevance = await self.workflow.evaluate_post(post, getattr(self.workflow, "target_profile", {}))
            if not relevance.get("relevant"):
                stats["relevance"] = relevance
                self.store.record_run(post_url, "completed", stats)
                return stats
        engagements = [
            Engagement(
                post_urn=post["urn"],
                actor_urn=item.get("actor_urn", ""),
                profile_url=item.get("profile_url", ""),
                action=item.get("action", ""),
                name=item.get("name", ""),
                headline=item.get("headline", ""),
                comment_text=item.get("comment_text", ""),
            )
            for item in result.get("engagements", [])
        ]
        deduped = deduplicate_engagements(engagements)
        stats["engagers_discovered"] = len(deduped)
        deduped = deduped[: self.max_engagers]
        stats["engagers"] = len(deduped)
        stats["engagers_truncated"] = stats["engagers_discovered"] > stats["engagers"]
        for engagement in deduped:
            lead_payload = {
                "identity_key": engagement.identity_key,
                "actor_urn": engagement.actor_urn,
                "profile_url": engagement.profile_url,
                "actions": engagement.actions,
                "name": engagement.name,
                "headline": engagement.headline,
                "comment_text": engagement.comment_text,
            }
            lead_id = self.store.upsert_signal_lead(
                identity_key=engagement.identity_key,
                actor_urn=engagement.actor_urn,
                profile_url=engagement.profile_url,
                source_post_urn=post["urn"],
                action=",".join(engagement.actions),
                name=engagement.name,
                headline=engagement.headline,
                comment_text=engagement.comment_text,
            )
            if self.workflow:
                qualification = await self.workflow.qualify(
                    lead_payload, post, getattr(self.workflow, "target_profile", {})
                )
            else:
                qualification = await self.qualifier.qualify(lead_payload, post)
            self.store.update_lead(
                lead_id, qualification_json=json.dumps(qualification, separators=(",", ":"))
            )
            if not qualification.get("qualified"):
                self.store.update_lead(lead_id, outreach_status="not_qualified")
                continue
            stats["qualified"] += 1
            enriched = await self.waterfall.enrich(lead_payload)
            if not enriched or not enriched.get("email"):
                self.store.update_lead(lead_id, outreach_status="enrichment_failed")
                continue
            email = enriched["email"].strip().lower()
            if self.store.is_suppressed(email):
                self.store.update_lead(lead_id, email=email, outreach_status="suppressed")
                continue
            verification = await self.verifier.verify(email)
            verification_status = str(verification.get("status", "unknown")).lower()
            self.store.update_lead(
                lead_id,
                name=enriched.get("name", ""),
                email=email,
                phone=enriched.get("phone", ""),
                company=enriched.get("company", ""),
                title=enriched.get("title", engagement.headline),
                headline=engagement.headline,
                comment_text=engagement.comment_text,
                enrichment_source=enriched.get("enrichment_source", ""),
                verification_status=verification_status,
            )
            if verification_status not in {"ok", "verified", "valid"}:
                self.store.update_lead(lead_id, outreach_status="verification_failed")
                continue
            stats["verified"] += 1
            if self.workflow:
                reviewed_lead = {
                    **lead_payload,
                    **enriched,
                    "email": email,
                    "verification_status": verification_status,
                }
                offer = await self.workflow.match_offer(reviewed_lead, self.offers)
                self.store.update_lead(lead_id, offer_json=json.dumps(offer, separators=(",", ":")))
                if not offer.get("matched"):
                    self.store.update_lead(lead_id, outreach_status="no_offer_match")
                    continue
                draft = await self.workflow.write_outreach(reviewed_lead, post, offer, self.policy)
                self.store.update_lead(lead_id, outreach_json=json.dumps(draft, separators=(",", ":")))
                deterministic = (
                    self.compliance_gate.evaluate(reviewed_lead, draft, self.policy)
                    if self.compliance_gate
                    else {"approved": False, "missing": ["compliance_gate"], "violations": []}
                )
                if not deterministic.get("approved"):
                    self.store.update_lead(
                        lead_id,
                        compliance_json=json.dumps(
                            {"approved": False, "deterministic": deterministic}, separators=(",", ":")
                        ),
                        outreach_status="compliance_blocked",
                    )
                    continue
                llm_review = await self.workflow.review_compliance(reviewed_lead, draft, self.policy)
                combined_review = {
                    "approved": bool(deterministic.get("approved") and llm_review.get("approved")),
                    "deterministic": deterministic,
                    "llm_review": llm_review,
                }
                self.store.update_lead(
                    lead_id, compliance_json=json.dumps(combined_review, separators=(",", ":"))
                )
                if not combined_review["approved"]:
                    self.store.update_lead(lead_id, outreach_status="compliance_blocked")
                    continue
            crm_result = await self.crm.create_lead(
                name=enriched.get("name", ""),
                email=email,
                source="linkedin_signal",
                phone=enriched.get("phone", ""),
                company=enriched.get("company", ""),
            )
            crm_lead = crm_result.get("lead", {}) if isinstance(crm_result, dict) else {}
            self.store.update_lead(
                lead_id,
                crm_lead_id=crm_lead.get("id", ""),
                outreach_status="awaiting_approval",
            )
            stats["crm_pushed"] += 1
            stats["awaiting_approval"] += 1
        self.store.record_run(post_url, "completed", stats)
        return stats
