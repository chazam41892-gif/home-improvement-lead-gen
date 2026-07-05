#!/usr/bin/env python3
"""
OUTREACH WRITER AGENT
═══════════════════════════════════════════════════════════════════
AI-powered campaign creation and email generation.

Features:
- Personalized email templates
- Multi-channel campaigns (email, SMS, LinkedIn)
- A/B testing support
- Follow-up sequence generation
- Industry-specific messaging
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OutreachWriter")


class Channel(Enum):
    """Communication channels"""
    EMAIL = "email"
    SMS = "sms"
    LINKEDIN = "linkedin"
    PHONE = "phone"
    DIRECT_MAIL = "direct_mail"


class CampaignType(Enum):
    """Campaign types"""
    COLD_OUTREACH = "cold_outreach"
    WARM_FOLLOWUP = "warm_followup"
    REFERRAL = "referral"
    REACTIVATION = "reactivation"
    PRODUCT_LAUNCH = "product_launch"
    EVENT_INVITE = "event_invite"


class IndustrySwarm(Enum):
    """Swarm-specific targeting"""
    CONSTRUCTION_SWARM = "construction_swarm"
    SPIRITUALITY_SWARM = "spirituality_swarm"
    GROWTH_SWARM = "growth_swarm"


@dataclass
class EmailTemplate:
    """Email template structure"""
    id: str
    name: str
    subject: str
    body: str
    swarm: Optional[IndustrySwarm] = None
    industry: Optional[str] = None
    tone: str = "professional"  # professional, casual, formal, friendly
    personalizable_fields: List[str] = field(default_factory=list)
    variables: Dict[str, str] = field(default_factory=dict)
    
    def personalize(self, lead_data: Dict[str, Any]) -> Dict[str, str]:
        """Personalize template with lead data"""
        personalized = {
            "subject": self.subject,
            "body": self.body,
        }
        
        # Replace variables
        for key, value in lead_data.items():
            placeholder = f"{{{key}}}"
            personalized["subject"] = personalized["subject"].replace(placeholder, str(value))
            personalized["body"] = personalized["body"].replace(placeholder, str(value))
        
        return personalized


@dataclass
class Message:
    """Individual message in a sequence"""
    id: str
    sequence_order: int
    channel: Channel
    subject: Optional[str] = None
    body: str = ""
    delay_days: int = 0  # Days after previous message
    delay_hours: int = 0  # Additional hours
    send_time: Optional[str] = None  # Preferred time (e.g., "9:00 AM")
    condition: Optional[str] = None  # Condition to send (e.g., "if_no_reply")
    
    def get_full_delay_hours(self) -> int:
        """Get total delay in hours"""
        return (self.delay_days * 24) + self.delay_hours


@dataclass
class Campaign:
    """Complete campaign structure"""
    id: str
    name: str
    campaign_type: CampaignType
    swarm: Optional[IndustrySwarm] = None
    target_industry: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "draft"  # draft, active, paused, completed
    
    # Targeting
    target_lead_count: int = 100
    criteria: Dict[str, Any] = field(default_factory=dict)
    
    # Messages
    messages: List[Message] = field(default_factory=list)
    
    # Performance
    sent_count: int = 0
    open_count: int = 0
    click_count: int = 0
    reply_count: int = 0
    conversion_count: int = 0
    
    # Settings
    sender_name: str = ""
    sender_email: str = ""
    reply_to: Optional[str] = None
    track_opens: bool = True
    track_clicks: bool = True
    
    def get_open_rate(self) -> float:
        """Calculate open rate"""
        if self.sent_count == 0:
            return 0.0
        return self.open_count / self.sent_count
    
    def get_reply_rate(self) -> float:
        """Calculate reply rate"""
        if self.sent_count == 0:
            return 0.0
        return self.reply_count / self.sent_count
    
    def get_conversion_rate(self) -> float:
        """Calculate conversion rate"""
        if self.sent_count == 0:
            return 0.0
        return self.conversion_count / self.sent_count


class OutreachWriter:
    """
    AI Outreach Writer Agent
    Creates personalized campaigns and messaging
    """
    
    # Industry-specific pain points
    PAIN_POINTS = {
        "construction": [
            "High customer acquisition cost",
            "Unpredictable project pipeline",
            "Worker retention challenges",
            "Seasonal demand fluctuations",
            "Insurance compliance burden",
        ],
        "roofing": [
            "Competition from storm chasers",
            "Inconsistent lead flow",
            "Long sales cycles",
            "Weather dependency",
        ],
        "plumbing": [
            "Emergency call scheduling",
            "Customer retention",
            "Pricing competition",
        ],
        "church": [
            "Declining attendance",
            "Reaching younger demographics",
            "Digital presence gaps",
            "Fundraising challenges",
        ],
        "synagogue": [
            "Community engagement",
            "Member retention",
            "Event participation",
        ],
        "wellness": [
            "Client acquisition",
            "Competition from chains",
            "Seasonal fluctuations",
        ],
        "tech_startup": [
            "Inconsistent sales pipeline",
            "High customer acquisition cost",
            "Sales team prospecting time",
        ],
        "b2b_services": [
            "Lead quality issues",
            "Long sales cycles",
            "Competitive differentiation",
        ],
    }
    
    # Value propositions by industry
    VALUE_PROPS = {
        "construction": "fill your project pipeline with pre-qualified leads that match your exact specialty and capacity",
        "roofing": "connect you with homeowners actively seeking roof repairs and replacements in your service area",
        "church": "expand your congregation by 30-50% using targeted outreach to families seeking spiritual community",
        "tech_startup": "automate your lead pipeline so your team focuses on closing, not prospecting",
    }
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.campaigns: List[Campaign] = []
        self.templates: Dict[str, EmailTemplate] = {}
        self._load_templates()
        logger.info("OutreachWriter initialized")
    
    def _load_templates(self) -> None:
        """Load default email templates"""
        
        # Construction Cold Email
        self.templates["construction_cold"] = EmailTemplate(
            id="construction_cold",
            name="Construction Cold Outreach",
            swarm=IndustrySwarm.CONSTRUCTION_SWARM,
            subject="{city}-based {industry} — {business_name}",
            body="""Hi {contact_first_name},

I came across {business_name} and was impressed by your work on recent projects in {city}.

We specialize in connecting {industry} contractors in {region} with pre-qualified project leads that match your capacity and expertise.

Most contractors we work with see a 40% increase in qualified opportunities within the first 60 days.

Would a quick 15-minute call this week be worthwhile to explore if this could work for {business_name}?

Best,
{sender_name}
{sender_title}

P.S. — I noticed you specialize in {specialty}. We have 12 active homeowners in {city} looking for exactly that expertise.""",
            personalizable_fields=["contact_first_name", "business_name", "city", "industry", "region", "specialty"],
            variables={"sender_name": "", "sender_title": ""}
        )
        
        # Church/Spirituality Email
        self.templates["spirituality_outreach"] = EmailTemplate(
            id="spirituality_outreach",
            name="Spirituality Community Growth",
            swarm=IndustrySwarm.SPIRITUALITY_SWARM,
            subject="Growing {business_name}'s community reach",
            body="""Hi {contact_first_name},

I found {business_name} while researching faith communities in {city} that are making a positive impact.

We help organizations like yours expand community engagement by 30-50% using targeted digital outreach to families and individuals actively searching for spiritual connection and community.

Our approach is respectful, non-intrusive, and has helped over 200 congregations grow their active membership.

Worth a 10-minute conversation to see if this aligns with {business_name}'s vision?

Peace,
{sender_name}

P.S. — No obligation. Just exploring if we can support your mission.""",
            personalizable_fields=["contact_first_name", "business_name", "city"],
        )
        
        # B2B/Growth Email
        self.templates["growth_outreach"] = EmailTemplate(
            id="growth_outreach",
            name="B2B Growth Outreach",
            swarm=IndustrySwarm.GROWTH_SWARM,
            subject="Automated lead pipeline for {business_name}",
            body="""Hi {contact_first_name},

I noticed {business_name} is scaling in the {industry} space — exciting growth phase.

Most growing teams at your stage waste 40% of their sales team's time on prospecting instead of closing.

We build automated lead pipelines that deliver qualified prospects directly to your closers, pre-screened and ready to talk.

Result: 2-3x more qualified meetings per rep per week.

Open to a quick 15-minute demo? I'll share how {similar_company} achieved {result} in 90 days.

Best,
{sender_name}
{sender_title}

→ Book a time: {calendar_link}

Unsubscribe: {unsubscribe_link}""",
            personalizable_fields=["contact_first_name", "business_name", "industry", "similar_company", "result"],
        )
        
        # Follow-up #1
        self.templates["followup_1"] = EmailTemplate(
            id="followup_1",
            name="Follow-up Day 3",
            subject="Re: {original_subject}",
            body="""Hi {contact_first_name},

Quick follow-up on my note from a few days ago about {topic}.

I understand you're busy. Just wanted to make sure this didn't get buried.

If {value_prop} is something you're exploring this quarter, happy to share how similar {industry} companies are achieving {specific_result}.

If not, no worries — I'll close the loop on my end.

{sender_name}""",
            personalizable_fields=["contact_first_name", "original_subject", "topic", "value_prop", "industry", "specific_result"],
        )
        
        # Follow-up #2 (Value-add)
        self.templates["followup_2_value"] = EmailTemplate(
            id="followup_2_value",
            name="Value-add Follow-up",
            subject="A resource for {business_name}",
            body="""Hi {contact_first_name},

I put together a quick case study on how {similar_company} increased their {metric} by {percentage}% using {strategy}.

Thought it might be relevant given {business_name}'s focus on {focus_area}.

[Download Case Study: {link}]

No pitch — just thought you'd find it useful.

If you want to discuss how this might apply to {business_name}, I'm around.

{sender_name}""",
            personalizable_fields=["contact_first_name", "business_name", "similar_company", "metric", "percentage", "strategy", "focus_area"],
        )
        
        # Break-up Email
        self.templates["breakup"] = EmailTemplate(
            id="breakup",
            name="Final Attempt",
            subject="Should I close the loop?",
            body="""Hi {contact_first_name},

I've reached out a few times about {topic} but haven't heard back.

Totally understand — priorities shift, timing isn't right, or this simply isn't a fit.

Should I close the loop on my end, or is there still interest in exploring {value_prop}?

Either way, wishing {business_name} continued success.

{sender_name}

P.S. — If timing was the issue, feel free to bookmark this: {resource_link}""",
            personalizable_fields=["contact_first_name", "topic", "value_prop", "business_name"],
        )
    
    def create_campaign(self, 
                       name: str,
                       campaign_type: CampaignType,
                       target_industry: str,
                       swarm: Optional[IndustrySwarm] = None,
                       target_lead_count: int = 100) -> Campaign:
        """
        Create a new campaign
        
        Args:
            name: Campaign name
            campaign_type: Type of campaign
            target_industry: Target industry
            swarm: Swarm specialization (optional)
            target_lead_count: Number of leads to target
            
        Returns:
            Campaign object
        """
        campaign = Campaign(
            id=f"camp_{datetime.now().timestamp()}",
            name=name,
            campaign_type=campaign_type,
            swarm=swarm,
            target_industry=target_industry,
            target_lead_count=target_lead_count,
        )
        
        # Auto-generate message sequence
        campaign.messages = self._generate_sequence(campaign)
        
        self.campaigns.append(campaign)
        logger.info(f"Created campaign: {name} ({len(campaign.messages)} messages)")
        
        return campaign
    
    def _generate_sequence(self, campaign: Campaign) -> List[Message]:
        """Generate message sequence based on campaign type"""
        messages = []
        
        # Get appropriate template
        template_key = self._get_template_for_campaign(campaign)
        template = self.templates.get(template_key)
        
        if not template:
            template = self.templates.get("construction_cold")  # Default
        
        # Message 1: Initial outreach
        msg1 = Message(
            id=f"msg_{campaign.id}_1",
            sequence_order=1,
            channel=Channel.EMAIL,
            subject=template.subject,
            body=template.body,
            delay_days=0,
            delay_hours=0,
            send_time="9:00 AM",
        )
        messages.append(msg1)
        
        # Message 2: Follow-up (Day 3)
        followup_template = self.templates.get("followup_1")
        msg2 = Message(
            id=f"msg_{campaign.id}_2",
            sequence_order=2,
            channel=Channel.EMAIL,
            subject=followup_template.subject if followup_template else "Quick follow-up",
            body=followup_template.body if followup_template else "Following up...",
            delay_days=3,
            delay_hours=0,
            send_time="10:00 AM",
            condition="if_no_reply",
        )
        messages.append(msg2)
        
        # Message 3: Value-add (Day 7)
        value_template = self.templates.get("followup_2_value")
        msg3 = Message(
            id=f"msg_{campaign.id}_3",
            sequence_order=3,
            channel=Channel.EMAIL,
            subject=value_template.subject if value_template else "A resource for you",
            body=value_template.body if value_template else "Sharing a resource...",
            delay_days=4,  # 4 days after previous (Day 7 total)
            delay_hours=0,
            send_time="2:00 PM",
            condition="if_no_reply",
        )
        messages.append(msg3)
        
        # Message 4: LinkedIn connection (Day 10)
        msg4 = Message(
            id=f"msg_{campaign.id}_4",
            sequence_order=4,
            channel=Channel.LINKEDIN,
            body=f"Hi {{contact_first_name}}, I've been trying to reach you about {campaign.target_industry} opportunities. Worth connecting?",
            delay_days=3,
            delay_hours=0,
            condition="if_no_reply",
        )
        messages.append(msg4)
        
        # Message 5: Final attempt (Day 14)
        breakup_template = self.templates.get("breakup")
        msg5 = Message(
            id=f"msg_{campaign.id}_5",
            sequence_order=5,
            channel=Channel.EMAIL,
            subject=breakup_template.subject if breakup_template else "Should I close the loop?",
            body=breakup_template.body if breakup_template else "One last attempt...",
            delay_days=4,
            delay_hours=0,
            send_time="9:00 AM",
            condition="if_no_reply",
        )
        messages.append(msg5)
        
        return messages
    
    def _get_template_for_campaign(self, campaign: Campaign) -> str:
        """Get appropriate template for campaign"""
        industry = campaign.target_industry.lower()
        
        if "construct" in industry or "roof" in industry or "plumb" in industry:
            return "construction_cold"
        elif "church" in industry or "synagogue" in industry or "spirit" in industry:
            return "spirituality_outreach"
        elif "tech" in industry or "b2b" in industry:
            return "growth_outreach"
        
        # Check swarm
        if campaign.swarm == IndustrySwarm.CONSTRUCTION_SWARM:
            return "construction_cold"
        elif campaign.swarm == IndustrySwarm.SPIRITUALITY_SWARM:
            return "spirituality_outreach"
        elif campaign.swarm == IndustrySwarm.GROWTH_SWARM:
            return "growth_outreach"
        
        return "construction_cold"  # Default
    
    def personalize_message(self, 
                          message: Message, 
                          lead_data: Dict[str, Any],
                          sender_info: Dict[str, str]) -> str:
        """
        Personalize a message with lead data
        
        Args:
            message: Message template
            lead_data: Lead information
            sender_info: Sender details (name, title, etc.)
            
        Returns:
            Personalized message body
        """
        body = message.body
        
        # Replace lead data placeholders
        for key, value in lead_data.items():
            placeholder = f"{{{key}}}"
            body = body.replace(placeholder, str(value))
        
        # Replace sender info
        for key, value in sender_info.items():
            placeholder = f"{{{key}}}"
            body = body.replace(placeholder, str(value))
        
        # Replace common placeholders with defaults
        defaults = {
            "{specialty}": lead_data.get("industry", "contracting"),
            "{region}": f"{lead_data.get('city', 'your area')}, {lead_data.get('state', '')}",
            "{sender_title}": sender_info.get("sender_title", "Business Development"),
            "{similar_company}": "a similar company",
            "{result}": "40% growth in qualified leads",
            "{calendar_link}": sender_info.get("calendar_link", "[calendar]"),
            "{unsubscribe_link}": "[unsubscribe]",
            "{topic}": "growing your business",
            "{value_prop}": "increasing your lead flow",
            "{specific_result}": "significant growth",
            "{metric}": "lead generation",
            "{percentage}": "40",
            "{strategy}": "targeted outreach",
            "{focus_area}": "growth",
            "{link}": "[link]",
            "{resource_link}": "[resource]",
        }
        
        for placeholder, default_value in defaults.items():
            body = body.replace(placeholder, default_value)
        
        return body
    
    def generate_subject_line(self, 
                             lead_data: Dict[str, Any],
                             template: Optional[EmailTemplate] = None) -> str:
        """Generate personalized subject line"""
        if template:
            subject = template.subject
        else:
            subject = "Quick question about {business_name}"
        
        # Replace placeholders
        for key, value in lead_data.items():
            placeholder = f"{{{key}}}"
            subject = subject.replace(placeholder, str(value))
        
        return subject
    
    def get_pain_points(self, industry: str) -> List[str]:
        """Get industry-specific pain points"""
        return self.PAIN_POINTS.get(industry.lower(), ["Growing your business"])
    
    def get_value_prop(self, industry: str) -> str:
        """Get industry-specific value proposition"""
        return self.VALUE_PROPS.get(industry.lower(), "help you grow your business")
    
    def create_ab_test(self, 
                      campaign: Campaign,
                      variations: List[Dict[str, str]]) -> List[Campaign]:
        """
        Create A/B test variations of a campaign
        
        Args:
            campaign: Base campaign
            variations: List of variation configs
            
        Returns:
            List of campaign variations
        """
        campaigns = []
        
        for i, variation in enumerate(variations):
            variant = Campaign(
                id=f"{campaign.id}_v{i+1}",
                name=f"{campaign.name} (Variant {i+1})",
                campaign_type=campaign.campaign_type,
                target_industry=campaign.target_industry,
                target_lead_count=campaign.target_lead_count // len(variations),
            )
            
            # Modify first message with variation
            if variant.messages:
                variant.messages[0].subject = variation.get("subject", variant.messages[0].subject)
                variant.messages[0].body = variation.get("body", variant.messages[0].body)
            
            campaigns.append(variant)
        
        return campaigns
    
    def get_campaign_stats(self, campaign_id: Optional[str] = None) -> Dict[str, Any]:
        """Get campaign statistics"""
        if campaign_id:
            campaign = next((c for c in self.campaigns if c.id == campaign_id), None)
            if campaign:
                return {
                    "id": campaign.id,
                    "name": campaign.name,
                    "status": campaign.status,
                    "sent": campaign.sent_count,
                    "opens": campaign.open_count,
                    "clicks": campaign.click_count,
                    "replies": campaign.reply_count,
                    "conversions": campaign.conversion_count,
                    "open_rate": f"{campaign.get_open_rate()*100:.1f}%",
                    "reply_rate": f"{campaign.get_reply_rate()*100:.1f}%",
                    "conversion_rate": f"{campaign.get_conversion_rate()*100:.1f}%",
                }
            return {}
        
        # All campaigns
        return {
            "total_campaigns": len(self.campaigns),
            "active": len([c for c in self.campaigns if c.status == "active"]),
            "drafts": len([c for c in self.campaigns if c.status == "draft"]),
            "completed": len([c for c in self.campaigns if c.status == "completed"]),
            "total_sent": sum(c.sent_count for c in self.campaigns),
            "total_opens": sum(c.open_count for c in self.campaigns),
            "total_replies": sum(c.reply_count for c in self.campaigns),
        }
    
    def export_campaign(self, campaign: Campaign, filepath: str) -> None:
        """Export campaign to JSON"""
        data = {
            "id": campaign.id,
            "name": campaign.name,
            "type": campaign.campaign_type.value,
            "industry": campaign.target_industry,
            "status": campaign.status,
            "messages": [
                {
                    "order": m.sequence_order,
                    "channel": m.channel.value,
                    "subject": m.subject,
                    "body": m.body,
                    "delay_days": m.delay_days,
                    "condition": m.condition,
                }
                for m in campaign.messages
            ],
            "stats": {
                "sent": campaign.sent_count,
                "opens": campaign.open_count,
                "replies": campaign.reply_count,
            }
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Exported campaign to {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo OutreachWriter functionality"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "OUTREACH WRITER AGENT DEMO" + " " * 27 + "║")
    print("╚" + "═" * 68 + "╝")
    
    writer = OutreachWriter()
    
    # Create campaign
    print("\n📧 Creating campaign...")
    campaign = writer.create_campaign(
        name="Eugene Contractors Q1",
        campaign_type=CampaignType.COLD_OUTREACH,
        target_industry="construction",
        swarm=IndustrySwarm.CONSTRUCTION_SWARM,
        target_lead_count=100
    )
    
    print(f"  Campaign: {campaign.name}")
    print(f"  Messages: {len(campaign.messages)}")
    print(f"  Industry: {campaign.target_industry}")
    
    # Show sequence
    print(f"\n{'─' * 70}")
    print(f"  MESSAGE SEQUENCE")
    print(f"{'─' * 70}\n")
    
    for msg in campaign.messages:
        print(f"  [{msg.sequence_order}] {msg.channel.value.upper()}")
        if msg.subject:
            print(f"      Subject: {msg.subject[:50]}...")
        print(f"      Delay: +{msg.delay_days} days, {msg.delay_hours} hours")
        print(f"      Condition: {msg.condition or 'None'}")
        print()
    
    # Personalize first message
    print(f"{'─' * 70}")
    print(f"  PERSONALIZED MESSAGE EXAMPLE")
    print(f"{'─' * 70}\n")
    
    lead_data = {
        "contact_first_name": "John",
        "business_name": "Elite Roofing LLC",
        "city": "Eugene",
        "state": "OR",
        "industry": "roofing",
        "region": "Lane County",
        "specialty": "residential roofing",
    }
    
    sender_info = {
        "sender_name": "Sarah",
        "sender_title": "Business Development",
    }
    
    personalized = writer.personalize_message(
        campaign.messages[0],
        lead_data,
        sender_info
    )
    
    print(f"  To: {lead_data['contact_first_name']} @ {lead_data['business_name']}")
    print(f"  Subject: {writer.generate_subject_line(lead_data)}")
    print()
    print("  " + "─" * 66)
    for line in personalized.split('\n'):
        print(f"  {line}")
    print("  " + "─" * 66)
    
    # Show stats
    print(f"\n{'─' * 70}")
    print(f"  CAMPAIGN STATISTICS")
    print(f"{'─' * 70}")
    stats = writer.get_campaign_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(demo())
