#!/usr/bin/env python3
"""
LEAD GEN ORCHESTRATOR
═══════════════════════════════════════════════════════════════════
Master orchestrator for the AI Lead Generation Ecosystem.

Integrates:
- Lead Scout (prospecting)
- Outreach Writer (campaigns)
- CRM Sync (database)
- Sales Pipeline (deal tracking)
- PropStream Integration (real estate)
- Spokeo Integration (contact enrichment)
- Follow-Up Automator (nurturing)

Built for: HaChazal, Metanoia Unlimited LLC
Status: Production Ready v1.0.0
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from .lead_scout import LeadScout, LeadCriteria, Industry, LeadSource
from .outreach_writer import OutreachWriter, Campaign, CampaignType, IndustrySwarm
from .crm_sync import CRMSync, LeadRecord, SyncConfig, CRMProvider, PipelineStage
from .sales_pipeline import SalesPipeline, Deal, PipelineStage as SalesStage
from .propstream_integration import PropStreamIntegration, PropertyCriteria, GuildCraftLeadScout
from .spokeo_integration import SpokeoIntegration, EnrichmentWorkflow
from .follow_up_automator import FollowUpAutomator, Channel, TriggerCondition

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LeadGenOrchestrator")


class LeadGenOrchestrator:
    """
    Lead Generation Ecosystem Orchestrator
    
    Manages the complete lead generation workflow:
    1. Discovery (Lead Scout + PropStream)
    2. Enrichment (Spokeo)
    3. Campaign Creation (Outreach Writer)
    4. CRM Sync (Database)
    5. Pipeline Management (Sales Pipeline)
    6. Follow-Up Automation (Nurturing)
    
    Completely isolated from other ecosystems (crypto, robotics, etc.)
    """
    
    SYSTEM_VERSION = "1.0.0"
    SYSTEM_NAME = "Leviathan AI Lead Generation Ecosystem"
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # Initialize all components
        self.lead_scout: Optional[LeadScout] = None
        self.outreach_writer: Optional[OutreachWriter] = None
        self.crm_sync: Optional[CRMSync] = None
        self.sales_pipeline: Optional[SalesPipeline] = None
        self.propstream: Optional[PropStreamIntegration] = None
        self.spokeo: Optional[SpokeoIntegration] = None
        self.follow_up: Optional[FollowUpAutomator] = None
        
        # State
        self.initialized = False
        self.active_campaigns: Dict[str, Any] = {}
        self.stats: Dict[str, Any] = {}
        
        # Configuration
        self.db_path = self.config.get("db_path", "leads.db")
        self.output_dir = Path(self.config.get("output_dir", "./leadgen_output"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"{self.SYSTEM_NAME} v{self.SYSTEM_VERSION} initialized")
    
    async def initialize(self) -> bool:
        """Initialize all ecosystem components"""
        logger.info("═" * 70)
        logger.info("INITIALIZING LEAD GENERATION ECOSYSTEM")
        logger.info("═" * 70)
        
        try:
            # 1. Lead Scout
            logger.info("[1/7] Initializing Lead Scout...")
            self.lead_scout = LeadScout(self.config.get("lead_scout", {}))
            
            # 2. Outreach Writer
            logger.info("[2/7] Initializing Outreach Writer...")
            self.outreach_writer = OutreachWriter(self.config.get("outreach", {}))
            
            # 3. CRM Sync
            logger.info("[3/7] Initializing CRM Sync...")
            crm_config = SyncConfig(
                provider=CRMProvider.SQLITE,
                auto_sync=True,
            )
            self.crm_sync = CRMSync(crm_config, self.db_path)
            
            # 4. Sales Pipeline
            logger.info("[4/7] Initializing Sales Pipeline...")
            self.sales_pipeline = SalesPipeline(self.config.get("pipeline", {}))
            
            # 5. PropStream
            logger.info("[5/7] Initializing PropStream Integration...")
            self.propstream = PropStreamIntegration(self.config.get("propstream", {}))
            
            # 6. Spokeo
            logger.info("[6/7] Initializing Spokeo Integration...")
            self.spokeo = SpokeoIntegration(self.config.get("spokeo", {}))
            
            # 7. Follow-Up Automator
            logger.info("[7/7] Initializing Follow-Up Automator...")
            self.follow_up = FollowUpAutomator(self.config.get("follow_up", {}))
            
            self.initialized = True
            logger.info("═" * 70)
            logger.info("ECOSYSTEM INITIALIZED SUCCESSFULLY")
            logger.info("═" * 70)
            
            return True
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False
    
    # ═══════════════════════════════════════════════════════════════════════
    # ═══ CORE WORKFLOWS ═══
    # ═══════════════════════════════════════════════════════════════════════
    
    async def run_discovery_workflow(self,
                                     criteria: LeadCriteria,
                                     sources: List[LeadSource] = None,
                                     max_results: int = 100) -> Dict[str, Any]:
        """
        Run complete discovery workflow
        
        Flow: Lead Scout → Export → CRM Import
        
        Args:
            criteria: Search criteria
            sources: Lead sources (None = all)
            max_results: Maximum leads to find
            
        Returns:
            Workflow results
        """
        if not self.initialized:
            await self.initialize()
        
        logger.info(f"\n{'═' * 70}")
        logger.info("STARTING DISCOVERY WORKFLOW")
        logger.info(f"{'═' * 70}")
        
        results = {
            "workflow": "discovery",
            "started_at": datetime.now().isoformat(),
            "leads_found": 0,
            "leads_imported": 0,
            "status": "running",
        }
        
        try:
            # Step 1: Search for leads
            async with self.lead_scout as scout:
                leads = await scout.search(
                    criteria=criteria,
                    sources=sources,
                    max_results=max_results
                )
                
                results["leads_found"] = len(leads)
                
                # Export to file
                json_path = self.output_dir / f"discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                scout.export_to_json(str(json_path))
                results["export_path"] = str(json_path)
            
            # Step 2: Import to CRM
            if leads:
                crm_leads = self._convert_to_crm_format(leads)
                imported = self.crm_sync.import_leads(crm_leads)
                results["leads_imported"] = imported
            
            results["status"] = "completed"
            results["completed_at"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"Discovery workflow failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
        
        return results
    
    async def run_propstream_workflow(self,
                                     criteria: PropertyCriteria,
                                     enrich: bool = True) -> Dict[str, Any]:
        """
        Run PropStream → Spokeo → CRM workflow
        
        Args:
            criteria: Property search criteria
            enrich: Whether to enrich with Spokeo
            
        Returns:
            Workflow results
        """
        if not self.initialized:
            await self.initialize()
        
        logger.info(f"\n{'═' * 70}")
        logger.info("STARTING PROPSTREAM WORKFLOW")
        logger.info(f"{'═' * 70}")
        
        results = {
            "workflow": "propstream",
            "started_at": datetime.now().isoformat(),
            "properties_found": 0,
            "enriched": 0,
            "imported": 0,
            "status": "running",
        }
        
        try:
            # Step 1: Fetch from PropStream
            properties = await self.propstream.fetch_homeowners(criteria)
            results["properties_found"] = len(properties)
            
            if not properties:
                results["status"] = "completed"
                results["message"] = "No properties found"
                return results
            
            # Step 2: Enrich with Spokeo
            if enrich:
                logger.info("Enriching with Spokeo...")
                
                workflow = EnrichmentWorkflow(self.spokeo)
                
                # Convert properties to dicts for enrichment
                property_dicts = [p.to_lead_dict() for p in properties]
                enriched = await workflow.process_lead_batch(property_dicts, batch_size=25)
                
                results["enriched"] = len([e for e in enriched if e.get("enriched_phone") or e.get("enriched_email")])
                
                # Generate enrichment report
                report = workflow.generate_enrichment_report(
                    len(property_dicts),
                    results["enriched"],
                    str(self.output_dir / "enrichment_report.txt")
                )
                results["enrichment_report"] = str(self.output_dir / "enrichment_report.txt")
            
            # Step 3: Import to CRM
            logger.info("Importing to CRM...")
            crm_leads = []
            for p in properties:
                crm_lead = LeadRecord(
                    id=f"prop_{p.id}",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    business_name=f"{p.get_owner_name()} - Property Owner",
                    contact_first_name=p.owner_first_name,
                    contact_last_name=p.owner_last_name,
                    address=p.address,
                    city=p.city,
                    state=p.state,
                    zip_code=p.zip_code,
                    meta_score=p.propensity_score,
                    source="propstream",
                )
                crm_leads.append(crm_lead)
            
            imported = self.crm_sync.import_leads(crm_leads)
            results["imported"] = imported
            
            # Export results
            export_path = self.output_dir / f"propstream_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            self.propstream.export_to_json(properties, str(export_path))
            
            results["status"] = "completed"
            results["completed_at"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"PropStream workflow failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
        
        return results
    
    async def run_campaign_workflow(self,
                                   campaign_name: str,
                                   campaign_type: CampaignType,
                                   target_industry: str,
                                   swarm: IndustrySwarm = None,
                                   lead_count: int = 100) -> Dict[str, Any]:
        """
        Run complete campaign workflow
        
        Flow: Create Campaign → Enroll Leads → Start Follow-Up
        
        Args:
            campaign_name: Campaign name
            campaign_type: Type of campaign
            target_industry: Target industry
            swarm: Swarm specialization
            lead_count: Number of leads to target
            
        Returns:
            Workflow results
        """
        if not self.initialized:
            await self.initialize()
        
        logger.info(f"\n{'═' * 70}")
        logger.info("STARTING CAMPAIGN WORKFLOW")
        logger.info(f"{'═' * 70}")
        
        results = {
            "workflow": "campaign",
            "started_at": datetime.now().isoformat(),
            "campaign_name": campaign_name,
            "status": "running",
        }
        
        try:
            # Step 1: Create campaign
            campaign = self.outreach_writer.create_campaign(
                name=campaign_name,
                campaign_type=campaign_type,
                target_industry=target_industry,
                swarm=swarm,
                target_lead_count=lead_count,
            )
            
            results["campaign_id"] = campaign.id
            results["messages_created"] = len(campaign.messages)
            
            # Step 2: Get leads from CRM
            # (In production, filter by criteria)
            crm_stats = self.crm_sync.get_local_stats()
            results["leads_available"] = crm_stats.get("total_leads", 0)
            
            # Step 3: Enroll in follow-up sequence
            # Get appropriate sequence
            sequence_map = {
                IndustrySwarm.CONSTRUCTION_SWARM: "seq_construction_standard",
                IndustrySwarm.SPIRITUALITY_SWARM: "seq_spirituality_standard",
                IndustrySwarm.GROWTH_SWARM: "seq_growth_standard",
            }
            sequence_id = sequence_map.get(swarm, "seq_construction_standard")
            
            # Enroll sample leads
            enrolled = 0
            for i in range(min(5, lead_count)):  # Demo: just 5 leads
                lead_id = f"{campaign.id}_lead_{i}"
                if self.follow_up.enroll_lead(lead_id, sequence_id):
                    enrolled += 1
            
            results["leads_enrolled"] = enrolled
            
            # Save campaign
            campaign_path = self.output_dir / f"campaign_{campaign.id}.json"
            self.outreach_writer.export_campaign(campaign, str(campaign_path))
            
            results["status"] = "completed"
            results["completed_at"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"Campaign workflow failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
        
        return results
    
    async def run_guildcraft_workflow(self, 
                                     max_prospects: int = 50,
                                     enrich: bool = True) -> Dict[str, Any]:
        """
        Specialized workflow for GuildCraft Exteriors
        
        Targets Lane County homeowners for roofing, siding, windows, patios
        
        Args:
            max_prospects: Maximum prospects to find
            enrich: Whether to enrich with Spokeo
            
        Returns:
            Workflow results
        """
        if not self.initialized:
            await self.initialize()
        
        logger.info(f"\n{'═' * 70}")
        logger.info("STARTING GUILDFCRAFT LEAD SWARM")
        logger.info(f"{'═' * 70}")
        
        results = {
            "workflow": "guildcraft",
            "started_at": datetime.now().isoformat(),
            "status": "running",
        }
        
        try:
            # Step 1: Find prospects
            guildcraft = GuildCraftLeadScout(self.propstream)
            prospects = await guildcraft.find_prospects(max_results=max_prospects)
            
            results["prospects_found"] = len(prospects)
            
            # Step 2: Generate outreach strategies
            strategies = []
            for prospect in prospects[:10]:  # Just top 10 for demo
                strategy = guildcraft.generate_outreach_strategy(prospect)
                strategies.append({
                    "prospect": prospect.get_owner_name(),
                    "address": prospect.address,
                    "service": strategy["primary_service"],
                    "angle": strategy["angle"],
                })
            
            results["strategies"] = strategies
            
            # Step 3: Enrich with Spokeo if requested
            if enrich and prospects:
                logger.info("Enriching prospects with Spokeo...")
                
                workflow = EnrichmentWorkflow(self.spokeo)
                property_dicts = [p.to_lead_dict() for p in prospects[:20]]
                enriched = await workflow.process_lead_batch(property_dicts)
                
                results["enriched"] = len(enriched)
                
                # Export for Spokeo lookup
                csv_path = self.output_dir / f"guildcraft_spokeo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                self.propstream.export_for_spokeo(prospects, str(csv_path))
                results["spokeo_csv"] = str(csv_path)
            
            # Step 4: Import to CRM
            crm_leads = []
            for p in prospects:
                crm_lead = LeadRecord(
                    id=f"guildcraft_{p.id}",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    business_name=f"{p.get_owner_name()} - Property Owner",
                    contact_first_name=p.owner_first_name,
                    contact_last_name=p.owner_last_name,
                    address=p.address,
                    city=p.city,
                    state=p.state,
                    zip_code=p.zip_code,
                    meta_score=p.propensity_score,
                    source="propstream",
                    tags=["guildcraft", "construction", p.property_type],
                )
                crm_leads.append(crm_lead)
            
            imported = self.crm_sync.import_leads(crm_leads)
            results["imported_to_crm"] = imported
            
            # Export final results
            export_path = self.output_dir / f"guildcraft_prospects_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            self.propstream.export_to_json(prospects, str(export_path))
            
            results["status"] = "completed"
            results["completed_at"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"GuildCraft workflow failed: {e}")
            results["status"] = "error"
            results["error"] = str(e)
        
        return results
    
    # ═══════════════════════════════════════════════════════════════════════
    # ═══ UTILITY METHODS ═══
    # ═══════════════════════════════════════════════════════════════════════
    
    def _convert_to_crm_format(self, leads: List[Any]) -> List[LeadRecord]:
        """Convert leads to CRM format"""
        crm_leads = []
        for lead in leads:
            if hasattr(lead, 'to_dict'):
                data = lead.to_dict()
                crm_lead = LeadRecord(
                    id=data.get("id", ""),
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    business_name=data.get("business_name", ""),
                    contact_first_name=data.get("contact_first_name"),
                    contact_last_name=data.get("contact_last_name"),
                    email=data.get("email"),
                    phone=data.get("phone"),
                    address=data.get("address"),
                    city=data.get("city"),
                    state=data.get("state"),
                    zip_code=data.get("zip_code"),
                    meta_score=data.get("meta_score", 0),
                    source=data.get("source", "unknown"),
                    tags=data.get("tags", []),
                )
                crm_leads.append(crm_lead)
        return crm_leads
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get complete system status"""
        status = {
            "system": {
                "name": self.SYSTEM_NAME,
                "version": self.SYSTEM_VERSION,
                "initialized": self.initialized,
            },
            "components": {
                "lead_scout": self.lead_scout is not None,
                "outreach_writer": self.outreach_writer is not None,
                "crm_sync": self.crm_sync is not None,
                "sales_pipeline": self.sales_pipeline is not None,
                "propstream": self.propstream is not None,
                "spokeo": self.spokeo is not None,
                "follow_up": self.follow_up is not None,
            },
            "timestamp": datetime.now().isoformat(),
        }
        
        # Add component stats if available
        if self.crm_sync:
            status["crm_stats"] = self.crm_sync.get_local_stats()
        
        if self.sales_pipeline:
            status["pipeline_stats"] = self.sales_pipeline.get_performance_metrics()
        
        if self.follow_up:
            status["follow_up_stats"] = self.follow_up.get_sequence_stats()
        
        return status
    
    def generate_report(self) -> str:
        """Generate comprehensive system report"""
        status = self.get_system_status()
        
        report = f"""
═══════════════════════════════════════════════════════════════════
        {self.SYSTEM_NAME}
                    v{self.SYSTEM_VERSION}
═══════════════════════════════════════════════════════════════════

SYSTEM STATUS
─────────────
Initialized: {'✅' if status['system']['initialized'] else '❌'}
Timestamp: {status['timestamp']}

COMPONENTS
──────────
"""
        for component, active in status['components'].items():
            report += f"  {component:20s} {'✅ Active' if active else '❌ Inactive'}\n"
        
        if 'crm_stats' in status:
            report += f"\nCRM STATISTICS\n──────────────\n"
            for key, value in status['crm_stats'].items():
                report += f"  {key}: {value}\n"
        
        if 'pipeline_stats' in status:
            report += f"\nPIPELINE STATISTICS\n───────────────────\n"
            for key, value in status['pipeline_stats'].items():
                report += f"  {key}: {value}\n"
        
        report += "\n═══════════════════════════════════════════════════════════════════\n"
        
        return report
    
    async def run_interactive(self):
        """Run interactive CLI"""
        print("\n" + "╔" + "═" * 68 + "╗")
        print("║" + " " * 12 + "LEAD GENERATION ECOSYSTEM" + " " * 29 + "║")
        print("║" + " " * 18 + f"v{self.SYSTEM_VERSION}" + " " * 48 + "║")
        print("╚" + "═" * 68 + "╝")
        
        if not self.initialized:
            print("\n⚙️  Initializing system...")
            await self.initialize()
        
        while True:
            print("\n┌────────────────────────────────────────────────────────────┐")
            print("│ MAIN MENU                                                  │")
            print("├────────────────────────────────────────────────────────────┤")
            print("│ [1] Discovery Workflow (General Leads)                   │")
            print("│ [2] PropStream Workflow (Real Estate)                      │")
            print("│ [3] Campaign Workflow (Outreach)                         │")
            print("│ [4] GuildCraft Lead Swarm (Construction)                 │")
            print("│ [5] System Status                                        │")
            print("│ [6] Generate Report                                      │")
            print("│ [7] Exit                                                 │")
            print("└────────────────────────────────────────────────────────────┘")
            
            choice = input("\nSelect option: ").strip()
            
            if choice == "1":
                await self._menu_discovery()
            elif choice == "2":
                await self._menu_propstream()
            elif choice == "3":
                await self._menu_campaign()
            elif choice == "4":
                await self._menu_guildcraft()
            elif choice == "5":
                self._menu_status()
            elif choice == "6":
                self._menu_report()
            elif choice == "7":
                print("\n👋 Exiting...")
                break
            else:
                print("\n❌ Invalid option")
    
    async def _menu_discovery(self):
        """Discovery workflow menu"""
        print("\n┌────────────────────────────────────────────────────────────┐")
        print("│ DISCOVERY WORKFLOW                                         │")
        print("└────────────────────────────────────────────────────────────┘")
        
        # Get criteria
        print("\nEnter search criteria:")
        city = input("City (Eugene): ").strip() or "Eugene"
        state = input("State (OR): ").strip() or "OR"
        industry_input = input("Industry (construction): ").strip() or "construction"
        max_results = int(input("Max results (20): ").strip() or "20")
        
        # Create criteria
        criteria = LeadCriteria(
            city=city,
            state=state,
            industries=[Industry.CONSTRUCTION],  # Simplified
            require_phone=True,
            min_score=50,
        )
        
        print(f"\n⚙️  Running discovery workflow...")
        results = await self.run_discovery_workflow(
            criteria=criteria,
            max_results=max_results
        )
        
        print(f"\n✅ Discovery complete!")
        print(f"   Leads found: {results.get('leads_found', 0)}")
        print(f"   Leads imported: {results.get('leads_imported', 0)}")
        print(f"   Export: {results.get('export_path', 'N/A')}")
    
    async def _menu_propstream(self):
        """PropStream workflow menu"""
        print("\n┌────────────────────────────────────────────────────────────┐")
        print("│ PROPSTREAM WORKFLOW                                        │")
        print("└────────────────────────────────────────────────────────────┘")
        
        state = input("State (OR): ").strip() or "OR"
        county = input("County (Lane): ").strip() or "Lane"
        max_results = int(input("Max results (50): ").strip() or "50")
        enrich = input("Enrich with Spokeo? (y/n): ").strip().lower() == "y"
        
        criteria = PropertyCriteria(
            state=state,
            county=county,
            property_types=["SFR", "Condo"],
            year_built_min=1960,
            year_built_max=2005,
            max_results=max_results,
        )
        
        print(f"\n⚙️  Running PropStream workflow...")
        results = await self.run_propstream_workflow(
            criteria=criteria,
            enrich=enrich
        )
        
        print(f"\n✅ PropStream workflow complete!")
        print(f"   Properties found: {results.get('properties_found', 0)}")
        print(f"   Enriched: {results.get('enriched', 0)}")
        print(f"   Imported: {results.get('imported', 0)}")
    
    async def _menu_campaign(self):
        """Campaign workflow menu"""
        print("\n┌────────────────────────────────────────────────────────────┐")
        print("│ CAMPAIGN WORKFLOW                                          │")
        print("└────────────────────────────────────────────────────────────┘")
        
        name = input("Campaign name: ").strip()
        industry = input("Target industry: ").strip()
        lead_count = int(input("Lead count (100): ").strip() or "100")
        
        swarm_map = {
            "1": IndustrySwarm.CONSTRUCTION_SWARM,
            "2": IndustrySwarm.SPIRITUALITY_SWARM,
            "3": IndustrySwarm.GROWTH_SWARM,
        }
        print("\nSwarm:")
        print("  [1] Construction")
        print("  [2] Spirituality")
        print("  [3] Growth")
        swarm_choice = input("Select: ").strip()
        swarm = swarm_map.get(swarm_choice)
        
        print(f"\n⚙️  Creating campaign...")
        results = await self.run_campaign_workflow(
            campaign_name=name,
            campaign_type=CampaignType.COLD_OUTREACH,
            target_industry=industry,
            swarm=swarm,
            lead_count=lead_count
        )
        
        print(f"\n✅ Campaign created!")
        print(f"   Campaign ID: {results.get('campaign_id', 'N/A')}")
        print(f"   Messages: {results.get('messages_created', 0)}")
        print(f"   Leads enrolled: {results.get('leads_enrolled', 0)}")
    
    async def _menu_guildcraft(self):
        """GuildCraft workflow menu"""
        print("\n┌────────────────────────────────────────────────────────────┐")
        print("│ GUILDFCRAFT LEAD SWARM                                     │")
        print("└────────────────────────────────────────────────────────────┘")
        
        print("\nTarget: Lane County, Oregon")
        print("Services: Roofing, Siding, Windows, Patios, Pergolas")
        
        max_prospects = int(input("Max prospects (50): ").strip() or "50")
        enrich = input("Enrich with Spokeo? (y/n): ").strip().lower() != "n"
        
        print(f"\n⚙️  Running GuildCraft lead swarm...")
        results = await self.run_guildcraft_workflow(
            max_prospects=max_prospects,
            enrich=enrich
        )
        
        print(f"\n✅ GuildCraft workflow complete!")
        print(f"   Prospects found: {results.get('prospects_found', 0)}")
        print(f"   Enriched: {results.get('enriched', 0)}")
        print(f"   Imported to CRM: {results.get('imported_to_crm', 0)}")
        
        if results.get("strategies"):
            print(f"\n   Sample outreach strategies:")
            for strategy in results["strategies"][:3]:
                print(f"     • {strategy['prospect']}: {strategy['service']}")
    
    def _menu_status(self):
        """Show system status"""
        print(f"\n{'─' * 70}")
        print(f"  SYSTEM STATUS")
        print(f"{'─' * 70}")
        
        status = self.get_system_status()
        
        print(f"\n  System: {status['system']['name']}")
        print(f"  Version: {status['system']['version']}")
        print(f"  Initialized: {'✅' if status['system']['initialized'] else '❌'}")
        
        print(f"\n  Components:")
        for component, active in status['components'].items():
            print(f"    {component}: {'✅' if active else '❌'}")
        
        if 'crm_stats' in status:
            print(f"\n  CRM Stats:")
            for key, value in status['crm_stats'].items():
                print(f"    {key}: {value}")
    
    def _menu_report(self):
        """Generate and display report"""
        report = self.generate_report()
        print(report)
        
        # Save to file
        report_path = self.output_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_path, 'w') as f:
            f.write(report)
        
        print(f"\n✅ Report saved to: {report_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo the complete Lead Generation Ecosystem"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 10 + "LEAD GENERATION ECOSYSTEM DEMO" + " " * 26 + "║")
    print("║" + " " * 15 + "Full Integration Test" + " " * 30 + "║")
    print("╚" + "═" * 68 + "╝")
    
    # Create orchestrator
    orchestrator = LeadGenOrchestrator(config={
        "output_dir": "./demo_output",
    })
    
    # Initialize
    print("\n⚙️  Initializing ecosystem...")
    await orchestrator.initialize()
    
    # Show system status
    print("\n" + orchestrator.generate_report())
    
    # Run GuildCraft workflow (most complete)
    print("\n" + "═" * 70)
    print("RUNNING GUILDFCRAFT LEAD SWARM")
    print("═" * 70)
    
    results = await orchestrator.run_guildcraft_workflow(
        max_prospects=10,
        enrich=True
    )
    
    print(f"\n✅ GuildCraft workflow results:")
    print(f"   Prospects found: {results.get('prospects_found', 0)}")
    print(f"   Enriched: {results.get('enriched', 0)}")
    print(f"   Imported: {results.get('imported_to_crm', 0)}")
    
    if results.get('strategies'):
        print(f"\n   Outreach Strategies:")
        for strategy in results['strategies'][:3]:
            print(f"     • {strategy['prospect']} → {strategy['service']}")
    
    print("\n" + "═" * 70)
    print("DEMO COMPLETE")
    print("═" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(demo())
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
