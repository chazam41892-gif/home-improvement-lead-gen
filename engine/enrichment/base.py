from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnrichmentResult:
    business_name: str
    trade: str
    contact_name: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    website: str | None = None
    employee_count: int | None = None
    revenue: str | None = None
    year_founded: int | None = None
    social_links: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    error: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            k: v
            for k, v in self.__dict__.items()
            if v is not None or k in ("sources", "social_links", "raw_data")
        }


class EnrichmentProvider:
    name: str = "base"
    """Fields this provider works best with, in order of preference."""
    input_preferences: list[str] = []
    """Fields this provider absolutely needs to produce useful output."""
    input_required: list[str] = []
    """Lower = tried first in smart routing mode."""
    priority: int = 10

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def enrich(
        self,
        business_name: str,
        trade: str,
        location: str | None = None,
        website: str | None = None,
        phone: str | None = None,
        **kwargs,
    ) -> EnrichmentResult:
        raise NotImplementedError

    def is_available(self) -> bool:
        return True

    def suitability_score(self, input_fields: set) -> float:
        """Score 0.0–1.0 how well-suited this provider is for the given input fields."""
        required = set(self.input_required)
        if required and not required.issubset(input_fields):
            return 0.0
        if not self.input_preferences:
            return 1.0
        matched = sum(1 for f in self.input_preferences if f in input_fields)
        return matched / len(self.input_preferences)
