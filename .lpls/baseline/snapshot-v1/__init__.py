#!/usr/bin/env python3
"""
LEVIATHAN AI LEAD GENERATION ECOSYSTEM
═══════════════════════════════════════════════════════════════════
Complete Lead Generation System for Metanoia Unlimited LLC

Components:
1. LeadScout - Prospecting and lead discovery
2. OutreachWriter - Campaign creation and email generation
3. CRMSync - Database synchronization
4. SalesPipeline - Pipeline management
5. PropStreamIntegration - Real estate lead harvesting
6. SpokeoIntegration - Contact enrichment
7. FollowUpAutomator - Automated follow-up sequences

Built for: HaChazal, Metanoia Unlimited LLC
Status: Production Ready v1.0.0
"""

__version__ = "1.0.0"
__author__ = "Malika for HaChazal"

from .lead_scout import LeadScout, LeadCriteria, LeadSource
from .outreach_writer import OutreachWriter, Campaign, EmailTemplate
from .crm_sync import CRMSync, LeadRecord, SyncConfig
from .sales_pipeline import SalesPipeline, PipelineStage, Deal
from .propstream_integration import PropStreamIntegration
from .spokeo_integration import SpokeoIntegration
from .follow_up_automator import FollowUpAutomator, FollowUpSequence
from .leadgen_orchestrator import LeadGenOrchestrator

__all__ = [
    # Core Agents
    "LeadScout",
    "LeadCriteria",
    "LeadSource",
    "OutreachWriter",
    "Campaign",
    "EmailTemplate",
    "CRMSync",
    "LeadRecord",
    "SyncConfig",
    "SalesPipeline",
    "PipelineStage",
    "Deal",
    # Integrations
    "PropStreamIntegration",
    "SpokeoIntegration",
    # Automation
    "FollowUpAutomator",
    "FollowUpSequence",
    # Orchestrator
    "LeadGenOrchestrator",
]

# System metadata
SYSTEM_CONFIG = {
    "name": "Leviathan AI Lead Generation Ecosystem",
    "version": "1.0.0",
    "author": "Malika for HaChazal",
    "company": "Metanoia Unlimited LLC",
    "ecosystem": "LeadGen",
    "isolation_level": "complete",
    "agents_count": 12,
    "integrations": ["PropStream", "Spokeo", "CRM", "Email"],
}
