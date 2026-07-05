#!/usr/bin/env python3
"""
PROPSTREAM INTEGRATION
═══════════════════════════════════════════════════════════════════
Real estate lead harvesting from PropStream.

Features:
- Property owner data extraction
- Geographic filtering
- Property type filtering
- Owner demographic filtering
- Integration with Lead Scout
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PropStreamIntegration")


@dataclass
class PropertyCriteria:
    """Criteria for PropStream property search"""
    state: str
    county: Optional[str] = None
    zip_codes: List[str] = field(default_factory=list)
    
    # Property filters
    property_types: List[str] = field(default_factory=lambda: ["SFR"])
    year_built_min: Optional[int] = None
    year_built_max: Optional[int] = None
    
    # Owner filters
    min_owner_age: Optional[int] = None
    max_owner_age: Optional[int] = None
    owner_occupied: Optional[bool] = None
    
    # Equity/LTV
    min_equity_percent: Optional[int] = None  # Minimum equity percentage
    max_ltv: Optional[int] = None  # Maximum loan-to-value
    
    # Limits
    max_results: int = 100
    
    def to_search_params(self) -> Dict[str, Any]:
        """Convert to API search parameters"""
        params = {
            "state": self.state,
            "max_results": self.max_results,
        }
        
        if self.county:
            params["county"] = self.county
        if self.zip_codes:
            params["zip_codes"] = self.zip_codes
        if self.property_types:
            params["property_types"] = self.property_types
        if self.year_built_min:
            params["year_built_min"] = self.year_built_min
        if self.year_built_max:
            params["year_built_max"] = self.year_built_max
        if self.min_owner_age:
            params["min_owner_age"] = self.min_owner_age
        if self.max_owner_age:
            params["max_owner_age"] = self.max_owner_age
        if self.owner_occupied is not None:
            params["owner_occupied"] = self.owner_occupied
        if self.min_equity_percent:
            params["min_equity_percent"] = self.min_equity_percent
        if self.max_ltv:
            params["max_ltv"] = self.max_ltv
        
        return params


@dataclass
class PropertyLead:
    """Property owner lead from PropStream"""
    id: str
    created_at: datetime
    
    # Property Info
    property_id: str
    address: str
    city: str
    state: str
    zip_code: str
    county: Optional[str] = None
    
    # Property Details
    property_type: str = "SFR"  # SFR, Condo, Townhouse, Multi-Family, etc.
    year_built: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[int] = None
    lot_size: Optional[int] = None  # Square feet
    
    # Valuation
    assessed_value: Optional[int] = None
    market_value: Optional[int] = None
    last_sale_price: Optional[int] = None
    last_sale_date: Optional[datetime] = None
    
    # Owner Info
    owner_first_name: Optional[str] = None
    owner_last_name: Optional[str] = None
    owner_age: Optional[int] = None
    owner_occupied: bool = True
    length_of_residence: Optional[int] = None  # Years
    
    # Contact (if available)
    phone: Optional[str] = None
    email: Optional[str] = None
    
    # Equity
    estimated_equity: Optional[int] = None
    equity_percentage: Optional[float] = None
    mortgage_balance: Optional[int] = None
    
    # Scoring
    propensity_score: int = 0  # PropStream's likelihood to sell
    
    # Status
    status: str = "new"  # new, contacted, qualified, etc.
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    
    def get_owner_name(self) -> str:
        """Get owner full name"""
        parts = [self.owner_first_name or "", self.owner_last_name or ""]
        return " ".join(p for p in parts if p).strip()
    
    def get_address_string(self) -> str:
        """Get full address string"""
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"
    
    def to_lead_dict(self) -> Dict[str, Any]:
        """Convert to standard lead format"""
        return {
            "id": self.id,
            "source": "propstream",
            "created_at": self.created_at.isoformat(),
            "business_name": f"{self.get_owner_name()} - Property Owner",
            "contact_first_name": self.owner_first_name,
            "contact_last_name": self.owner_last_name,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "property_type": self.property_type,
            "year_built": self.year_built,
            "assessed_value": self.assessed_value,
            "owner_age": self.owner_age,
            "owner_occupied": self.owner_occupied,
            "phone": self.phone,
            "email": self.email,
            "equity_percentage": self.equity_percentage,
            "status": self.status,
            "tags": self.tags,
        }


class PropStreamIntegration:
    """
    PropStream Integration
    Harvests real estate leads from PropStream data
    
    Note: This is a framework. Actual API integration requires
    PropStream API credentials and proper authentication.
    """
    
    # Lane County ZIP codes (default)
    LANE_COUNTY_ZIPS = [
        "97401", "97402", "97403", "97404", "97405", "97406",
        "97408", "97477", "97478", "97487", "97488", "97426",
        "97431", "97437", "97439", "97448", "97452", "97453",
        "97461", "97462", "97463", "97484", "97489", "97492",
    ]
    
    # Residential property types
    RESIDENTIAL_TYPES = {"sfr", "condo", "townhouse", "single family", 
                        "single_family", "residential", "townhome"}
    
    # Commercial keywords to filter out
    COMMERCIAL_KEYWORDS = [
        "office", "commercial", "warehouse", "retail", "industrial",
        "mixed use", "mixed_use", "multi-tenant", "strip mall",
        "apartment building", "apartments", "duplex", "triplex",
    ]
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.email = self.config.get("email") or os.environ.get("PROPSTREAM_EMAIL", "")
        self.password = self.config.get("password") or os.environ.get("PROPSTREAM_PASSWORD", "")
        self.api_key = self.config.get("api_key") or os.environ.get("PROPSTREAM_API_KEY", "")
        
        self.leads: List[PropertyLead] = []
        self.authenticated = False
        
        logger.info("PropStreamIntegration initialized")
    
    async def authenticate(self) -> bool:
        """
        Authenticate with PropStream
        
        Returns:
            True if authentication successful
        """
        if not self.email or not self.password:
            logger.error("PropStream credentials not configured")
            return False
        
        # In a real implementation, this would make API call to authenticate
        logger.info(f"Authenticating as {self.email}...")
        
        # Simulated authentication
        self.authenticated = True
        logger.info("PropStream authentication successful")
        return True
    
    async def fetch_homeowners(self, criteria: PropertyCriteria) -> List[PropertyLead]:
        """
        Fetch homeowner leads from PropStream
        
        Args:
            criteria: Search criteria
            
        Returns:
            List of property leads
        """
        if not self.authenticated:
            await self.authenticate()
        
        logger.info(f"Fetching homeowners: {criteria.to_search_params()}")
        
        # In production, this would make actual API calls to PropStream
        # For now, we simulate realistic data
        leads = await self._simulate_fetch(criteria)
        
        # Filter for residential only
        residential_leads = [l for l in leads if self._is_residential(l)]
        
        logger.info(f"Found {len(leads)} properties, {len(residential_leads)} residential")
        
        self.leads = residential_leads
        return residential_leads
    
    async def _simulate_fetch(self, criteria: PropertyCriteria) -> List[PropertyLead]:
        """Simulate PropStream data fetch"""
        import random
        
        # Sample street names
        streets = [
            "Oak Street", "Maple Avenue", "Pine Road", "Cedar Lane",
            "Elm Street", "Washington Avenue", "Main Street", "Park Road",
            "Highland Avenue", "River Road", "Forest Lane", "Sunset Drive",
            "Willow Street", "Cherry Avenue", "Birch Lane",
        ]
        
        # Sample owner last names
        last_names = [
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
            "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
            "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
            "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
        ]
        
        # Sample first names
        first_names = [
            "James", "Mary", "John", "Patricia", "Robert", "Jennifer",
            "Michael", "Linda", "William", "Elizabeth", "David", "Barbara",
            "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
            "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
        ]
        
        leads = []
        zips = criteria.zip_codes or self.LANE_COUNTY_ZIPS[:10]
        
        for i in range(min(criteria.max_results, 100)):
            zip_code = random.choice(zips)
            street = random.choice(streets)
            house_number = random.randint(100, 9999)
            
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            
            year_built = random.randint(1960, 2005)
            owner_age = random.randint(35, 70)
            
            assessed_value = random.randint(200000, 800000)
            equity_pct = random.randint(30, 100)
            
            lead = PropertyLead(
                id=f"prop_{datetime.now().timestamp()}_{i}",
                created_at=datetime.now(),
                property_id=f"pid_{i}",
                address=f"{house_number} {street}",
                city="Eugene" if zip_code in ["97401", "97402", "97403", "97404", "97405"] else "Springfield",
                state=criteria.state or "OR",
                zip_code=zip_code,
                county="Lane",
                property_type=random.choice(["SFR", "Condo", "Townhouse"]),
                year_built=year_built,
                bedrooms=random.randint(2, 5),
                bathrooms=random.choice([1.0, 1.5, 2.0, 2.5, 3.0, 3.5]),
                square_feet=random.randint(1200, 3500),
                assessed_value=assessed_value,
                market_value=int(assessed_value * 1.1),
                owner_first_name=first_name,
                owner_last_name=last_name,
                owner_age=owner_age,
                owner_occupied=random.choice([True, True, True, False]),  # 75% owner-occupied
                length_of_residence=random.randint(2, 20),
                estimated_equity=int(assessed_value * equity_pct / 100),
                equity_percentage=equity_pct,
                propensity_score=random.randint(20, 80),
            )
            
            leads.append(lead)
        
        return leads
    
    def _is_residential(self, lead: PropertyLead) -> bool:
        """Check if property is residential"""
        ptype = (lead.property_type or "SFR").lower().strip()
        
        # Check if in residential types
        if any(rt in ptype for rt in self.RESIDENTIAL_TYPES):
            # Check for commercial keywords in address or other fields
            lead_data = json.dumps(lead.to_lead_dict()).lower()
            if any(kw in lead_data for kw in self.COMMERCIAL_KEYWORDS):
                return False
            return True
        
        return False
    
    def filter_by_criteria(self, 
                          leads: List[PropertyLead],
                          criteria: PropertyCriteria) -> List[PropertyLead]:
        """
        Filter leads by criteria
        
        Args:
            leads: Raw leads
            criteria: Filter criteria
            
        Returns:
            Filtered leads
        """
        filtered = leads
        
        # Geographic filter
        if criteria.zip_codes:
            filtered = [l for l in filtered if l.zip_code in criteria.zip_codes]
        
        if criteria.county:
            filtered = [l for l in filtered if l.county and l.county.lower() == criteria.county.lower()]
        
        # Property filter
        if criteria.property_types:
            filtered = [l for l in filtered if l.property_type in criteria.property_types]
        
        if criteria.year_built_min:
            filtered = [l for l in filtered if l.year_built and l.year_built >= criteria.year_built_min]
        
        if criteria.year_built_max:
            filtered = [l for l in filtered if l.year_built and l.year_built <= criteria.year_built_max]
        
        # Owner filter
        if criteria.min_owner_age:
            filtered = [l for l in filtered if l.owner_age and l.owner_age >= criteria.min_owner_age]
        
        if criteria.max_owner_age:
            filtered = [l for l in filtered if l.owner_age and l.owner_age <= criteria.max_owner_age]
        
        if criteria.owner_occupied is not None:
            filtered = [l for l in filtered if l.owner_occupied == criteria.owner_occupied]
        
        # Equity filter
        if criteria.min_equity_percent:
            filtered = [l for l in filtered if l.equity_percentage and l.equity_percentage >= criteria.min_equity_percent]
        
        return filtered
    
    def score_leads(self, leads: List[PropertyLead]) -> List[PropertyLead]:
        """
        Score leads based on various factors
        
        Scoring criteria:
        - Equity: Higher equity = higher score
        - Owner age: Target age range = higher score
        - Years owned: Longer ownership = higher score
        - Property age: Older properties may need work
        """
        for lead in leads:
            score = 0
            
            # Equity score (up to 40 points)
            if lead.equity_percentage:
                score += int(lead.equity_percentage * 0.4)
            
            # Owner age score (35-65 is target, up to 20 points)
            if lead.owner_age:
                if 35 <= lead.owner_age <= 65:
                    score += 20
                elif 30 <= lead.owner_age <= 70:
                    score += 10
            
            # Length of residence (up to 15 points)
            if lead.length_of_residence:
                score += min(lead.length_of_residence, 15)
            
            # Property age (older = potential work needed, up to 15 points)
            if lead.year_built:
                age = datetime.now().year - lead.year_built
                if age >= 25:
                    score += 15
                elif age >= 15:
                    score += 10
            
            # Propensity bonus
            score += lead.propensity_score // 10
            
            lead.propensity_score = min(score, 100)
        
        # Sort by score
        leads.sort(key=lambda l: l.propensity_score, reverse=True)
        return leads
    
    def export_for_spokeo(self, 
                         leads: List[PropertyLead],
                         filepath: str) -> None:
        """
        Export leads to CSV for Spokeo enrichment
        
        Spokeo will be used to find phone numbers and emails
        """
        import csv
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "First Name", "Last Name", "Address", "City", "State", "ZIP",
                "Property Type", "Year Built", "Assessed Value", "Owner Age",
                "Length of Residence", "Equity %", "Propensity Score",
                "Phone (Spokeo)", "Email (Spokeo)", "Status"
            ])
            
            for lead in leads:
                writer.writerow([
                    lead.id,
                    lead.owner_first_name or "",
                    lead.owner_last_name or "",
                    lead.address,
                    lead.city,
                    lead.state,
                    lead.zip_code,
                    lead.property_type,
                    lead.year_built or "",
                    lead.assessed_value or "",
                    lead.owner_age or "",
                    lead.length_of_residence or "",
                    f"{lead.equity_percentage:.0f}%" if lead.equity_percentage else "",
                    lead.propensity_score,
                    lead.phone or "",  # To be filled by Spokeo
                    lead.email or "",  # To be filled by Spokeo
                    lead.status,
                ])
        
        logger.info(f"Exported {len(leads)} leads to {filepath} for Spokeo enrichment")
    
    def export_to_json(self, 
                      leads: List[PropertyLead],
                      filepath: str) -> None:
        """Export leads to JSON"""
        data = [lead.to_lead_dict() for lead in leads]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported {len(leads)} leads to {filepath}")
    
    def get_stats(self, leads: Optional[List[PropertyLead]] = None) -> Dict[str, Any]:
        """Get lead statistics"""
        leads = leads or self.leads
        
        if not leads:
            return {"total": 0}
        
        # Geographic distribution
        by_city = {}
        for lead in leads:
            by_city[lead.city] = by_city.get(lead.city, 0) + 1
        
        # Property types
        by_type = {}
        for lead in leads:
            by_type[lead.property_type] = by_type.get(lead.property_type, 0) + 1
        
        # Value distribution
        values = [l.assessed_value for l in leads if l.assessed_value]
        
        # Age distribution
        ages = [l.owner_age for l in leads if l.owner_age]
        
        return {
            "total": len(leads),
            "by_city": by_city,
            "by_property_type": by_type,
            "avg_value": sum(values) / len(values) if values else 0,
            "avg_owner_age": sum(ages) / len(ages) if ages else 0,
            "avg_propensity_score": sum(l.propensity_score for l in leads) / len(leads),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ GUILDFCRAFT SPECIFIC IMPLEMENTATION ═══
# ═══════════════════════════════════════════════════════════════════════════════

class GuildCraftLeadScout:
    """
    Specialized lead scout for GuildCraft Exteriors
    Targets Lane County homeowners for roofing, siding, windows, patios, pergolas
    """
    
    # GuildCraft service areas
    SERVICE_ZIPS = [
        "97401", "97402", "97403", "97404", "97405", "97406",
        "97408", "97477", "97478", "97487", "97488", "97426",
        "97431", "97437", "97439", "97448", "97452", "97453",
        "97461", "97462", "97463", "97484", "97489", "97492",
    ]
    
    # Target services
    SERVICES = ["Roofing", "Siding", "Windows", "Patio", "Pergola"]
    
    def __init__(self, propstream: PropStreamIntegration):
        self.propstream = propstream
    
    async def find_prospects(self, max_results: int = 50) -> List[PropertyLead]:
        """
        Find ideal prospects for GuildCraft
        
        Criteria:
        - Lane County, Oregon
        - Single family homes
        - Built 1960-2005 (likely need exterior work)
        - Owner occupied
        - Owners aged 35-70 (decision makers)
        - Residential only (no commercial)
        """
        criteria = PropertyCriteria(
            state="OR",
            county="Lane",
            zip_codes=self.SERVICE_ZIPS,
            property_types=["SFR", "Condo", "Townhouse"],
            year_built_min=1960,
            year_built_max=2005,
            min_owner_age=35,
            max_owner_age=70,
            owner_occupied=True,
            max_results=max_results * 3,  # Request more for filtering
        )
        
        # Fetch from PropStream
        leads = await self.propstream.fetch_homeowners(criteria)
        
        # Filter and score
        filtered = self.propstream.filter_by_criteria(leads, criteria)
        scored = self.propstream.score_leads(filtered)
        
        # Take top results
        return scored[:max_results]
    
    def generate_outreach_strategy(self, lead: PropertyLead) -> Dict[str, str]:
        """Generate outreach strategy for a lead"""
        
        # Determine likely service need based on property age
        property_age = datetime.now().year - (lead.year_built or 1990)
        
        if property_age >= 30:
            primary_service = "Roofing"
            angle = "Many roofs in your neighborhood are reaching the end of their lifespan"
        elif property_age >= 20:
            primary_service = "Siding"
            angle = "Updating your home's exterior can dramatically improve curb appeal and energy efficiency"
        else:
            primary_service = "Windows"
            angle = "Energy-efficient windows can significantly reduce your heating and cooling costs"
        
        return {
            "primary_service": primary_service,
            "angle": angle,
            "pain_point": f"Your home was built in {lead.year_built}, which means {primary_service.lower()} may be due for an update",
            "value_prop": f"GuildCraft specializes in {primary_service.lower()} for homes like yours in {lead.city}",
            "personalized_subject": f"{lead.city} home exterior services - {lead.get_owner_name()}",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo PropStream integration"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "PROPSTREAM INTEGRATION DEMO" + " " * 26 + "║")
    print("╚" + "═" * 68 + "╝")
    
    # Initialize integration
    propstream = PropStreamIntegration(config={
        "email": "demo@example.com",
        "password": "demo_password",
    })
    
    # Authenticate
    print("\n🔐 Authenticating...")
    await propstream.authenticate()
    
    # Search for homeowners
    print("\n🏠 Searching Lane County homeowners...")
    criteria = PropertyCriteria(
        state="OR",
        county="Lane",
        zip_codes=propstream.LANE_COUNTY_ZIPS[:10],
        property_types=["SFR", "Condo"],
        year_built_min=1960,
        year_built_max=2005,
        min_owner_age=35,
        max_owner_age=70,
        max_results=20,
    )
    
    leads = await propstream.fetch_homeowners(criteria)
    
    # Display results
    print(f"\n{'─' * 70}")
    print(f"  FOUND {len(leads)} RESIDENTIAL LEADS")
    print(f"{'─' * 70}\n")
    
    for i, lead in enumerate(leads[:5], 1):
        print(f"  {i}. {lead.get_owner_name()}")
        print(f"     Property: {lead.address}")
        print(f"     {lead.city}, {lead.state} {lead.zip_code}")
        print(f"     Built: {lead.year_built} | Value: ${lead.assessed_value:,}")
        print(f"     Owner Age: {lead.owner_age} | Equity: {lead.equity_percentage:.0f}%")
        print(f"     Score: {lead.propensity_score}/100")
        print()
    
    # Show stats
    print(f"{'─' * 70}")
    print(f"  STATISTICS")
    print(f"{'─' * 70}")
    
    stats = propstream.get_stats(leads)
    print(f"  Total: {stats['total']}")
    print(f"  By City: {stats['by_city']}")
    print(f"  By Type: {stats['by_property_type']}")
    print(f"  Avg Value: ${stats['avg_value']:,.0f}")
    print(f"  Avg Owner Age: {stats['avg_owner_age']:.1f}")
    print(f"  Avg Score: {stats['avg_propensity_score']:.1f}")
    
    # GuildCraft demo
    print(f"\n{'─' * 70}")
    print(f"  GUILDFCRAFT LEAD SCOUT")
    print(f"{'─' * 70}")
    
    guildcraft = GuildCraftLeadScout(propstream)
    prospects = await guildcraft.find_prospects(max_results=10)
    
    print(f"\n  Found {len(prospects)} prospects for GuildCraft\n")
    
    for i, prospect in enumerate(prospects[:3], 1):
        strategy = guildcraft.generate_outreach_strategy(prospect)
        print(f"  {i}. {prospect.get_owner_name()}")
        print(f"     Service: {strategy['primary_service']}")
        print(f"     Angle: {strategy['angle']}")
        print(f"     Subject: {strategy['personalized_subject']}")
        print()


if __name__ == "__main__":
    asyncio.run(demo())
