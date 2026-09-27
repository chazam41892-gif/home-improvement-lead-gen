import hashlib
import os
from pathlib import Path
from typing import Any

from engine.linkedin.linkedin_signals.models import canonicalize_linkedin_url

from .catalog import get_catalog
from .store import AcquisitionStore


class FeatureDisabledError(RuntimeError):
    pass


class ResourceNotFoundError(RuntimeError):
    pass


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_db_path():
    return Path(__file__).resolve().parents[4] / "data" / "linkedin_acquisition.db"


class LinkedInAcquisitionService:
    def __init__(self, store=None, enabled=None):
        self.enabled = (
            _truthy(os.environ.get("SIOS_LINKEDIN_ACQUISITION_ENGINE_ENABLED", "false"))
            if enabled is None
            else enabled
        )
        self._store = store
        self._db_path = os.environ.get("SIOS_LINKEDIN_ACQUISITION_DB", str(_default_db_path()))

    @property
    def store(self):
        if self._store is None:
            self._store = AcquisitionStore(self._db_path)
        return self._store

    def _require_enabled(self):
        if not self.enabled:
            raise FeatureDisabledError("LinkedIn acquisition engine is disabled")

    def _workspace(self, tenant_id: str, workspace_id: str):
        workspace = self.store.get_workspace(tenant_id, workspace_id)
        if not workspace:
            raise ResourceNotFoundError("Acquisition workspace was not found")
        return workspace

    def status(self):
        catalog = get_catalog()
        return {
            "enabled": self.enabled,
            "feature_flag": "SIOS_LINKEDIN_ACQUISITION_ENGINE_ENABLED",
            "outbound_enabled": False,
            "capability_count": catalog["capability_count"],
            "method_count": catalog["method_count"],
            "authorized_sources": ["user_upload", "authorized_connector"],
            "prohibited_sources": ["linkedin_scrape", "browser_automation", "access_control_bypass"],
            "stats": self.store.stats()
            if self.enabled
            else {"workspaces": 0, "prospects": 0, "suppressions": 0},
        }

    def create_workspace(self, tenant_id: str, request, idempotency_key: str):
        self._require_enabled()
        operation = "workspace.create"
        cached = self.store.get_idempotent(tenant_id, operation, idempotency_key)
        if cached is not None:
            return cached
        workspace = self.store.create_workspace(tenant_id, request.name, request.settings)
        self.store.audit(
            tenant_id, workspace["id"], "leadgen.workspace.created", {"workspace_id": workspace["id"]}
        )
        response = {"workspace": workspace}
        self.store.record_idempotent(tenant_id, operation, idempotency_key, response)
        return response

    def get_workspace(self, tenant_id: str, workspace_id: str):
        return self._workspace(tenant_id, workspace_id)

    def import_prospects(self, tenant_id: str, workspace_id: str, request, idempotency_key: str):
        self._require_enabled()
        self._workspace(tenant_id, workspace_id)
        operation = f"prospects.import:{workspace_id}"
        cached = self.store.get_idempotent(tenant_id, operation, idempotency_key)
        if cached is not None:
            return cached
        created = 0
        duplicates = 0
        suppressed = 0
        for item in request.prospects:
            prospect = item.model_dump()
            prospect["profile_url"] = canonicalize_linkedin_url(prospect["profile_url"])
            if self.store.is_suppressed(tenant_id, workspace_id, "linkedin", prospect["profile_url"]):
                suppressed += 1
                self.store.audit(
                    tenant_id,
                    workspace_id,
                    "leadgen.prospect.suppressed",
                    {"profile_url_sha256": hashlib.sha256(prospect["profile_url"].encode()).hexdigest()},
                )
                continue
            if self.store.add_prospect(tenant_id, workspace_id, prospect):
                created += 1
                self.store.audit(
                    tenant_id,
                    workspace_id,
                    "leadgen.prospect.imported",
                    {
                        "source_type": prospect["source_type"],
                        "verification_status": prospect["verification_status"],
                    },
                )
            else:
                duplicates += 1
        response = {"created": created, "duplicates": duplicates, "suppressed": suppressed}
        self.store.record_idempotent(tenant_id, operation, idempotency_key, response)
        return response

    def list_prospects(self, tenant_id: str, workspace_id: str):
        self._workspace(tenant_id, workspace_id)
        prospects = self.store.list_prospects(tenant_id, workspace_id)
        return {"prospects": prospects, "count": len(prospects)}

    def suppress(self, tenant_id: str, workspace_id: str, request, idempotency_key: str):
        self._require_enabled()
        self._workspace(tenant_id, workspace_id)
        operation = f"suppression.create:{workspace_id}"
        cached = self.store.get_idempotent(tenant_id, operation, idempotency_key)
        if cached is not None:
            return cached
        recipient = request.recipient.strip().lower()
        if request.channel in {"linkedin", "all"}:
            recipient = canonicalize_linkedin_url(recipient)
        record = self.store.suppress(
            tenant_id, workspace_id, request.channel, recipient, request.reason.strip()
        )
        self.store.audit(
            tenant_id,
            workspace_id,
            "leadgen.prospect.suppressed",
            {"channel": request.channel, "recipient_sha256": hashlib.sha256(recipient.encode()).hexdigest()},
        )
        response = {"suppression": record}
        self.store.record_idempotent(tenant_id, operation, idempotency_key, response)
        return response

    def list_suppressions(self, tenant_id: str, workspace_id: str):
        self._workspace(tenant_id, workspace_id)
        records = self.store.list_suppressions(tenant_id, workspace_id)
        return {"suppressions": records, "count": len(records)}

    def list_audit(self, tenant_id: str, workspace_id: str):
        self._workspace(tenant_id, workspace_id)
        events = self.store.list_audit(tenant_id, workspace_id)
        return {"events": events, "count": len(events)}


def capability_catalog() -> dict[str, Any]:
    return get_catalog()
