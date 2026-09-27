import hashlib
import json
from typing import Any


class ContentEngine:
    def __init__(self, store, workflow):
        self.store = store
        self.workflow = workflow

    async def ingest(self, source_type: str, source_text: str,
                     metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        asset = {
            "source_type": source_type,
            "source_text": source_text,
            "metadata": metadata or {},
        }
        insights = await self.workflow.extract_content(asset)
        persisted_metadata = {
            **(metadata or {}),
            "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        }
        stored_source = source_text if persisted_metadata.get("retain_source") is True else ""
        asset_id = self.store.create_content_asset(source_type, stored_source, persisted_metadata, insights)
        draft_ids = []
        for idea in insights.get("ideas", []):
            remix = await self.workflow.remix_content({"asset_id": asset_id, "idea": idea, "metadata": metadata or {}})
            for draft in remix.get("drafts", []):
                if str(draft.get("body", "")).strip():
                    draft_ids.append(self.store.create_content_draft(asset_id, draft))
        return {"asset_id": asset_id, "ideas": len(insights.get("ideas", [])), "drafts_created": len(draft_ids), "draft_ids": draft_ids}

    def approve_draft(self, draft_id: int) -> dict[str, Any]:
        current = self.store.get_content_draft(draft_id)
        if not current:
            raise ValueError("Content draft was not found")
        claims = json.loads(current.get("claims_json") or "[]")
        if claims:
            raise ValueError("Content draft has unresolved claims requiring verification")
        draft = self.store.update_content_draft(draft_id, status="approved")
        if not draft:
            raise ValueError("Content draft was not found")
        return draft

    def reject_draft(self, draft_id: int) -> dict[str, Any]:
        draft = self.store.update_content_draft(draft_id, status="rejected")
        if not draft:
            raise ValueError("Content draft was not found")
        return draft

    async def learn(self, metrics: dict[str, Any]) -> dict[str, Any]:
        draft_id = metrics.get("draft_id")
        if draft_id is not None:
            self.store.update_content_draft(int(draft_id), metrics=metrics)
        result = await self.workflow.learn(metrics)
        self.store.record_run("content_performance", "completed", result)
        return result
