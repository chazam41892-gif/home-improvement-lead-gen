#!/usr/bin/env python3
"""
SALES PIPELINE MANAGER
═══════════════════════════════════════════════════════════════════
Complete sales pipeline management with deal tracking.

Features:
- Pipeline stage management
- Deal tracking and forecasting
- Activity logging
- Win/loss analysis
- Team collaboration
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from collections import defaultdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SalesPipeline")


class PipelineStage(Enum):
    """Standard pipeline stages"""
    NEW = "new"
    PROSPECTING = "prospecting"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    MEETING_SCHEDULED = "meeting_scheduled"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    CONTRACT_SENT = "contract_sent"
    WON = "won"
    LOST = "lost"
    DISQUALIFIED = "disqualified"
    ON_HOLD = "on_hold"


class DealPriority(Enum):
    """Deal priority levels"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ActivityType(Enum):
    """Activity types for deal tracking"""
    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    SMS = "sms"
    NOTE = "note"
    TASK = "task"
    PROPOSAL = "proposal"
    CONTRACT = "contract"
    FOLLOW_UP = "follow_up"
    VOICEMAIL = "voicemail"


@dataclass
class Activity:
    """Pipeline activity record"""
    id: str
    deal_id: str
    activity_type: ActivityType
    timestamp: datetime
    description: str
    performed_by: str  # User/agent ID
    duration_minutes: Optional[int] = None
    outcome: Optional[str] = None
    next_action: Optional[str] = None
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "deal_id": self.deal_id,
            "type": self.activity_type.value,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "performed_by": self.performed_by,
            "duration_minutes": self.duration_minutes,
            "outcome": self.outcome,
            "next_action": self.next_action,
        }


@dataclass
class Deal:
    """Sales deal record"""
    id: str
    created_at: datetime
    updated_at: datetime
    
    # Deal Info
    title: str
    company_name: str
    contact_name: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    
    # Deal Value
    value: float = 0.0
    currency: str = "USD"
    probability: int = 10  # 0-100
    expected_close_date: Optional[datetime] = None
    actual_close_date: Optional[datetime] = None
    
    # Categorization
    stage: PipelineStage = PipelineStage.NEW
    priority: DealPriority = DealPriority.MEDIUM
    source: Optional[str] = None
    industry: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    # Assignment
    owner_id: Optional[str] = None
    team_id: Optional[str] = None
    
    # Status
    status: str = "open"  # open, won, lost, on_hold
    loss_reason: Optional[str] = None
    loss_notes: Optional[str] = None
    
    # Scoring
    lead_score: int = 0
    deal_score: int = 0  # Calculated based on activity
    
    # Tracking
    activities: List[Activity] = field(default_factory=list)
    products_services: List[str] = field(default_factory=list)
    competitors: List[str] = field(default_factory=list)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Calculate deal score"""
        self.deal_score = self._calculate_deal_score()
    
    def _calculate_deal_score(self) -> int:
        """Calculate deal health score (0-100)"""
        score = self.lead_score
        
        # Activity bonus
        score += min(len(self.activities) * 2, 20)
        
        # Stage progression bonus
        stage_scores = {
            PipelineStage.NEW: 0,
            PipelineStage.CONTACTED: 5,
            PipelineStage.QUALIFIED: 15,
            PipelineStage.MEETING_SCHEDULED: 25,
            PipelineStage.PROPOSAL_SENT: 35,
            PipelineStage.NEGOTIATION: 45,
            PipelineStage.CONTRACT_SENT: 50,
            PipelineStage.WON: 100,
        }
        score += stage_scores.get(self.stage, 0)
        
        # Priority bonus
        if self.priority == DealPriority.HIGH:
            score += 5
        elif self.priority == DealPriority.CRITICAL:
            score += 10
        
        return min(score, 100)
    
    def update_stage(self, new_stage: PipelineStage, reason: Optional[str] = None) -> None:
        """Update deal stage"""
        old_stage = self.stage
        self.stage = new_stage
        self.updated_at = datetime.now()
        
        # Log activity
        activity = Activity(
            id=f"act_{datetime.now().timestamp()}",
            deal_id=self.id,
            activity_type=ActivityType.NOTE,
            timestamp=datetime.now(),
            description=f"Stage changed from {old_stage.value} to {new_stage.value}",
            performed_by="system",
            notes=reason,
        )
        self.activities.append(activity)
        
        # Update status if closed
        if new_stage == PipelineStage.WON:
            self.status = "won"
            self.actual_close_date = datetime.now()
            self.probability = 100
        elif new_stage == PipelineStage.LOST:
            self.status = "lost"
            self.actual_close_date = datetime.now()
            self.probability = 0
        
        # Recalculate score
        self.deal_score = self._calculate_deal_score()
    
    def add_activity(self, activity: Activity) -> None:
        """Add activity to deal"""
        self.activities.append(activity)
        self.updated_at = datetime.now()
        self.deal_score = self._calculate_deal_score()
    
    def get_weighted_value(self) -> float:
        """Get probability-weighted deal value"""
        return self.value * (self.probability / 100)
    
    def get_days_in_stage(self) -> int:
        """Get number of days in current stage"""
        if not self.activities:
            return (datetime.now() - self.created_at).days
        
        # Find last stage change
        stage_changes = [
            a for a in self.activities 
            if "Stage changed" in a.description
        ]
        if stage_changes:
            last_change = max(stage_changes, key=lambda a: a.timestamp)
            return (datetime.now() - last_change.timestamp).days
        
        return (datetime.now() - self.created_at).days
    
    def get_next_action(self) -> Optional[Activity]:
        """Get next scheduled action"""
        future = [
            a for a in self.activities 
            if a.next_action and a.timestamp > datetime.now()
        ]
        if future:
            return min(future, key=lambda a: a.timestamp)
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "company_name": self.company_name,
            "contact_name": self.contact_name,
            "value": self.value,
            "currency": self.currency,
            "probability": self.probability,
            "stage": self.stage.value,
            "status": self.status,
            "priority": self.priority.name,
            "lead_score": self.lead_score,
            "deal_score": self.deal_score,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expected_close": self.expected_close_date.isoformat() if self.expected_close_date else None,
            "tags": self.tags,
        }


@dataclass
class Pipeline:
    """Pipeline configuration"""
    id: str
    name: str
    description: Optional[str] = None
    stages: List[PipelineStage] = field(default_factory=lambda: [
        PipelineStage.NEW,
        PipelineStage.CONTACTED,
        PipelineStage.QUALIFIED,
        PipelineStage.PROPOSAL_SENT,
        PipelineStage.NEGOTIATION,
        PipelineStage.WON,
        PipelineStage.LOST,
    ])
    
    def get_stage_index(self, stage: PipelineStage) -> int:
        """Get stage position in pipeline"""
        try:
            return self.stages.index(stage)
        except ValueError:
            return -1
    
    def get_next_stage(self, current_stage: PipelineStage) -> Optional[PipelineStage]:
        """Get next stage in pipeline"""
        idx = self.get_stage_index(current_stage)
        if idx >= 0 and idx < len(self.stages) - 1:
            return self.stages[idx + 1]
        return None
    
    def get_previous_stage(self, current_stage: PipelineStage) -> Optional[PipelineStage]:
        """Get previous stage in pipeline"""
        idx = self.get_stage_index(current_stage)
        if idx > 0:
            return self.stages[idx - 1]
        return None


class SalesPipeline:
    """
    Sales Pipeline Manager
    Complete pipeline management for sales teams
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.deals: Dict[str, Deal] = {}
        self.pipelines: Dict[str, Pipeline] = {}
        self.activities: List[Activity] = []
        
        # Create default pipeline
        self._create_default_pipeline()
        
        logger.info("SalesPipeline initialized")
    
    def _create_default_pipeline(self) -> None:
        """Create default sales pipeline"""
        default = Pipeline(
            id="pipeline_default",
            name="Default Sales Pipeline",
            description="Standard B2B sales pipeline",
        )
        self.pipelines[default.id] = default
    
    def create_deal(self,
                   title: str,
                   company_name: str,
                   contact_name: str,
                   value: float = 0.0,
                   stage: PipelineStage = PipelineStage.NEW,
                   priority: DealPriority = DealPriority.MEDIUM,
                   owner_id: Optional[str] = None,
                   **kwargs) -> Deal:
        """
        Create a new deal
        
        Args:
            title: Deal title
            company_name: Company name
            contact_name: Primary contact name
            value: Deal value
            stage: Initial pipeline stage
            priority: Deal priority
            owner_id: Assigned owner
            **kwargs: Additional deal attributes
            
        Returns:
            Created deal
        """
        deal = Deal(
            id=f"deal_{datetime.now().timestamp()}",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            title=title,
            company_name=company_name,
            contact_name=contact_name,
            contact_email=kwargs.get("contact_email"),
            contact_phone=kwargs.get("contact_phone"),
            value=value,
            currency=kwargs.get("currency", "USD"),
            probability=kwargs.get("probability", 10),
            expected_close_date=kwargs.get("expected_close_date"),
            stage=stage,
            priority=priority,
            source=kwargs.get("source"),
            industry=kwargs.get("industry"),
            tags=kwargs.get("tags", []),
            owner_id=owner_id,
            lead_score=kwargs.get("lead_score", 0),
        )
        
        self.deals[deal.id] = deal
        logger.info(f"Created deal: {title} (${value:,.2f})")
        
        return deal
    
    def get_deal(self, deal_id: str) -> Optional[Deal]:
        """Get deal by ID"""
        return self.deals.get(deal_id)
    
    def update_deal_stage(self, 
                         deal_id: str, 
                         new_stage: PipelineStage,
                         reason: Optional[str] = None) -> bool:
        """
        Update deal stage
        
        Args:
            deal_id: Deal ID
            new_stage: New pipeline stage
            reason: Reason for stage change
            
        Returns:
            True if successful
        """
        deal = self.deals.get(deal_id)
        if not deal:
            logger.error(f"Deal not found: {deal_id}")
            return False
        
        deal.update_stage(new_stage, reason)
        logger.info(f"Updated deal {deal_id} to stage {new_stage.value}")
        return True
    
    def advance_deal(self, deal_id: str, reason: Optional[str] = None) -> bool:
        """Move deal to next stage"""
        deal = self.deals.get(deal_id)
        if not deal:
            return False
        
        pipeline = self.pipelines.get("pipeline_default")
        if not pipeline:
            return False
        
        next_stage = pipeline.get_next_stage(deal.stage)
        if next_stage:
            return self.update_deal_stage(deal_id, next_stage, reason)
        
        return False
    
    def move_deal_backward(self, deal_id: str, reason: Optional[str] = None) -> bool:
        """Move deal to previous stage"""
        deal = self.deals.get(deal_id)
        if not deal:
            return False
        
        pipeline = self.pipelines.get("pipeline_default")
        if not pipeline:
            return False
        
        prev_stage = pipeline.get_previous_stage(deal.stage)
        if prev_stage:
            return self.update_deal_stage(deal_id, prev_stage, reason)
        
        return False
    
    def log_activity(self,
                    deal_id: str,
                    activity_type: ActivityType,
                    description: str,
                    performed_by: str,
                    **kwargs) -> Activity:
        """
        Log activity on a deal
        
        Args:
            deal_id: Deal ID
            activity_type: Type of activity
            description: Activity description
            performed_by: User/agent who performed
            **kwargs: Additional activity attributes
            
        Returns:
            Created activity
        """
        deal = self.deals.get(deal_id)
        if not deal:
            logger.error(f"Deal not found: {deal_id}")
            return None
        
        activity = Activity(
            id=f"act_{datetime.now().timestamp()}",
            deal_id=deal_id,
            activity_type=activity_type,
            timestamp=datetime.now(),
            description=description,
            performed_by=performed_by,
            duration_minutes=kwargs.get("duration_minutes"),
            outcome=kwargs.get("outcome"),
            next_action=kwargs.get("next_action"),
            notes=kwargs.get("notes"),
        )
        
        deal.add_activity(activity)
        self.activities.append(activity)
        
        logger.info(f"Logged {activity_type.value} on deal {deal_id}")
        return activity
    
    def get_deals_by_stage(self, stage: PipelineStage) -> List[Deal]:
        """Get all deals in a stage"""
        return [d for d in self.deals.values() if d.stage == stage]
    
    def get_deals_by_owner(self, owner_id: str) -> List[Deal]:
        """Get all deals owned by user"""
        return [d for d in self.deals.values() if d.owner_id == owner_id]
    
    def get_pipeline_view(self) -> Dict[str, List[Deal]]:
        """Get pipeline organized by stage"""
        view = defaultdict(list)
        for deal in self.deals.values():
            view[deal.stage.value].append(deal)
        
        # Sort by value desc
        for stage in view:
            view[stage].sort(key=lambda d: d.value, reverse=True)
        
        return dict(view)
    
    def get_forecast(self, days: int = 30) -> Dict[str, Any]:
        """
        Get sales forecast
        
        Args:
            days: Forecast period in days
            
        Returns:
            Forecast data
        """
        cutoff = datetime.now() + timedelta(days=days)
        
        # Get deals expected to close
        forecast_deals = [
            d for d in self.deals.values()
            if d.expected_close_date and d.expected_close_date <= cutoff
            and d.status == "open"
        ]
        
        # Calculate weighted value
        total_weighted = sum(d.get_weighted_value() for d in forecast_deals)
        total_unweighted = sum(d.value for d in forecast_deals)
        
        # By stage
        by_stage = defaultdict(float)
        for deal in forecast_deals:
            by_stage[deal.stage.value] += deal.get_weighted_value()
        
        return {
            "period_days": days,
            "total_deals": len(forecast_deals),
            "weighted_value": total_weighted,
            "unweighted_value": total_unweighted,
            "by_stage": dict(by_stage),
            "average_probability": sum(d.probability for d in forecast_deals) / len(forecast_deals) if forecast_deals else 0,
        }
    
    def get_performance_metrics(self, 
                             owner_id: Optional[str] = None,
                             period_days: int = 30) -> Dict[str, Any]:
        """
        Get performance metrics
        
        Args:
            owner_id: Filter by owner (None for all)
            period_days: Analysis period
            
        Returns:
            Performance metrics
        """
        cutoff = datetime.now() - timedelta(days=period_days)
        
        deals = self.deals.values()
        if owner_id:
            deals = [d for d in deals if d.owner_id == owner_id]
        
        # Won deals in period
        won = [d for d in deals if d.status == "won" and d.actual_close_date and d.actual_close_date >= cutoff]
        
        # Lost deals in period
        lost = [d for d in deals if d.status == "lost" and d.actual_close_date and d.actual_close_date >= cutoff]
        
        # New deals in period
        new = [d for d in deals if d.created_at >= cutoff]
        
        # Win rate
        closed = len(won) + len(lost)
        win_rate = len(won) / closed if closed > 0 else 0
        
        # Revenue
        won_revenue = sum(d.value for d in won)
        lost_revenue = sum(d.value for d in lost)
        
        # Average deal size
        avg_deal_size = won_revenue / len(won) if won else 0
        
        # Pipeline velocity (deals moved forward)
        activities_in_period = [
            a for a in self.activities 
            if a.timestamp >= cutoff and "Stage changed" in a.description
        ]
        
        return {
            "period_days": period_days,
            "deals_won": len(won),
            "deals_lost": len(lost),
            "deals_created": len(new),
            "win_rate": win_rate,
            "win_rate_pct": f"{win_rate*100:.1f}%",
            "revenue_won": won_revenue,
            "revenue_lost": lost_revenue,
            "avg_deal_size": avg_deal_size,
            "total_pipeline_value": sum(d.get_weighted_value() for d in deals if d.status == "open"),
            "stage_advances": len(activities_in_period),
        }
    
    def get_stalled_deals(self, days_threshold: int = 14) -> List[Deal]:
        """Get deals with no activity for threshold days"""
        cutoff = datetime.now() - timedelta(days=days_threshold)
        
        stalled = []
        for deal in self.deals.values():
            if deal.status != "open":
                continue
            
            if not deal.activities:
                if deal.created_at < cutoff:
                    stalled.append(deal)
            else:
                last_activity = max(a.timestamp for a in deal.activities)
                if last_activity < cutoff:
                    stalled.append(deal)
        
        return stalled
    
    def get_win_loss_analysis(self, period_days: int = 90) -> Dict[str, Any]:
        """Analyze won vs lost deals"""
        cutoff = datetime.now() - timedelta(days=period_days)
        
        won = [d for d in self.deals.values() 
               if d.status == "won" and d.actual_close_date and d.actual_close_date >= cutoff]
        lost = [d for d in self.deals.values() 
                if d.status == "lost" and d.actual_close_date and d.actual_close_date >= cutoff]
        
        # Common loss reasons
        loss_reasons = defaultdict(int)
        for deal in lost:
            if deal.loss_reason:
                loss_reasons[deal.loss_reason] += 1
        
        # Average cycle time
        def avg_cycle(deals):
            cycles = [
                (d.actual_close_date - d.created_at).days 
                for d in deals 
                if d.actual_close_date
            ]
            return sum(cycles) / len(cycles) if cycles else 0
        
        return {
            "period_days": period_days,
            "won_count": len(won),
            "lost_count": len(lost),
            "win_rate": len(won) / (len(won) + len(lost)) if (won or lost) else 0,
            "avg_won_value": sum(d.value for d in won) / len(won) if won else 0,
            "avg_lost_value": sum(d.value for d in lost) / len(lost) if lost else 0,
            "avg_won_cycle_days": avg_cycle(won),
            "avg_lost_cycle_days": avg_cycle(lost),
            "loss_reasons": dict(loss_reasons),
        }
    
    def export_pipeline(self, filepath: str) -> None:
        """Export pipeline to JSON"""
        data = {
            "deals": [d.to_dict() for d in self.deals.values()],
            "pipelines": [
                {
                    "id": p.id,
                    "name": p.name,
                    "stages": [s.value for s in p.stages],
                }
                for p in self.pipelines.values()
            ],
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported pipeline to {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo SalesPipeline functionality"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "SALES PIPELINE MANAGER DEMO" + " " * 26 + "║")
    print("╚" + "═" * 68 + "╝")
    
    pipeline = SalesPipeline()
    
    # Create sample deals
    print("\n📊 Creating sample deals...")
    
    deals_data = [
        {
            "title": "Roofing Project - Smith Residence",
            "company": "Elite Roofing LLC",
            "contact": "John Smith",
            "value": 15000.00,
            "stage": PipelineStage.PROPOSAL_SENT,
            "priority": DealPriority.HIGH,
            "probability": 70,
            "lead_score": 85,
        },
        {
            "title": "Church Website Redesign",
            "company": "Sacred Heart Church",
            "contact": "Father Michael",
            "value": 8000.00,
            "stage": PipelineStage.QUALIFIED,
            "priority": DealPriority.MEDIUM,
            "probability": 50,
            "lead_score": 70,
        },
        {
            "title": "Lead Gen Platform License",
            "company": "TechStart Solutions",
            "contact": "Sarah Johnson",
            "value": 24000.00,
            "stage": PipelineStage.NEGOTIATION,
            "priority": DealPriority.CRITICAL,
            "probability": 80,
            "lead_score": 95,
        },
        {
            "title": "HVAC Maintenance Contract",
            "company": "Comfort Air Systems",
            "contact": "Mike Davis",
            "value": 5000.00,
            "stage": PipelineStage.WON,
            "priority": DealPriority.MEDIUM,
            "probability": 100,
            "lead_score": 75,
        },
        {
            "title": "Siding Installation",
            "company": "Premium Exteriors",
            "contact": "Lisa Chen",
            "value": 12000.00,
            "stage": PipelineStage.LOST,
            "priority": DealPriority.LOW,
            "probability": 0,
            "lead_score": 60,
            "loss_reason": "Chose competitor (lower price)",
        },
    ]
    
    for data in deals_data:
        deal = pipeline.create_deal(
            title=data["title"],
            company_name=data["company"],
            contact_name=data["contact"],
            value=data["value"],
            stage=data["stage"],
            priority=data["priority"],
            probability=data["probability"],
            lead_score=data["lead_score"],
        )
        
        # Add loss reason if applicable
        if data.get("loss_reason"):
            deal.loss_reason = data["loss_reason"]
            deal.actual_close_date = datetime.now()
        
        print(f"  ✓ {data['title'][:40]}... (${data['value']:,.2f})")
    
    # Show pipeline view
    print(f"\n{'─' * 70}")
    print(f"  PIPELINE VIEW")
    print(f"{'─' * 70}")
    
    view = pipeline.get_pipeline_view()
    for stage, deals in view.items():
        stage_value = sum(d.value for d in deals)
        print(f"\n  {stage.upper().replace('_', ' ')}: {len(deals)} deals, ${stage_value:,.2f}")
        for deal in deals:
            print(f"    • {deal.title[:35]}... (${deal.value:,.2f}, {deal.probability}%)")
    
    # Show forecast
    print(f"\n{'─' * 70}")
    print(f"  SALES FORECAST (30 days)")
    print(f"{'─' * 70}")
    
    forecast = pipeline.get_forecast(days=30)
    print(f"  Weighted Value: ${forecast['weighted_value']:,.2f}")
    print(f"  Unweighted Value: ${forecast['unweighted_value']:,.2f}")
    print(f"  Deals: {forecast['total_deals']}")
    print(f"  By Stage: {forecast['by_stage']}")
    
    # Show performance metrics
    print(f"\n{'─' * 70}")
    print(f"  PERFORMANCE METRICS")
    print(f"{'─' * 70}")
    
    metrics = pipeline.get_performance_metrics(period_days=30)
    print(f"  Deals Won: {metrics['deals_won']}")
    print(f"  Deals Lost: {metrics['deals_lost']}")
    print(f"  Win Rate: {metrics['win_rate_pct']}")
    print(f"  Revenue Won: ${metrics['revenue_won']:,.2f}")
    print(f"  Avg Deal Size: ${metrics['avg_deal_size']:,.2f}")
    
    # Show win/loss analysis
    print(f"\n{'─' * 70}")
    print(f"  WIN/LOSS ANALYSIS")
    print(f"{'─' * 70}")
    
    analysis = pipeline.get_win_loss_analysis(period_days=90)
    print(f"  Won: {analysis['won_count']} | Lost: {analysis['lost_count']}")
    print(f"  Win Rate: {analysis['win_rate']*100:.1f}%")
    print(f"  Avg Won Cycle: {analysis['avg_won_cycle_days']:.0f} days")
    print(f"  Avg Lost Cycle: {analysis['avg_lost_cycle_days']:.0f} days")
    print(f"  Loss Reasons: {analysis['loss_reasons']}")


if __name__ == "__main__":
    asyncio.run(demo())
