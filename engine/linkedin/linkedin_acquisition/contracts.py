from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProspectInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=300)
    company: str = Field(default="", max_length=300)
    role: str = Field(default="", max_length=300)
    profile_url: str = Field(min_length=1, max_length=2000)
    source_type: Literal["user_upload", "authorized_connector"]
    source_timestamp: str = Field(min_length=1, max_length=100)
    provenance: dict[str, Any]
    verification_status: Literal["unverified", "pending", "verified", "stale"]
    lawful_or_authorized_basis: str = Field(min_length=1, max_length=500)

    @field_validator("provenance")
    @classmethod
    def provenance_must_not_be_empty(cls, value):
        if not value:
            raise ValueError("provenance is required for every prospect")
        return value


class ProspectImport(BaseModel):
    prospects: list[ProspectInput] = Field(min_length=1, max_length=1000)


class SuppressionCreate(BaseModel):
    channel: Literal["linkedin", "email", "phone", "all"]
    recipient: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=500)
