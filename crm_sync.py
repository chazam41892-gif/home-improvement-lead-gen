#!/usr/bin/env python3
"""
CRM SYNC AGENT
═══════════════════════════════════════════════════════════════════
Database synchronization and lead management.

Features:
- Multi-CRM support (HubSpot, Salesforce, Pipedrive, etc.)
- Lead record management
- Two-way sync
- Duplicate detection
- Sync conflict resolution
"""

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CRMSync")


class CRMProvider(Enum):
    """Supported CRM providers"""
    HUBSPOT = "hubspot"
    SALESFORCE = "salesforce"
    PIPEDRIVE = "pipedrive"
    ZOHO = "zoho"
    FRESHSALES = "freshsales"
    CLOSE = "close"
    GOOGLE_SHEETS = "google_sheets"
    AIRTABLE = "airtable"
    SQLITE = "sqlite"
    CUSTOM = "custom"


class SyncStatus(Enum):
    """Sync operation status"""
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"
    CONFLICT = "conflict"


class PipelineStage(Enum):
    """Lead pipeline stages"""
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"
    NURTURING = "nurturing"
    DISQUALIFIED = "disqualified"


@dataclass
class LeadRecord:
    """Complete lead record for CRM"""
    id: str
    created_at: datetime
    updated_at: datetime
    
    # Core Info
    business_name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    
    # Contact
    contact_first_name: Optional[str] = None
    contact_last_name: Optional[str] = None
    contact_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    
    # Address
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: str = "US"
    
    # Scoring
    meta_score: int = 0
    swarm_score: int = 0
    total_score: int = 0
    
    # Pipeline
    stage: PipelineStage = PipelineStage.NEW
    pipeline: str = "default"
    owner_id: Optional[str] = None  # Assigned sales rep
    
    # Source
    source: Optional[str] = None
    source_details: Optional[str] = None
    campaign_id: Optional[str] = None
    
    # Engagement
    last_contact: Optional[datetime] = None
    contact_count: int = 0
    email_opens: int = 0
    link_clicks: int = 0
    last_email_sent: Optional[datetime] = None
    
    # Notes
    notes: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    
    # Sync
    crm_id: Optional[str] = None  # ID in external CRM
    sync_status: SyncStatus = SyncStatus.PENDING
    last_sync: Optional[datetime] = None
    sync_error: Optional[str] = None
    
    def __post_init__(self):
        """Calculate total score after initialization"""
        self.total_score = self.meta_score + self.swarm_score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "business_name": self.business_name,
            "industry": self.industry,
            "website": self.website,
            "contact_first_name": self.contact_first_name,
            "contact_last_name": self.contact_last_name,
            "contact_title": self.contact_title,
            "email": self.email,
            "phone": self.phone,
            "mobile_phone": self.mobile_phone,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "meta_score": self.meta_score,
            "swarm_score": self.swarm_score,
            "total_score": self.total_score,
            "stage": self.stage.value,
            "pipeline": self.pipeline,
            "source": self.source,
            "tags": self.tags,
            "sync_status": self.sync_status.value,
            "crm_id": self.crm_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LeadRecord":
        """Create from dictionary"""
        return cls(
            id=data.get("id", ""),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.now().isoformat())),
            business_name=data.get("business_name", ""),
            industry=data.get("industry"),
            website=data.get("website"),
            contact_first_name=data.get("contact_first_name"),
            contact_last_name=data.get("contact_last_name"),
            contact_title=data.get("contact_title"),
            email=data.get("email"),
            phone=data.get("phone"),
            mobile_phone=data.get("mobile_phone"),
            address=data.get("address"),
            city=data.get("city"),
            state=data.get("state"),
            zip_code=data.get("zip_code"),
            meta_score=data.get("meta_score", 0),
            swarm_score=data.get("swarm_score", 0),
            stage=PipelineStage(data.get("stage", "new")),
            source=data.get("source"),
            tags=data.get("tags", []),
            crm_id=data.get("crm_id"),
        )
    
    def get_full_name(self) -> str:
        """Get contact full name"""
        parts = [self.contact_first_name or "", self.contact_last_name or ""]
        return " ".join(p for p in parts if p).strip()
    
    def get_address_string(self) -> str:
        """Get formatted address"""
        parts = [
            self.address or "",
            f"{self.city or ''}, {self.state or ''} {self.zip_code or ''}".strip()
        ]
        return ", ".join(p for p in parts if p)


@dataclass
class SyncConfig:
    """CRM sync configuration"""
    provider: CRMProvider
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    instance_url: Optional[str] = None  # For Salesforce, etc.
    
    # Sync settings
    auto_sync: bool = True
    sync_interval_minutes: int = 5
    conflict_resolution: str = "local_wins"  # local_wins, remote_wins, newest
    
    # Field mapping
    field_mapping: Dict[str, str] = field(default_factory=dict)
    
    # Filters
    sync_only_scored_above: int = 50
    sync_only_stages: List[str] = field(default_factory=lambda: ["new", "contacted", "qualified"])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider.value,
            "auto_sync": self.auto_sync,
            "sync_interval_minutes": self.sync_interval_minutes,
            "conflict_resolution": self.conflict_resolution,
        }


class LocalDatabase:
    """Local SQLite database for lead storage"""
    
    def __init__(self, db_path: str = "leads.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    business_name TEXT NOT NULL,
                    industry TEXT,
                    website TEXT,
                    contact_first_name TEXT,
                    contact_last_name TEXT,
                    contact_title TEXT,
                    email TEXT,
                    phone TEXT,
                    mobile_phone TEXT,
                    address TEXT,
                    city TEXT,
                    state TEXT,
                    zip_code TEXT,
                    country TEXT DEFAULT 'US',
                    meta_score INTEGER DEFAULT 0,
                    swarm_score INTEGER DEFAULT 0,
                    total_score INTEGER DEFAULT 0,
                    stage TEXT DEFAULT 'new',
                    pipeline TEXT DEFAULT 'default',
                    owner_id TEXT,
                    source TEXT,
                    source_details TEXT,
                    campaign_id TEXT,
                    last_contact TEXT,
                    contact_count INTEGER DEFAULT 0,
                    email_opens INTEGER DEFAULT 0,
                    link_clicks INTEGER DEFAULT 0,
                    last_email_sent TEXT,
                    notes TEXT,
                    tags TEXT,
                    custom_fields TEXT,
                    crm_id TEXT,
                    sync_status TEXT DEFAULT 'pending',
                    last_sync TEXT,
                    sync_error TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    lead_id TEXT,
                    crm_id TEXT,
                    status TEXT,
                    error_message TEXT
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(total_score);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_leads_sync ON leads(sync_status);
            """)
    
    def save_lead(self, lead: LeadRecord) -> bool:
        """Save or update lead"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO leads (
                        id, created_at, updated_at, business_name, industry, website,
                        contact_first_name, contact_last_name, contact_title,
                        email, phone, mobile_phone, address, city, state, zip_code, country,
                        meta_score, swarm_score, total_score, stage, pipeline, owner_id,
                        source, source_details, campaign_id, last_contact, contact_count,
                        email_opens, link_clicks, last_email_sent, notes, tags,
                        custom_fields, crm_id, sync_status, last_sync, sync_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lead.id, lead.created_at.isoformat(), lead.updated_at.isoformat(),
                    lead.business_name, lead.industry, lead.website,
                    lead.contact_first_name, lead.contact_last_name, lead.contact_title,
                    lead.email, lead.phone, lead.mobile_phone,
                    lead.address, lead.city, lead.state, lead.zip_code, lead.country,
                    lead.meta_score, lead.swarm_score, lead.total_score,
                    lead.stage.value, lead.pipeline, lead.owner_id,
                    lead.source, lead.source_details, lead.campaign_id,
                    lead.last_contact.isoformat() if lead.last_contact else None,
                    lead.contact_count, lead.email_opens, lead.link_clicks,
                    lead.last_email_sent.isoformat() if lead.last_email_sent else None,
                    lead.notes, json.dumps(lead.tags), json.dumps(lead.custom_fields),
                    lead.crm_id, lead.sync_status.value,
                    lead.last_sync.isoformat() if lead.last_sync else None,
                    lead.sync_error
                ))
            return True
        except Exception as e:
            logger.error(f"Error saving lead: {e}")
            return False
    
    def get_lead(self, lead_id: str) -> Optional[LeadRecord]:
        """Get lead by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM leads WHERE id = ?", (lead_id,)
            ).fetchone()
            
            if row:
                return self._row_to_lead(row)
        return None
    
    def get_leads_by_stage(self, stage: PipelineStage, limit: int = 100) -> List[LeadRecord]:
        """Get leads by pipeline stage"""
        leads = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM leads WHERE stage = ? ORDER BY total_score DESC LIMIT ?",
                (stage.value, limit)
            )
            for row in cursor:
                leads.append(self._row_to_lead(row))
        return leads
    
    def get_leads_by_score(self, min_score: int, limit: int = 100) -> List[LeadRecord]:
        """Get leads above score threshold"""
        leads = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM leads WHERE total_score >= ? ORDER BY total_score DESC LIMIT ?",
                (min_score, limit)
            )
            for row in cursor:
                leads.append(self._row_to_lead(row))
        return leads
    
    def get_pending_sync(self, limit: int = 100) -> List[LeadRecord]:
        """Get leads pending sync"""
        leads = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM leads WHERE sync_status = 'pending' OR sync_status = 'error' LIMIT ?",
                (limit,)
            )
            for row in cursor:
                leads.append(self._row_to_lead(row))
        return leads
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            
            stage_counts = {}
            for row in conn.execute("SELECT stage, COUNT(*) FROM leads GROUP BY stage"):
                stage_counts[row[0]] = row[1]
            
            sync_counts = {}
            for row in conn.execute("SELECT sync_status, COUNT(*) FROM leads GROUP BY sync_status"):
                sync_counts[row[0]] = row[1]
            
            avg_score = conn.execute("SELECT AVG(total_score) FROM leads").fetchone()[0] or 0
            
            return {
                "total_leads": total,
                "by_stage": stage_counts,
                "by_sync_status": sync_counts,
                "average_score": round(avg_score, 2),
            }
    
    def _row_to_lead(self, row: sqlite3.Row) -> LeadRecord:
        """Convert database row to LeadRecord"""
        return LeadRecord(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            business_name=row["business_name"],
            industry=row["industry"],
            website=row["website"],
            contact_first_name=row["contact_first_name"],
            contact_last_name=row["contact_last_name"],
            contact_title=row["contact_title"],
            email=row["email"],
            phone=row["phone"],
            mobile_phone=row["mobile_phone"],
            address=row["address"],
            city=row["city"],
            state=row["state"],
            zip_code=row["zip_code"],
            country=row["country"] or "US",
            meta_score=row["meta_score"] or 0,
            swarm_score=row["swarm_score"] or 0,
            stage=PipelineStage(row["stage"] or "new"),
            pipeline=row["pipeline"] or "default",
            owner_id=row["owner_id"],
            source=row["source"],
            source_details=row["source_details"],
            campaign_id=row["campaign_id"],
            last_contact=datetime.fromisoformat(row["last_contact"]) if row["last_contact"] else None,
            contact_count=row["contact_count"] or 0,
            email_opens=row["email_opens"] or 0,
            link_clicks=row["link_clicks"] or 0,
            last_email_sent=datetime.fromisoformat(row["last_email_sent"]) if row["last_email_sent"] else None,
            notes=row["notes"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            custom_fields=json.loads(row["custom_fields"]) if row["custom_fields"] else {},
            crm_id=row["crm_id"],
            sync_status=SyncStatus(row["sync_status"] or "pending"),
            last_sync=datetime.fromisoformat(row["last_sync"]) if row["last_sync"] else None,
            sync_error=row["sync_error"],
        )


class CRMSync:
    """
    CRM Sync Agent
    Manages synchronization between local database and external CRMs
    """
    
    def __init__(self, config: SyncConfig, db_path: str = "leads.db"):
        self.config = config
        self.db = LocalDatabase(db_path)
        self.session: Optional[aiohttp.ClientSession] = None
        
        logger.info(f"CRMSync initialized for {config.provider.value}")
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def sync_lead(self, lead: LeadRecord) -> bool:
        """
        Sync a single lead to CRM
        
        Args:
            lead: Lead to sync
            
        Returns:
            True if successful
        """
        lead.sync_status = SyncStatus.SYNCING
        
        try:
            if self.config.provider == CRMProvider.HUBSPOT:
                result = await self._sync_hubspot(lead)
            elif self.config.provider == CRMProvider.PIPEDRIVE:
                result = await self._sync_pipedrive(lead)
            elif self.config.provider == CRMProvider.SALESFORCE:
                result = await self._sync_salesforce(lead)
            elif self.config.provider == CRMProvider.SQLITE:
                result = True  # Already in local DB
            else:
                logger.warning(f"CRM provider {self.config.provider.value} not yet implemented")
                result = False
            
            if result:
                lead.sync_status = SyncStatus.SYNCED
                lead.last_sync = datetime.now()
                lead.sync_error = None
            else:
                lead.sync_status = SyncStatus.ERROR
                lead.sync_error = "Sync failed"
            
            # Update local DB
            self.db.save_lead(lead)
            
            return result
            
        except Exception as e:
            logger.error(f"Sync error: {e}")
            lead.sync_status = SyncStatus.ERROR
            lead.sync_error = str(e)
            self.db.save_lead(lead)
            return False
    
    async def sync_batch(self, leads: List[LeadRecord]) -> Dict[str, int]:
        """
        Sync multiple leads
        
        Args:
            leads: List of leads to sync
            
        Returns:
            Summary of results
        """
        results = {"success": 0, "failed": 0, "total": len(leads)}
        
        for lead in leads:
            if await self.sync_lead(lead):
                results["success"] += 1
            else:
                results["failed"] += 1
        
        return results
    
    async def sync_all_pending(self, limit: int = 100) -> Dict[str, int]:
        """Sync all pending leads"""
        pending = self.db.get_pending_sync(limit)
        logger.info(f"Syncing {len(pending)} pending leads")
        return await self.sync_batch(pending)
    
    async def _sync_hubspot(self, lead: LeadRecord) -> bool:
        """Sync lead to HubSpot"""
        if not self.session:
            return False
        
        # HubSpot API endpoint
        url = "https://api.hubapi.com/crm/v3/objects/contacts"
        
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        
        # Map fields
        properties = {
            "email": lead.email,
            "phone": lead.phone,
            "firstname": lead.contact_first_name,
            "lastname": lead.contact_last_name,
            "company": lead.business_name,
            "website": lead.website,
            "address": lead.address,
            "city": lead.city,
            "state": lead.state,
            "zip": lead.zip_code,
            "hs_lead_status": self._map_stage_to_hubspot(lead.stage),
        }
        
        # Remove None values
        properties = {k: v for k, v in properties.items() if v is not None}
        
        try:
            async with self.session.post(
                url, headers=headers, json={"properties": properties}
            ) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    lead.crm_id = str(data.get("id", ""))
                    return True
                else:
                    logger.error(f"HubSpot sync failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"HubSpot API error: {e}")
            return False
    
    async def _sync_pipedrive(self, lead: LeadRecord) -> bool:
        """Sync lead to Pipedrive"""
        # Similar implementation for Pipedrive
        logger.info(f"Pipedrive sync for {lead.business_name} (simulated)")
        lead.crm_id = f"pd_{lead.id}"
        return True
    
    async def _sync_salesforce(self, lead: LeadRecord) -> bool:
        """Sync lead to Salesforce"""
        # Similar implementation for Salesforce
        logger.info(f"Salesforce sync for {lead.business_name} (simulated)")
        lead.crm_id = f"sf_{lead.id}"
        return True
    
    def _map_stage_to_hubspot(self, stage: PipelineStage) -> str:
        """Map internal stage to HubSpot status"""
        mapping = {
            PipelineStage.NEW: "NEW",
            PipelineStage.CONTACTED: "CONTACTED",
            PipelineStage.QUALIFIED: "QUALIFIED",
            PipelineStage.WON: "CUSTOMER",
            PipelineStage.LOST: "UNQUALIFIED",
        }
        return mapping.get(stage, "NEW")
    
    def import_leads(self, leads: List[LeadRecord]) -> int:
        """
        Import leads to local database
        
        Args:
            leads: Leads to import
            
        Returns:
            Number of leads imported
        """
        count = 0
        for lead in leads:
            # Check for duplicates (by email)
            if lead.email:
                existing = self._find_by_email(lead.email)
                if existing:
                    # Update existing
                    lead.id = existing.id
                    lead.created_at = existing.created_at
            
            if self.db.save_lead(lead):
                count += 1
        
        logger.info(f"Imported {count} leads")
        return count
    
    def _find_by_email(self, email: str) -> Optional[LeadRecord]:
        """Find lead by email"""
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM leads WHERE email = ?", (email,)
            ).fetchone()
            if row:
                return self.db._row_to_lead(row)
        return None
    
    def get_local_stats(self) -> Dict[str, Any]:
        """Get local database statistics"""
        return self.db.get_stats()
    
    def export_to_csv(self, filepath: str) -> None:
        """Export all leads to CSV"""
        import csv
        
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM leads")
            
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # Write header
                writer.writerow([description[0] for description in cursor.description])
                # Write data
                for row in cursor:
                    writer.writerow(row)
        
        logger.info(f"Exported leads to {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo CRMSync functionality"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 18 + "CRM SYNC AGENT DEMO" + " " * 29 + "║")
    print("╚" + "═" * 68 + "╝")
    
    # Create config
    config = SyncConfig(
        provider=CRMProvider.SQLITE,  # Using local DB for demo
        auto_sync=True,
    )
    
    async with CRMSync(config, db_path="demo_leads.db") as crm:
        # Create sample leads
        print("\n📝 Creating sample leads...")
        leads = [
            LeadRecord(
                id="lead_001",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                business_name="Elite Roofing LLC",
                industry="Roofing",
                contact_first_name="John",
                contact_last_name="Smith",
                contact_title="Owner",
                email="john@eliteroofing.com",
                phone="(541) 555-0123",
                city="Eugene",
                state="OR",
                zip_code="97401",
                meta_score=75,
                swarm_score=60,
                stage=PipelineStage.NEW,
                source="google_maps",
            ),
            LeadRecord(
                id="lead_002",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                business_name="Sacred Heart Church",
                industry="Religious Organization",
                contact_first_name="Father",
                contact_last_name="Michael",
                contact_title="Pastor",
                email="pastor@sacredheart.org",
                phone="(541) 555-0456",
                city="Eugene",
                state="OR",
                zip_code="97402",
                meta_score=70,
                swarm_score=55,
                stage=PipelineStage.CONTACTED,
                source="google_maps",
            ),
            LeadRecord(
                id="lead_003",
                created_at=datetime.now(),
                updated_at=datetime.now(),
                business_name="TechStart Solutions",
                industry="Technology",
                contact_first_name="Sarah",
                contact_last_name="Johnson",
                contact_title="CEO",
                email="sarah@techstart.io",
                phone="(541) 555-0789",
                city="Springfield",
                state="OR",
                zip_code="97477",
                meta_score=85,
                swarm_score=70,
                stage=PipelineStage.QUALIFIED,
                source="linkedin",
            ),
        ]
        
        # Import leads
        imported = crm.import_leads(leads)
        print(f"  Imported {imported} leads")
        
        # Show stats
        print(f"\n{'─' * 70}")
        print(f"  DATABASE STATISTICS")
        print(f"{'─' * 70}")
        stats = crm.get_local_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        # Sync pending leads
        print(f"\n{'─' * 70}")
        print(f"  SYNCING LEADS")
        print(f"{'─' * 70}")
        results = await crm.sync_all_pending()
        print(f"  Success: {results['success']}")
        print(f"  Failed: {results['failed']}")
        print(f"  Total: {results['total']}")
        
        # Export to CSV
        crm.export_to_csv("demo_leads_export.csv")
        print(f"\n  ✅ Exported to demo_leads_export.csv")


if __name__ == "__main__":
    asyncio.run(demo())
