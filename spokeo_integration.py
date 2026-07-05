#!/usr/bin/env python3
"""
SPOKEO INTEGRATION
═══════════════════════════════════════════════════════════════════
Contact enrichment via Spokeo people search.

Features:
- Phone number lookup
- Email address discovery
- Social profile enrichment
- Address verification
- Family member discovery
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SpokeoIntegration")


@dataclass
class EnrichedContact:
    """Enriched contact information from Spokeo"""
    id: str
    searched_at: datetime
    
    # Input data (what we searched with)
    input_first_name: Optional[str] = None
    input_last_name: Optional[str] = None
    input_address: Optional[str] = None
    input_city: Optional[str] = None
    input_state: Optional[str] = None
    input_zip: Optional[str] = None
    
    # Found data
    full_name: Optional[str] = None
    age: Optional[int] = None
    aliases: List[str] = field(default_factory=list)
    
    # Phone numbers
    phone_numbers: List[Dict[str, str]] = field(default_factory=list)
    # Format: [{"number": "555-123-4567", "type": "mobile", "carrier": "Verizon"}]
    
    # Email addresses
    email_addresses: List[Dict[str, str]] = field(default_factory=list)
    # Format: [{"email": "john@email.com", "confidence": "high", "source": "public"}]
    
    # Addresses
    addresses: List[Dict[str, str]] = field(default_factory=list)
    # Format: [{"address": "123 Main St", "city": "Eugene", "state": "OR", "type": "current"}]
    
    # Social profiles
    social_profiles: Dict[str, str] = field(default_factory=dict)
    # Format: {"facebook": "profile_url", "linkedin": "profile_url"}
    
    # Family members
    family_members: List[Dict[str, str]] = field(default_factory=list)
    # Format: [{"name": "Jane Smith", "relationship": "spouse", "age": "45"}]
    
    # Additional
    photos: List[str] = field(default_factory=list)
    occupation: Optional[str] = None
    education: Optional[str] = None
    
    # Metadata
    confidence_score: int = 0  # 0-100
    match_quality: str = "unknown"  # high, medium, low
    data_sources: List[str] = field(default_factory=list)
    
    def get_best_phone(self) -> Optional[str]:
        """Get best phone number (prefer mobile)"""
        # Prefer mobile
        mobile = [p for p in self.phone_numbers if p.get("type") == "mobile"]
        if mobile:
            return mobile[0].get("number")
        
        # Then landline
        landline = [p for p in self.phone_numbers if p.get("type") == "landline"]
        if landline:
            return landline[0].get("number")
        
        # Return first available
        if self.phone_numbers:
            return self.phone_numbers[0].get("number")
        
        return None
    
    def get_best_email(self) -> Optional[str]:
        """Get best email address"""
        if not self.email_addresses:
            return None
        
        # Prefer high confidence
        high = [e for e in self.email_addresses if e.get("confidence") == "high"]
        if high:
            return high[0].get("email")
        
        return self.email_addresses[0].get("email")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "age": self.age,
            "best_phone": self.get_best_phone(),
            "best_email": self.get_best_email(),
            "phone_numbers": self.phone_numbers,
            "email_addresses": self.email_addresses,
            "addresses": self.addresses,
            "social_profiles": self.social_profiles,
            "confidence_score": self.confidence_score,
            "match_quality": self.match_quality,
        }


@dataclass
class SpokeoSearchCriteria:
    """Criteria for Spokeo search"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    
    def to_search_query(self) -> str:
        """Generate search query string"""
        parts = []
        if self.first_name:
            parts.append(self.first_name)
        if self.last_name:
            parts.append(self.last_name)
        if self.address:
            parts.append(self.address)
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        return " ".join(parts)
    
    def has_minimum_data(self) -> bool:
        """Check if we have enough data to search"""
        return (self.first_name and self.last_name) or self.phone or self.email


class SpokeoIntegration:
    """
    Spokeo Integration
    Enriches contact data with phone numbers, emails, and social profiles
    
    Note: This is a framework. Actual integration requires
    Spokeo API access or manual search interface.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.api_key = self.config.get("api_key")
        self.rate_limit_remaining = 100  # Requests per hour
        
        self.enriched_contacts: Dict[str, EnrichedContact] = {}
        
        logger.info("SpokeoIntegration initialized")
    
    async def enrich_contact(self, 
                            first_name: Optional[str] = None,
                            last_name: Optional[str] = None,
                            address: Optional[str] = None,
                            city: Optional[str] = None,
                            state: Optional[str] = None,
                            zip_code: Optional[str] = None,
                            existing_phone: Optional[str] = None) -> Optional[EnrichedContact]:
        """
        Enrich contact information
        
        Args:
            first_name: First name
            last_name: Last name
            address: Street address
            city: City
            state: State
            zip_code: ZIP code
            existing_phone: Existing phone to verify
            
        Returns:
            Enriched contact or None if not found
        """
        criteria = SpokeoSearchCriteria(
            first_name=first_name,
            last_name=last_name,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
        )
        
        if not criteria.has_minimum_data():
            logger.warning("Insufficient data for Spokeo search")
            return None
        
        logger.info(f"Enriching: {criteria.to_search_query()}")
        
        # In production, this would call Spokeo API
        # For now, simulate enrichment
        enriched = await self._simulate_enrichment(criteria)
        
        if enriched:
            self.enriched_contacts[enriched.id] = enriched
            logger.info(f"Enriched contact: {enriched.full_name} "
                       f"(phones: {len(enriched.phone_numbers)}, "
                       f"emails: {len(enriched.email_addresses)})")
        
        return enriched
    
    async def _simulate_enrichment(self, criteria: SpokeoSearchCriteria) -> Optional[EnrichedContact]:
        """Simulate Spokeo enrichment"""
        import random
        
        # Simulate some not-found cases
        if random.random() < 0.1:
            return None
        
        full_name = f"{criteria.first_name or ''} {criteria.last_name or ''}".strip()
        
        # Generate phone numbers
        phones = []
        if random.random() < 0.8:  # 80% chance of finding mobile
            phones.append({
                "number": f"(541) {random.randint(200, 999):03d}-{random.randint(1000, 9999):04d}",
                "type": "mobile",
                "carrier": random.choice(["Verizon", "AT&T", "T-Mobile"]),
            })
        if random.random() < 0.5:  # 50% chance of finding landline
            phones.append({
                "number": f"(541) {random.randint(200, 999):03d}-{random.randint(1000, 9999):04d}",
                "type": "landline",
                "carrier": "CenturyLink",
            })
        
        # Generate emails
        emails = []
        if criteria.first_name and criteria.last_name:
            first = criteria.first_name.lower()
            last = criteria.last_name.lower()
            domains = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com"]
            
            if random.random() < 0.6:
                emails.append({
                    "email": f"{first}.{last}@{random.choice(domains)}",
                    "confidence": "high",
                    "source": "public_records",
                })
            if random.random() < 0.4:
                emails.append({
                    "email": f"{first[0]}{last}@{random.choice(domains)}",
                    "confidence": "medium",
                    "source": "social_profiles",
                })
        
        # Generate social profiles
        social = {}
        if random.random() < 0.4:
            social["facebook"] = f"https://facebook.com/{criteria.first_name}.{criteria.last_name}"
        if random.random() < 0.3:
            social["linkedin"] = f"https://linkedin.com/in/{criteria.first_name}-{criteria.last_name}"
        
        # Calculate confidence
        confidence = 50
        if phones:
            confidence += 20
        if emails:
            confidence += 20
        if social:
            confidence += 10
        
        return EnrichedContact(
            id=f"spokeo_{datetime.now().timestamp()}",
            searched_at=datetime.now(),
            input_first_name=criteria.first_name,
            input_last_name=criteria.last_name,
            input_address=criteria.address,
            input_city=criteria.city,
            input_state=criteria.state,
            full_name=full_name,
            age=random.randint(35, 70) if random.random() > 0.2 else None,
            phone_numbers=phones,
            email_addresses=emails,
            addresses=[{
                "address": criteria.address or "123 Main St",
                "city": criteria.city or "Eugene",
                "state": criteria.state or "OR",
                "type": "current",
            }] if criteria.address else [],
            social_profiles=social,
            confidence_score=confidence,
            match_quality="high" if confidence >= 70 else "medium" if confidence >= 40 else "low",
        )
    
    async def batch_enrich(self, 
                          leads: List[Dict[str, Any]],
                          progress_callback=None) -> List[EnrichedContact]:
        """
        Enrich multiple leads in batch
        
        Args:
            leads: List of lead dictionaries with name/address info
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of enriched contacts
        """
        enriched = []
        total = len(leads)
        
        logger.info(f"Batch enriching {total} leads")
        
        for i, lead in enumerate(leads):
            try:
                result = await self.enrich_contact(
                    first_name=lead.get("first_name") or lead.get("contact_first_name"),
                    last_name=lead.get("last_name") or lead.get("contact_last_name"),
                    address=lead.get("address"),
                    city=lead.get("city"),
                    state=lead.get("state"),
                    zip_code=lead.get("zip_code") or lead.get("zip"),
                )
                
                if result:
                    enriched.append(result)
                
                # Progress callback
                if progress_callback:
                    progress_callback(i + 1, total, result)
                
                # Rate limiting
                if i > 0 and i % 10 == 0:
                    await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error enriching lead {i}: {e}")
        
        logger.info(f"Batch enrichment complete: {len(enriched)}/{total} enriched")
        return enriched
    
    def export_enrichment_results(self, 
                                  contacts: List[EnrichedContact],
                                  filepath: str) -> None:
        """
        Export enrichment results to CSV
        
        Format suitable for importing back to CRM
        """
        import csv
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "Full Name", "Age", "Phone 1", "Phone 2", "Phone 3",
                "Email 1", "Email 2", "Email 3",
                "Facebook", "LinkedIn",
                "Confidence", "Match Quality"
            ])
            
            for contact in contacts:
                phones = [p.get("number", "") for p in contact.phone_numbers[:3]]
                emails = [e.get("email", "") for e in contact.email_addresses[:3]]
                
                writer.writerow([
                    contact.id,
                    contact.full_name or "",
                    contact.age or "",
                    phones[0] if len(phones) > 0 else "",
                    phones[1] if len(phones) > 1 else "",
                    phones[2] if len(phones) > 2 else "",
                    emails[0] if len(emails) > 0 else "",
                    emails[1] if len(emails) > 1 else "",
                    emails[2] if len(emails) > 2 else "",
                    contact.social_profiles.get("facebook", ""),
                    contact.social_profiles.get("linkedin", ""),
                    contact.confidence_score,
                    contact.match_quality,
                ])
        
        logger.info(f"Exported {len(contacts)} enrichment results to {filepath}")
    
    def get_enrichment_stats(self, contacts: Optional[List[EnrichedContact]] = None) -> Dict[str, Any]:
        """Get enrichment statistics"""
        contacts = contacts or list(self.enriched_contacts.values())
        
        if not contacts:
            return {"total": 0}
        
        with_phones = sum(1 for c in contacts if c.phone_numbers)
        with_emails = sum(1 for c in contacts if c.email_addresses)
        with_social = sum(1 for c in contacts if c.social_profiles)
        
        high_confidence = sum(1 for c in contacts if c.match_quality == "high")
        medium_confidence = sum(1 for c in contacts if c.match_quality == "medium")
        
        avg_confidence = sum(c.confidence_score for c in contacts) / len(contacts)
        
        return {
            "total": len(contacts),
            "with_phones": with_phones,
            "with_emails": with_emails,
            "with_social": with_social,
            "high_confidence": high_confidence,
            "medium_confidence": medium_confidence,
            "low_confidence": len(contacts) - high_confidence - medium_confidence,
            "avg_confidence": round(avg_confidence, 1),
            "phone_coverage": f"{with_phones/len(contacts)*100:.1f}%",
            "email_coverage": f"{with_emails/len(contacts)*100:.1f}%",
        }
    
    def merge_with_leads(self, 
                        original_leads: List[Dict],
                        enriched_contacts: List[EnrichedContact]) -> List[Dict]:
        """
        Merge enrichment data back into original leads
        
        Args:
            original_leads: Original lead data
            enriched_contacts: Enriched contact data
            
        Returns:
            Merged lead data
        """
        # Create lookup by name
        enriched_lookup = {
            (c.input_first_name or "").lower() + " " + (c.input_last_name or "").lower(): c
            for c in enriched_contacts
        }
        
        merged = []
        for lead in original_leads:
            name_key = f"{(lead.get('first_name') or lead.get('contact_first_name') or '').lower()} "
            name_key += f"{(lead.get('last_name') or lead.get('contact_last_name') or '').lower()}"
            name_key = name_key.strip()
            
            enriched = enriched_lookup.get(name_key)
            
            merged_lead = lead.copy()
            if enriched:
                merged_lead["enriched_phone"] = enriched.get_best_phone()
                merged_lead["enriched_email"] = enriched.get_best_email()
                merged_lead["enriched_social"] = enriched.social_profiles
                merged_lead["enriched_confidence"] = enriched.confidence_score
                merged_lead["all_phones"] = enriched.phone_numbers
                merged_lead["all_emails"] = enriched.email_addresses
            
            merged.append(merged_lead)
        
        return merged


class EnrichmentWorkflow:
    """
    Complete enrichment workflow
    Takes PropStream leads → Spokeo enrichment → CRM-ready data
    """
    
    def __init__(self, spokeo: SpokeoIntegration):
        self.spokeo = spokeo
    
    async def process_lead_batch(self, 
                                leads: List[Dict],
                                batch_size: int = 25) -> List[Dict]:
        """
        Process a batch of leads through enrichment
        
        Args:
            leads: Raw leads (from PropStream)
            batch_size: Number of leads to process at once
            
        Returns:
            Enriched leads ready for CRM import
        """
        logger.info(f"Processing {len(leads)} leads through enrichment workflow")
        
        all_enriched = []
        
        # Process in batches
        for i in range(0, len(leads), batch_size):
            batch = leads[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}: {len(batch)} leads")
            
            enriched = await self.spokeo.batch_enrich(batch)
            all_enriched.extend(enriched)
            
            # Brief pause between batches
            if i + batch_size < len(leads):
                await asyncio.sleep(2)
        
        # Merge enrichment data back
        merged = self.spokeo.merge_with_leads(leads, all_enriched)
        
        return merged
    
    def generate_enrichment_report(self, 
                                 original_count: int,
                                 enriched_count: int,
                                 output_file: str = "enrichment_report.txt") -> str:
        """Generate enrichment report"""
        stats = self.spokeo.get_enrichment_stats()
        
        report = f"""
═══════════════════════════════════════════════════════════════════
                    SPOKEO ENRICHMENT REPORT
═══════════════════════════════════════════════════════════════════

EXECUTIVE SUMMARY
─────────────────
Original Leads:     {original_count}
Successfully Enriched: {enriched_count}
Success Rate:         {enriched_count/original_count*100:.1f}%

ENRICHMENT COVERAGE
───────────────────
Phone Numbers Found:  {stats.get('with_phones', 0)} ({stats.get('phone_coverage', '0%')})
Email Addresses Found: {stats.get('with_emails', 0)} ({stats.get('email_coverage', '0%')})
Social Profiles Found: {stats.get('with_social', 0)}

CONFIDENCE DISTRIBUTION
───────────────────────
High Confidence:    {stats.get('high_confidence', 0)}
Medium Confidence:  {stats.get('medium_confidence', 0)}
Low Confidence:     {stats.get('low_confidence', 0)}
Average Confidence: {stats.get('avg_confidence', 0)}/100

RECOMMENDATIONS
───────────────
• Prioritize high-confidence contacts for immediate outreach
• Verify medium-confidence contacts via alternate methods
• Consider additional data sources for low-confidence contacts
• Use multiple phone numbers in sequence for best contact rate

═══════════════════════════════════════════════════════════════════
        """
        
        with open(output_file, 'w') as f:
            f.write(report)
        
        return report


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo Spokeo enrichment"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 18 + "SPOKEO ENRICHMENT DEMO" + " " * 28 + "║")
    print("╚" + "═" * 68 + "╝")
    
    # Initialize
    spokeo = SpokeoIntegration()
    
    # Sample leads (from PropStream)
    sample_leads = [
        {
            "first_name": "John",
            "last_name": "Smith",
            "address": "1234 Oak Street",
            "city": "Eugene",
            "state": "OR",
            "zip": "97401",
        },
        {
            "first_name": "Mary",
            "last_name": "Johnson",
            "address": "5678 Maple Avenue",
            "city": "Springfield",
            "state": "OR",
            "zip": "97477",
        },
        {
            "first_name": "Robert",
            "last_name": "Williams",
            "address": "9012 Pine Road",
            "city": "Eugene",
            "state": "OR",
            "zip": "97405",
        },
        {
            "first_name": "Linda",
            "last_name": "Brown",
            "address": "3456 Cedar Lane",
            "city": "Eugene",
            "state": "OR",
            "zip": "97402",
        },
        {
            "first_name": "Michael",
            "last_name": "Davis",
            "address": "7890 Elm Street",
            "city": "Springfield",
            "state": "OR",
            "zip": "97478",
        },
    ]
    
    # Enrich single contact
    print("\n🔍 Enriching single contact...")
    enriched = await spokeo.enrich_contact(
        first_name="John",
        last_name="Smith",
        address="1234 Oak Street",
        city="Eugene",
        state="OR",
    )
    
    if enriched:
        print(f"\n  Enriched: {enriched.full_name}")
        print(f"  Age: {enriched.age}")
        print(f"  Best Phone: {enriched.get_best_phone()}")
        print(f"  Best Email: {enriched.get_best_email()}")
        print(f"  Confidence: {enriched.confidence_score}/100 ({enriched.match_quality})")
        print(f"  Social: {list(enriched.social_profiles.keys())}")
    
    # Batch enrichment
    print(f"\n{'─' * 70}")
    print(f"  BATCH ENRICHMENT")
    print(f"{'─' * 70}")
    
    def progress(current, total, result):
        print(f"  Progress: {current}/{total}", end="\r")
    
    enriched_batch = await spokeo.batch_enrich(sample_leads, progress_callback=progress)
    print(f"\n  Enriched {len(enriched_batch)}/{len(sample_leads)} leads")
    
    # Show enrichment results
    print(f"\n{'─' * 70}")
    print(f"  ENRICHMENT RESULTS")
    print(f"{'─' * 70}\n")
    
    for contact in enriched_batch[:3]:
        print(f"  • {contact.full_name}")
        print(f"    Phone: {contact.get_best_phone() or 'N/A'}")
        print(f"    Email: {contact.get_best_email() or 'N/A'}")
        print(f"    Confidence: {contact.confidence_score}/100")
        print()
    
    # Statistics
    print(f"{'─' * 70}")
    print(f"  ENRICHMENT STATISTICS")
    print(f"{'─' * 70}")
    
    stats = spokeo.get_enrichment_stats(enriched_batch)
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Export results
    spokeo.export_enrichment_results(enriched_batch, "enrichment_results.csv")
    print(f"\n  ✅ Exported to enrichment_results.csv")


if __name__ == "__main__":
    asyncio.run(demo())
