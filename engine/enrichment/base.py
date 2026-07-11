from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class EnrichmentResult:
    business_name: str
    trade: str
    contact_name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    website: Optional[str] = None
    employee_count: Optional[int] = None
    revenue: Optional[str] = None
    year_founded: Optional[int] = None
    social_links: Dict[str, str] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)
    confidence: float = 0.0
    error: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None or k in ("sources", "social_links", "raw_data")}


class EnrichmentProvider:
    name: str = "base"
    """Fields this provider works best with, in order of preference."""
    input_preferences: List[str] = []
    """Fields this provider absolutely needs to produce useful output."""
    input_required: List[str] = []
    """Lower = tried first in smart routing mode."""
    priority: int = 10

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    async def enrich(self, business_name: str, trade: str,
                     location: Optional[str] = None,
                     website: Optional[str] = None,
                     phone: Optional[str] = None,
                     **kwargs) -> EnrichmentResult:
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
