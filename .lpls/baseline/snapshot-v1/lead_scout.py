#!/usr/bin/env python3
"""
LEAD SCOUT AGENT
═══════════════════════════════════════════════════════════════════
AI-powered lead discovery and prospecting across multiple sources.

Features:
- Multi-source lead harvesting (Google Maps, LinkedIn, Directories)
- Intelligent filtering and scoring
- Contact enrichment
- Geographic targeting
- Industry-specific prospecting
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, AsyncGenerator
import aiohttp
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LeadScout")


class LeadSource(Enum):
    """Sources for lead discovery"""
    GOOGLE_MAPS = "google_maps"
    LINKEDIN = "linkedin"
    YELP = "yelp"
    CHAMBER_OF_COMMERCE = "chamber"
    BBB = "bbb"
    ANGI = "angi"
    HOMEADVISOR = "homeadvisor"
    FACEBOOK = "facebook"
    CRUNCHBASE = "crunchbase"
    ANGELLIST = "angellist"
    PROPSTREAM = "propstream"
    MANUAL_ENTRY = "manual"
    REFERRAL = "referral"


class Industry(Enum):
    """Industry categories for targeting"""
    CONSTRUCTION = "construction"
    ROOFING = "roofing"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    HVAC = "hvac"
    LANDSCAPING = "landscaping"
    REAL_ESTATE = "real_estate"
    CHURCH = "church"
    SYNAGOGUE = "synagogue"
    WELLNESS = "wellness"
    TECH_STARTUP = "tech_startup"
    B2B_SERVICES = "b2b_services"
    RETAIL = "retail"
    RESTAURANT = "restaurant"
    HEALTHCARE = "healthcare"
    LEGAL = "legal"
    FINANCIAL = "financial"
    MANUFACTURING = "manufacturing"


@dataclass
class LeadCriteria:
    """Criteria for lead filtering and scoring"""
    # Geographic
    city: Optional[str] = None
    state: Optional[str] = None
    zip_codes: List[str] = field(default_factory=list)
    radius_miles: Optional[int] = None
    
    # Business
    industries: List[Industry] = field(default_factory=list)
    min_employees: Optional[int] = None
    max_employees: Optional[int] = None
    min_revenue: Optional[int] = None
    years_in_business: Optional[int] = None
    
    # Contact
    require_email: bool = False
    require_phone: bool = True
    require_website: bool = False
    
    # Property (for real estate)
    property_types: List[str] = field(default_factory=list)
    year_built_min: Optional[int] = None
    year_built_max: Optional[int] = None
    min_owner_age: Optional[int] = None
    max_owner_age: Optional[int] = None
    
    # Scoring
    min_score: int = 50
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "city": self.city,
            "state": self.state,
            "zip_codes": self.zip_codes,
            "industries": [i.value for i in self.industries],
            "min_employees": self.min_employees,
            "max_employees": self.max_employees,
            "min_score": self.min_score,
        }


@dataclass
class Lead:
    """Complete lead record"""
    id: str
    source: LeadSource
    created_at: datetime
    
    # Business Info
    business_name: str
    industry: Optional[Industry] = None
    website: Optional[str] = None
    years_in_business: Optional[int] = None
    employee_count: Optional[int] = None
    estimated_revenue: Optional[int] = None
    
    # Contact Info
    contact_first_name: Optional[str] = None
    contact_last_name: Optional[str] = None
    contact_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_type: Optional[str] = None  # mobile, landline, business
    
    # Address
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    
    # Property (for real estate)
    property_type: Optional[str] = None
    year_built: Optional[int] = None
    assessed_value: Optional[int] = None
    owner_occupied: Optional[bool] = None
    owner_age: Optional[int] = None
    
    # Scoring
    meta_score: int = 0
    swarm_score: int = 0
    pain_signals: List[str] = field(default_factory=list)
    buying_intent: Optional[str] = None
    
    # Status
    status: str = "new"  # new, contacted, qualified, booked, won, lost
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    
    # Engagement
    last_contact: Optional[datetime] = None
    contact_count: int = 0
    email_opens: int = 0
    link_clicks: int = 0
    
    def calculate_meta_score(self) -> int:
        """Calculate Meta Score (0-100)"""
        score = 0
        
        # Contact completeness
        if self.email and "@" in self.email:
            score += 20
        if self.phone:
            score += 15
        if self.website:
            score += 15
        if self.business_name:
            score += 20
        
        # Decision maker identified
        if self.contact_first_name and self.contact_last_name:
            score += 15
            if self.contact_title and any(t in self.contact_title.lower() 
                                         for t in ["owner", "founder", "ceo", "director", "manager"]):
                score += 10
        
        # Buying intent signals
        if self.buying_intent == "high":
            score += 5
        
        self.meta_score = min(score, 100)
        return self.meta_score
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source.value,
            "created_at": self.created_at.isoformat(),
            "business_name": self.business_name,
            "industry": self.industry.value if self.industry else None,
            "website": self.website,
            "contact_name": f"{self.contact_first_name or ''} {self.contact_last_name or ''}".strip(),
            "contact_title": self.contact_title,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "meta_score": self.meta_score,
            "swarm_score": self.swarm_score,
            "status": self.status,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Lead":
        return cls(
            id=data.get("id", ""),
            source=LeadSource(data.get("source", "manual")),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            business_name=data.get("business_name", ""),
            website=data.get("website"),
            contact_first_name=data.get("contact_first_name"),
            contact_last_name=data.get("contact_last_name"),
            contact_title=data.get("contact_title"),
            email=data.get("email"),
            phone=data.get("phone"),
            address=data.get("address"),
            city=data.get("city"),
            state=data.get("state"),
            zip_code=data.get("zip_code"),
            meta_score=data.get("meta_score", 0),
            swarm_score=data.get("swarm_score", 0),
            status=data.get("status", "new"),
            tags=data.get("tags", []),
        )


class LeadScout:
    """
    AI Lead Scout Agent
    Discovers and harvests leads from multiple sources
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.session: Optional[aiohttp.ClientSession] = None
        self.leads: List[Lead] = []
        self.criteria: Optional[LeadCriteria] = None
        
        # API Keys (load from env in production)
        self.google_maps_api_key = self.config.get("google_maps_api_key")
        self.linkedin_api_key = self.config.get("linkedin_api_key")
        self.propstream_email = self.config.get("propstream_email")
        self.propstream_password = self.config.get("propstream_password")
        
        logger.info("LeadScout initialized")
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search(self, criteria: LeadCriteria, 
                     sources: List[LeadSource] = None,
                     max_results: int = 100) -> List[Lead]:
        """
        Search for leads across multiple sources
        
        Args:
            criteria: Filtering criteria
            sources: Sources to search (None = all)
            max_results: Maximum leads to return
            
        Returns:
            List of qualified leads
        """
        self.criteria = criteria
        sources = sources or list(LeadSource)
        
        logger.info(f"Searching for leads: {criteria.to_dict()}")
        logger.info(f"Sources: {[s.value for s in sources]}")
        
        all_leads: List[Lead] = []
        
        # Search each source
        for source in sources:
            try:
                if source == LeadSource.GOOGLE_MAPS:
                    leads = await self._search_google_maps(criteria)
                elif source == LeadSource.YELP:
                    leads = await self._search_yelp(criteria)
                elif source == LeadSource.LINKEDIN:
                    leads = await self._search_linkedin(criteria)
                elif source == LeadSource.CHAMBER_OF_COMMERCE:
                    leads = await self._search_chamber(criteria)
                elif source == LeadSource.BBB:
                    leads = await self._search_bbb(criteria)
                elif source == LeadSource.CRUNCHBASE:
                    leads = await self._search_crunchbase(criteria)
                elif source == LeadSource.PROPSTREAM:
                    leads = await self._search_propstream(criteria)
                else:
                    continue
                
                all_leads.extend(leads)
                logger.info(f"  {source.value}: Found {len(leads)} leads")
                
            except Exception as e:
                logger.error(f"Error searching {source.value}: {e}")
        
        # Filter and score
        filtered = self._filter_leads(all_leads, criteria)
        scored = self._score_leads(filtered)
        
        # Sort by score and limit
        scored.sort(key=lambda l: l.meta_score + l.swarm_score, reverse=True)
        self.leads = scored[:max_results]
        
        logger.info(f"Total qualified leads: {len(self.leads)}")
        return self.leads
    
    async def _search_google_maps(self, criteria: LeadCriteria) -> List[Lead]:
        """Search Google Maps for businesses"""
        if not self.session:
            return []
        
        leads = []
        
        # Build search query
        industries = criteria.industries or [Industry.CONSTRUCTION]
        industry_terms = {
            Industry.CONSTRUCTION: "contractor",
            Industry.ROOFING: "roofing",
            Industry.PLUMBING: "plumber",
            Industry.ELECTRICAL: "electrician",
            Industry.HVAC: "hvac",
            Industry.LANDSCAPING: "landscaping",
            Industry.REAL_ESTATE: "real estate",
        }
        
        for industry in industries[:3]:  # Limit to 3 industries
            term = industry_terms.get(industry, "business")
            location = criteria.city or ""
            if criteria.state:
                location += f", {criteria.state}"
            
            query = f"{term} in {location}"
            logger.debug(f"Google Maps query: {query}")
            
            # Simulated results (replace with actual API call)
            for i in range(5):
                lead = Lead(
                    id=f"gm_{datetime.now().timestamp()}_{i}",
                    source=LeadSource.GOOGLE_MAPS,
                    created_at=datetime.now(),
                    business_name=f"{term.title()} Company {i+1}",
                    industry=industry,
                    city=criteria.city,
                    state=criteria.state,
                    zip_code=criteria.zip_codes[0] if criteria.zip_codes else None,
                    email=f"contact@company{i+1}.com",
                    phone=f"(555) {100+i:03d}-{1000+i:04d}",
                    website=f"https://company{i+1}.com",
                )
                lead.calculate_meta_score()
                leads.append(lead)
        
        return leads
    
    async def _search_yelp(self, criteria: LeadCriteria) -> List[Lead]:
        """Search Yelp for businesses"""
        leads = []
        # Implementation similar to Google Maps
        logger.info("Yelp search (simulated)")
        return leads
    
    async def _search_linkedin(self, criteria: LeadCriteria) -> List[Lead]:
        """Search LinkedIn for B2B leads"""
        leads = []
        logger.info("LinkedIn search (simulated)")
        return leads
    
    async def _search_chamber(self, criteria: LeadCriteria) -> List[Lead]:
        """Search Chamber of Commerce directories"""
        leads = []
        logger.info("Chamber search (simulated)")
        return leads
    
    async def _search_bbb(self, criteria: LeadCriteria) -> List[Lead]:
        """Search BBB directory"""
        leads = []
        logger.info("BBB search (simulated)")
        return leads
    
    async def _search_crunchbase(self, criteria: LeadCriteria) -> List[Lead]:
        """Search Crunchbase for startups"""
        leads = []
        logger.info("Crunchbase search (simulated)")
        return leads
    
    async def _search_propstream(self, criteria: LeadCriteria) -> List[Lead]:
        """Search PropStream for real estate leads"""
        # This will be handled by PropStreamIntegration
        logger.info("PropStream search (delegated to PropStreamIntegration)")
        return []
    
    def _filter_leads(self, leads: List[Lead], criteria: LeadCriteria) -> List[Lead]:
        """Filter leads based on criteria"""
        filtered = []
        
        for lead in leads:
            # Geographic filter
            if criteria.zip_codes and lead.zip_code:
                if lead.zip_code not in criteria.zip_codes:
                    continue
            
            # Industry filter
            if criteria.industries and lead.industry:
                if lead.industry not in criteria.industries:
                    continue
            
            # Contact requirement filter
            if criteria.require_email and not lead.email:
                continue
            if criteria.require_phone and not lead.phone:
                continue
            
            filtered.append(lead)
        
        return filtered
    
    def _score_leads(self, leads: List[Lead]) -> List[Lead]:
        """Score leads based on various factors"""
        for lead in leads:
            # Calculate base meta score
            lead.calculate_meta_score()
            
            # Calculate swarm score (industry-specific)
            if lead.industry in [Industry.CONSTRUCTION, Industry.ROOFING]:
                # ConstructionSwarm scoring
                score = 0
                if lead.employee_count:
                    if 5 <= lead.employee_count <= 50:
                        score += 40
                if lead.years_in_business:
                    if lead.years_in_business >= 5:
                        score += 35
                if lead.assessed_value:
                    score += 25
                lead.swarm_score = min(score, 100)
            
            elif lead.industry in [Industry.CHURCH, Industry.SYNAGOGUE, Industry.WELLNESS]:
                # SpiritualitySwarm scoring
                score = 50  # Base for community organizations
                lead.swarm_score = min(score, 100)
            
            else:
                # GrowthSwarm scoring
                score = 0
                if lead.employee_count:
                    if 10 <= lead.employee_count <= 200:
                        score += 35
                if lead.estimated_revenue:
                    score += 40
                lead.swarm_score = min(score, 100)
        
        return leads
    
    async def enrich_lead(self, lead: Lead) -> Lead:
        """Enrich lead data with additional information"""
        logger.info(f"Enriching lead: {lead.business_name}")
        
        # This would integrate with SpokeoIntegration
        # For now, return as-is
        
        return lead
    
    def export_to_json(self, filepath: str) -> None:
        """Export leads to JSON file"""
        data = [lead.to_dict() for lead in self.leads]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Exported {len(self.leads)} leads to {filepath}")
    
    def export_to_csv(self, filepath: str) -> None:
        """Export leads to CSV file"""
        import csv
        
        if not self.leads:
            logger.warning("No leads to export")
            return
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Business Name", "Industry", "Contact Name", "Title",
                "Email", "Phone", "Address", "City", "State", "ZIP",
                "Website", "Meta Score", "Swarm Score", "Status", "Source"
            ])
            
            for lead in self.leads:
                writer.writerow([
                    lead.id,
                    lead.business_name,
                    lead.industry.value if lead.industry else "",
                    f"{lead.contact_first_name or ''} {lead.contact_last_name or ''}".strip(),
                    lead.contact_title or "",
                    lead.email or "",
                    lead.phone or "",
                    lead.address or "",
                    lead.city or "",
                    lead.state or "",
                    lead.zip_code or "",
                    lead.website or "",
                    lead.meta_score,
                    lead.swarm_score,
                    lead.status,
                    lead.source.value
                ])
        
        logger.info(f"Exported {len(self.leads)} leads to {filepath}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get lead statistics"""
        if not self.leads:
            return {"total": 0, "by_source": {}, "by_industry": {}, "avg_score": 0}
        
        by_source = {}
        by_industry = {}
        total_score = 0
        
        for lead in self.leads:
            by_source[lead.source.value] = by_source.get(lead.source.value, 0) + 1
            if lead.industry:
                by_industry[lead.industry.value] = by_industry.get(lead.industry.value, 0) + 1
            total_score += lead.meta_score + lead.swarm_score
        
        return {
            "total": len(self.leads),
            "by_source": by_source,
            "by_industry": by_industry,
            "avg_score": total_score / (len(self.leads) * 2),
            "by_status": {
                "new": len([l for l in self.leads if l.status == "new"]),
                "contacted": len([l for l in self.leads if l.status == "contacted"]),
                "qualified": len([l for l in self.leads if l.status == "qualified"]),
            }
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo LeadScout functionality"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "LEAD SCOUT AGENT DEMO" + " " * 32 + "║")
    print("╚" + "═" * 68 + "╝")
    
    async with LeadScout() as scout:
        # Define criteria
        criteria = LeadCriteria(
            city="Eugene",
            state="OR",
            zip_codes=["97401", "97402", "97403"],
            industries=[Industry.CONSTRUCTION, Industry.ROOFING, Industry.PLUMBING],
            require_phone=True,
            min_score=50
        )
        
        # Search
        leads = await scout.search(
            criteria=criteria,
            sources=[LeadSource.GOOGLE_MAPS],
            max_results=20
        )
        
        # Display results
        print(f"\n{'─' * 70}")
        print(f"  FOUND {len(leads)} QUALIFIED LEADS")
        print(f"{'─' * 70}\n")
        
        for i, lead in enumerate(leads[:5], 1):
            print(f"  {i}. {lead.business_name}")
            print(f"     Industry: {lead.industry.value if lead.industry else 'N/A'}")
            print(f"     Contact: {lead.contact_first_name or ''} {lead.contact_last_name or ''}")
            print(f"     Phone: {lead.phone or 'N/A'}")
            print(f"     Email: {lead.email or 'N/A'}")
            print(f"     Meta Score: {lead.meta_score}/100 | Swarm Score: {lead.swarm_score}/100")
            print()
        
        # Show stats
        stats = scout.get_stats()
        print(f"{'─' * 70}")
        print(f"  STATISTICS")
        print(f"{'─' * 70}")
        print(f"  Total Leads: {stats['total']}")
        print(f"  By Source: {stats['by_source']}")
        print(f"  By Industry: {stats['by_industry']}")
        print(f"  Average Score: {stats['avg_score']:.1f}")


if __name__ == "__main__":
    asyncio.run(demo())
