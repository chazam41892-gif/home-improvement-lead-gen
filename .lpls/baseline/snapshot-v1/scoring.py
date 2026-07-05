from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class LeadScore:
    total: float = 0.0
    contact_completeness: float = 0.0
    business_presence: float = 0.0
    industry_relevance: float = 0.0
    location_match: float = 0.0
    enrichment_potential: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "contact_completeness": round(self.contact_completeness, 1),
            "business_presence": round(self.business_presence, 1),
            "industry_relevance": round(self.industry_relevance, 1),
            "location_match": round(self.location_match, 1),
            "enrichment_potential": round(self.enrichment_potential, 1),
            "breakdown": self.details,
        }


INDUSTRY_KEYWORDS: Dict[str, List[str]] = {
    "roofing": ["roof", "roofing", "shingle", "gutter", "roofer"],
    "plumbing": ["plumb", "pipe", "drain", "sewer", "water heater", "faucet"],
    "hvac": ["hvac", "heating", "cooling", "air conditioning", "furnace", "ac repair"],
    "electrical": ["electric", "electrical", "wiring", "circuit", "panel"],
    "construction": ["construction", "contractor", "builder", "remodel", "general contractor"],
    "landscaping": ["landscap", "lawn", "garden", "tree service", "hardscape"],
    "solar": ["solar", "panel installation", "photovoltaic"],
    "painting": ["paint", "painter", "painting contractor"],
    "kitchen_bath": ["kitchen", "bathroom", "remodel", "cabinet", "countertop"],
    "windows": ["window", "siding", "door", "glass"],
    "fencing": ["fence", "fencing", "deck"],
    "concrete": ["concrete", "asphalt", "paving", "masonry"],
    "cleaning": ["cleaning", "janitorial", "pressure wash"],
    "pest_control": ["pest", "exterminat", "termite"],
    "moving": ["moving", "mover", "relocation", "trucking"],
}

INDUSTRY_WEIGHTS: Dict[str, float] = {
    "roofing": 1.0, "hvac": 1.0, "plumbing": 1.0, "electrical": 1.0,
    "solar": 0.95, "kitchen_bath": 0.9, "windows": 0.9,
    "construction": 0.85, "landscaping": 0.8, "painting": 0.8,
    "fencing": 0.7, "concrete": 0.75, "cleaning": 0.65,
    "pest_control": 0.7, "moving": 0.6,
}


def score_contact_completeness(title: str, snippet: str, url: str) -> float:
    score = 0.0
    combined = f"{title} {snippet}".lower()

    if title and len(title) > 5:
        score += 25
    if snippet and len(snippet) > 20:
        score += 15

    phone_patterns = [
        r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
    ]
    for pat in phone_patterns:
        if re.search(pat, combined):
            score += 25
            break

    email_patterns = [r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b']
    for pat in email_patterns:
        if re.search(pat, combined):
            score += 20
            break

    if any(domain in url for domain in [".com", ".net", ".org", ".io", ".us", ".co"]):
        score += 15

    return min(score, 100)


def score_business_presence(title: str, snippet: str) -> float:
    score = 0.0
    combined = f"{title} {snippet}".lower()

    years_pattern = r'\b(\d+)\s*(year|yr)s?\b'
    years_match = re.search(years_pattern, combined)
    if years_match:
        try:
            years = int(years_match.group(1))
            if years >= 5: score += 20
            if years >= 10: score += 20
        except ValueError:
            pass

    trust_signals = [
        "bbb", "accredited", "licensed", "insured", "bonded",
        "award", "top rated", "best of", "5-star", "recommended",
        "family owned", "locally owned", "since",
    ]
    for signal in trust_signals:
        if signal in combined:
            score += 8

    presence_signals = [
        "free estimate", "free quote", "call now", "contact us",
        "service area", "satisfaction guaranteed", "warranty",
    ]
    for signal in presence_signals:
        if signal in combined:
            score += 5

    return min(score, 100)


def score_industry_relevance(title: str, snippet: str, target_industry: Optional[str] = None) -> float:
    combined = f"{title} {snippet}".lower()

    if target_industry:
        target_lower = target_industry.lower()
        keywords = INDUSTRY_KEYWORDS.get(target_lower, [target_lower])
        match_count = sum(1 for kw in keywords if kw.lower() in combined)
        if match_count > 0:
            score = min(match_count * 20, 100)
            weight = INDUSTRY_WEIGHTS.get(target_lower, 0.7)
            return score * weight
        return 10.0

    best_score = 0.0
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw.lower() in combined)
        weight = INDUSTRY_WEIGHTS.get(industry, 0.5)
        score = min(match_count * 20, 100) * weight
        best_score = max(best_score, score)

    return best_score


def score_location_match(snippet: str, target_city: Optional[str] = None,
                         target_state: Optional[str] = None, target_zip: Optional[str] = None) -> float:
    if not target_city and not target_state and not target_zip:
        return 50.0

    combined = snippet.lower()
    score = 0.0

    if target_city and target_city.lower() in combined:
        score += 40
    if target_state and target_state.lower() in combined:
        score += 30
    if target_zip and target_zip in combined:
        score += 30

    return min(score, 100)


def score_enrichment_potential(url: str) -> float:
    score = 0.0

    if url and url.startswith("http"):
        score += 30

    social_domains = {
        "linkedin.com": 25, "facebook.com": 15, "instagram.com": 10,
        "twitter.com": 10, "youtube.com": 10, "yelp.com": 15,
        "bbb.org": 20, "angi.com": 15, "homeadvisor.com": 15,
    }
    for domain, pts in social_domains.items():
        if domain in url.lower():
            score += pts

    return min(score, 100)


def score_lead(title: str, snippet: str, url: str,
               target_industry: Optional[str] = None,
               target_city: Optional[str] = None,
               target_state: Optional[str] = None,
               target_zip: Optional[str] = None) -> LeadScore:
    contact = score_contact_completeness(title, snippet, url)
    business = score_business_presence(title, snippet)
    industry = score_industry_relevance(title, snippet, target_industry)
    location = score_location_match(snippet, target_city, target_state, target_zip)
    enrichment = score_enrichment_potential(url)

    weights = {"contact": 0.25, "business": 0.15, "industry": 0.30, "location": 0.20, "enrichment": 0.10}
    total = (
        contact * weights["contact"] +
        business * weights["business"] +
        industry * weights["industry"] +
        location * weights["location"] +
        enrichment * weights["enrichment"]
    )

    return LeadScore(
        total=total,
        contact_completeness=contact,
        business_presence=business,
        industry_relevance=industry,
        location_match=location,
        enrichment_potential=enrichment,
        details={
            "weights": weights,
            "title_length": len(title),
            "snippet_length": len(snippet),
            "has_domain": any(d in url.lower() for d in [".com", ".net", ".org"]),
        },
    )
