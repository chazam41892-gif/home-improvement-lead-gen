#!/usr/bin/env python3
"""
FOLLOW-UP AUTOMATOR
═══════════════════════════════════════════════════════════════════
Automated follow-up sequences for lead nurturing.

Features:
- Multi-channel sequences (email, SMS, call, LinkedIn)
- Conditional logic based on engagement
- A/B testing
- Timing optimization
- Response detection
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FollowUpAutomator")


class Channel(Enum):
    """Communication channels"""
    EMAIL = "email"
    SMS = "sms"
    PHONE = "phone"
    LINKEDIN = "linkedin"
    DIRECT_MAIL = "direct_mail"
    TASK = "task"  # For internal reminders


class TriggerCondition(Enum):
    """Conditions that can trigger a follow-up"""
    NO_REPLY = "no_reply"
    EMAIL_OPENED = "email_opened"
    LINK_CLICKED = "link_clicked"
    PHONE_CALL_MADE = "phone_call_made"
    MEETING_BOOKED = "meeting_booked"
    STAGE_CHANGED = "stage_changed"
    TIME_BASED = "time_based"
    MANUAL = "manual"


class SequenceStatus(Enum):
    """Status of a follow-up sequence"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class FollowUpMessage:
    """Individual message in follow-up sequence"""
    id: str
    sequence_order: int
    channel: Channel
    subject: Optional[str] = None
    body: str = ""
    
    # Timing
    delay_days: int = 0
    delay_hours: int = 0
    send_time: str = "9:00 AM"  # Preferred send time
    
    # Conditions
    trigger_condition: Optional[TriggerCondition] = None
    condition_value: Optional[str] = None  # Additional condition details
    
    # Personalization
    variables: Dict[str, str] = field(default_factory=dict)
    
    # Tracking
    sent: bool = False
    sent_at: Optional[datetime] = None
    delivered: bool = False
    opened: bool = False
    clicked: bool = False
    replied: bool = False
    
    # A/B testing
    variant: str = "A"  # A or B for testing
    
    def get_send_time(self, start_time: datetime) -> datetime:
        """Calculate send time based on start time"""
        send_time = start_time + timedelta(days=self.delay_days, hours=self.delay_hours)
        
        # Parse preferred time
        try:
            time_parts = self.send_time.replace(" ", "").upper()
            if "AM" in time_parts or "PM" in time_parts:
                # Handle AM/PM
                hour = int(self.send_time.split(":")[0])
                minute = int(self.send_time.split(":")[1].split()[0])
                ampm = self.send_time.split()[-1].upper()
                
                if ampm == "PM" and hour != 12:
                    hour += 12
                elif ampm == "AM" and hour == 12:
                    hour = 0
            else:
                hour = int(self.send_time.split(":")[0])
                minute = int(self.send_time.split(":")[1])
            
            send_time = send_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except:
            pass
        
        return send_time
    
    def should_send(self, lead_state: Dict[str, Any]) -> bool:
        """Check if message should be sent based on conditions"""
        if self.sent:
            return False
        
        if self.trigger_condition == TriggerCondition.NO_REPLY:
            return not lead_state.get("replied", False)
        
        if self.trigger_condition == TriggerCondition.EMAIL_OPENED:
            return lead_state.get("email_opened", False)
        
        if self.trigger_condition == TriggerCondition.LINK_CLICKED:
            return lead_state.get("link_clicked", False)
        
        if self.trigger_condition == TriggerCondition.TIME_BASED:
            return True
        
        return True  # Default: send if no condition


@dataclass
class FollowUpSequence:
    """Complete follow-up sequence"""
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    status: SequenceStatus = SequenceStatus.ACTIVE
    
    # Targeting
    target_swarm: Optional[str] = None  # construction, spirituality, growth
    target_industry: Optional[str] = None
    
    # Messages
    messages: List[FollowUpMessage] = field(default_factory=list)
    
    # Settings
    exit_on_reply: bool = True
    exit_on_meeting: bool = True
    exit_on_negative: bool = True
    max_messages: int = 10
    
    # Timing
    timezone: str = "America/Los_Angeles"
    skip_weekends: bool = True
    skip_holidays: bool = True
    business_hours_only: bool = True
    
    # Stats
    total_enrolled: int = 0
    total_completed: int = 0
    total_exited: int = 0
    avg_sequence_time_days: float = 0.0
    
    def get_next_message(self, 
                        lead_state: Dict[str, Any],
                        current_message_order: int = 0) -> Optional[FollowUpMessage]:
        """Get next message that should be sent"""
        for msg in self.messages:
            if msg.sequence_order > current_message_order:
                if msg.should_send(lead_state):
                    return msg
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "message_count": len(self.messages),
            "total_enrolled": self.total_enrolled,
            "exit_on_reply": self.exit_on_reply,
            "exit_on_meeting": self.exit_on_meeting,
        }


@dataclass
class LeadSequenceState:
    """Tracks a lead's progress through a sequence"""
    lead_id: str
    sequence_id: str
    enrolled_at: datetime
    
    current_message_order: int = 0
    messages_sent: int = 0
    messages_delivered: int = 0
    messages_opened: int = 0
    messages_clicked: int = 0
    
    status: str = "active"  # active, paused, completed, exited
    exit_reason: Optional[str] = None
    exit_at: Optional[datetime] = None
    
    next_scheduled_time: Optional[datetime] = None
    
    # Engagement tracking
    total_opens: int = 0
    total_clicks: int = 0
    total_replies: int = 0
    last_activity: Optional[datetime] = None


class SequenceLibrary:
    """Library of pre-built follow-up sequences"""
    
    @staticmethod
    def get_construction_sequence() -> FollowUpSequence:
        """Standard sequence for construction/industry leads"""
        seq = FollowUpSequence(
            id="seq_construction_standard",
            name="Construction Standard Follow-Up",
            description="5-touch email sequence for construction industry leads",
            target_swarm="construction",
        )
        
        # Day 0: Initial email
        msg1 = FollowUpMessage(
            id="msg_1",
            sequence_order=1,
            channel=Channel.EMAIL,
            subject="{city}-based {industry} — {business_name}",
            body="""Hi {first_name},

I came across {business_name} and was impressed by your work in {city}.

We specialize in connecting {industry} contractors with pre-qualified project leads that match your exact specialty and capacity.

Most contractors we work with see a 40% increase in qualified opportunities within 60 days.

Would a quick 15-minute call this week be worthwhile?

Best,
{sender_name}""",
            delay_days=0,
            send_time="9:00 AM",
            trigger_condition=TriggerCondition.TIME_BASED,
        )
        
        # Day 3: Follow-up
        msg2 = FollowUpMessage(
            id="msg_2",
            sequence_order=2,
            channel=Channel.EMAIL,
            subject="Re: {city}-based {industry} — {business_name}",
            body="""Hi {first_name},

Quick follow-up on my note from a few days ago.

I understand you're busy. Just wanted to make sure this didn't get buried.

If filling your project pipeline with qualified leads is something you're exploring this quarter, happy to share how similar {industry} companies are achieving significant growth.

If not, no worries — I'll close the loop on my end.

{sender_name}""",
            delay_days=3,
            send_time="10:00 AM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        # Day 7: Value-add
        msg3 = FollowUpMessage(
            id="msg_3",
            sequence_order=3,
            channel=Channel.EMAIL,
            subject="A case study for {business_name}",
            body="""Hi {first_name},

I put together a quick case study on how a {city} {industry} company increased their project pipeline by 45% using targeted lead generation.

Thought it might be relevant given {business_name}'s focus on growth.

[Read Case Study]

No pitch — just thought you'd find it useful.

If you want to discuss how this might apply to {business_name}, I'm around.

{sender_name}""",
            delay_days=4,  # 4 days after previous (Day 7 total)
            send_time="2:00 PM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        # Day 10: LinkedIn
        msg4 = FollowUpMessage(
            id="msg_4",
            sequence_order=4,
            channel=Channel.LINKEDIN,
            subject=None,
            body="""Hi {first_name}, I've been trying to connect regarding project lead opportunities for {business_name} in {city}. Worth a brief conversation?""",
            delay_days=3,
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        # Day 14: Final attempt
        msg5 = FollowUpMessage(
            id="msg_5",
            sequence_order=5,
            channel=Channel.EMAIL,
            subject="Should I close the loop?",
            body="""Hi {first_name},

I've reached out a few times about project lead opportunities for {business_name} but haven't heard back.

Totally understand — priorities shift, timing isn't right, or this simply isn't a fit.

Should I close the loop on my end, or is there still interest in exploring how we can help fill your pipeline?

Either way, wishing {business_name} continued success.

{sender_name}

P.S. — If timing was the issue, feel free to bookmark this: [resource link]""",
            delay_days=4,
            send_time="9:00 AM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        seq.messages = [msg1, msg2, msg3, msg4, msg5]
        return seq
    
    @staticmethod
    def get_spirituality_sequence() -> FollowUpSequence:
        """Sequence for spirituality/community organizations"""
        seq = FollowUpSequence(
            id="seq_spirituality_standard",
            name="Spirituality/Community Follow-Up",
            description="Gentle outreach sequence for churches and community orgs",
            target_swarm="spirituality",
        )
        
        # Day 0: Initial
        msg1 = FollowUpMessage(
            id="msg_1",
            sequence_order=1,
            channel=Channel.EMAIL,
            subject="Growing {business_name}'s community reach",
            body="""Hi {first_name},

I found {business_name} while researching faith communities in {city} that are making a positive impact.

We help organizations like yours expand community engagement by 30-50% using targeted digital outreach to families actively searching for spiritual connection.

Our approach is respectful, non-intrusive, and has helped over 200 congregations grow.

Worth a 10-minute conversation to see if this aligns with {business_name}'s vision?

Peace,
{sender_name}""",
            delay_days=0,
            send_time="9:00 AM",
        )
        
        # Day 5: Follow-up (longer interval for this audience)
        msg2 = FollowUpMessage(
            id="msg_2",
            sequence_order=2,
            channel=Channel.EMAIL,
            subject="Re: Growing {business_name}'s community reach",
            body="""Hi {first_name},

Following up on my previous note about expanding {business_name}'s reach in {city}.

I understand decisions like this often require input from multiple people and careful consideration.

Happy to provide references from other faith communities we've worked with, or simply send you some information to review when convenient.

No pressure — just here if you'd like to explore further.

Peace,
{sender_name}""",
            delay_days=5,
            send_time="10:00 AM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        # Day 12: Value-add
        msg3 = FollowUpMessage(
            id="msg_3",
            sequence_order=3,
            channel=Channel.EMAIL,
            subject="Resources for community growth",
            body="""Hi {first_name},

I wanted to share a free resource we've put together: "10 Digital Outreach Strategies for Faith Communities" — no pitch, just practical tips.

[Download Guide]

If you find it useful and want to discuss how we might support {business_name}'s growth goals, I'm available.

Otherwise, I hope the resource serves you well.

Peace and blessings,
{sender_name}""",
            delay_days=7,
            send_time="2:00 PM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        seq.messages = [msg1, msg2, msg3]
        return seq
    
    @staticmethod
    def get_growth_sequence() -> FollowUpSequence:
        """Sequence for B2B/growth companies"""
        seq = FollowUpSequence(
            id="seq_growth_standard",
            name="B2B Growth Follow-Up",
            description="High-touch sequence for B2B/growth leads",
            target_swarm="growth",
        )
        
        # Day 0: Initial
        msg1 = FollowUpMessage(
            id="msg_1",
            sequence_order=1,
            channel=Channel.EMAIL,
            subject="Automated lead pipeline for {business_name}",
            body="""Hi {first_name},

I noticed {business_name} is scaling in the {industry} space — exciting growth phase.

Most growing teams at your stage waste 40% of their sales team's time on prospecting instead of closing.

We build automated lead pipelines that deliver qualified prospects directly to your closers.

Result: 2-3x more qualified meetings per rep per week.

Open to a quick 15-minute demo? I'll share how {similar_company} achieved 40% growth in qualified leads in 90 days.

Best,
{sender_name}

→ Book a time: {calendar_link}""",
            delay_days=0,
            send_time="9:00 AM",
        )
        
        # Day 2: Faster follow-up for B2B
        msg2 = FollowUpMessage(
            id="msg_2",
            sequence_order=2,
            channel=Channel.EMAIL,
            subject="Quick question, {first_name}",
            body="""Hi {first_name},

Did you get my note yesterday about automated lead pipelines for {business_name}?

Quick question: What's your team's biggest bottleneck right now — lead volume or lead quality?

If it's either (or both), I have a few ideas worth 5 minutes of your time.

{sender_name}""",
            delay_days=2,
            send_time="10:00 AM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        # Day 4: LinkedIn
        msg3 = FollowUpMessage(
            id="msg_3",
            sequence_order=3,
            channel=Channel.LINKEDIN,
            body="""Hi {first_name}, I sent you an email about automated lead pipelines for {business_name}. Worth a brief conversation?""",
            delay_days=2,
        )
        
        # Day 7: Case study
        msg4 = FollowUpMessage(
            id="msg_4",
            sequence_order=4,
            channel=Channel.EMAIL,
            subject="How {similar_company} increased leads 40%",
            body="""Hi {first_name},

I put together a case study on how {similar_company} solved their lead pipeline challenges.

Key results:
• 40% increase in qualified leads
• 60% reduction in prospecting time
• 25% faster sales cycle

[Read Case Study]

If you see parallels with {business_name}'s situation, happy to discuss how we achieved this.

{sender_name}""",
            delay_days=3,
            send_time="2:00 PM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        # Day 10: Final
        msg5 = FollowUpMessage(
            id="msg_5",
            sequence_order=5,
            channel=Channel.EMAIL,
            subject="Should I close the loop?",
            body="""Hi {first_name},

I've reached out a few times about lead pipeline automation for {business_name} but haven't heard back.

Totally get it — you're busy, this isn't a priority, or it's just not a fit.

Should I close the loop on my end?

{sender_name}""",
            delay_days=3,
            send_time="9:00 AM",
            trigger_condition=TriggerCondition.NO_REPLY,
        )
        
        seq.messages = [msg1, msg2, msg3, msg4, msg5]
        return seq


class FollowUpAutomator:
    """
    Follow-Up Automator
    Manages automated follow-up sequences for lead nurturing
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.sequences: Dict[str, FollowUpSequence] = {}
        self.lead_states: Dict[str, LeadSequenceState] = {}
        
        # Load default sequences
        self._load_default_sequences()
        
        # Callbacks for sending messages
        self.email_sender: Optional[Callable] = None
        self.sms_sender: Optional[Callable] = None
        self.task_creator: Optional[Callable] = None
        
        logger.info("FollowUpAutomator initialized")
    
    def _load_default_sequences(self) -> None:
        """Load default sequences from library"""
        library = SequenceLibrary()
        
        construction = library.get_construction_sequence()
        self.sequences[construction.id] = construction
        
        spirituality = library.get_spirituality_sequence()
        self.sequences[spirituality.id] = spirituality
        
        growth = library.get_growth_sequence()
        self.sequences[growth.id] = growth
        
        logger.info(f"Loaded {len(self.sequences)} default sequences")
    
    def register_sequence(self, sequence: FollowUpSequence) -> None:
        """Register a custom sequence"""
        self.sequences[sequence.id] = sequence
        logger.info(f"Registered sequence: {sequence.name}")
    
    def enroll_lead(self, 
                   lead_id: str,
                   sequence_id: str,
                   start_time: Optional[datetime] = None) -> Optional[LeadSequenceState]:
        """
        Enroll a lead in a follow-up sequence
        
        Args:
            lead_id: Lead identifier
            sequence_id: Sequence to enroll in
            start_time: When to start (None = now)
            
        Returns:
            LeadSequenceState if enrolled successfully
        """
        sequence = self.sequences.get(sequence_id)
        if not sequence:
            logger.error(f"Sequence not found: {sequence_id}")
            return None
        
        if sequence.status != SequenceStatus.ACTIVE:
            logger.error(f"Sequence {sequence_id} is not active")
            return None
        
        start_time = start_time or datetime.now()
        
        state = LeadSequenceState(
            lead_id=lead_id,
            sequence_id=sequence_id,
            enrolled_at=start_time,
            next_scheduled_time=start_time,
        )
        
        self.lead_states[lead_id] = state
        sequence.total_enrolled += 1
        
        logger.info(f"Enrolled lead {lead_id} in sequence {sequence.name}")
        return state
    
    def get_next_actions(self, current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Get list of follow-up actions that should be taken now
        
        Args:
            current_time: Current time (None = now)
            
        Returns:
            List of actions to take
        """
        current_time = current_time or datetime.now()
        actions = []
        
        for lead_id, state in self.lead_states.items():
            if state.status != "active":
                continue
            
            sequence = self.sequences.get(state.sequence_id)
            if not sequence:
                continue
            
            # Check if it's time for next message
            if state.next_scheduled_time and state.next_scheduled_time <= current_time:
                lead_state = self._build_lead_state(state)
                next_msg = sequence.get_next_message(lead_state, state.current_message_order)
                
                if next_msg:
                    actions.append({
                        "lead_id": lead_id,
                        "sequence_id": state.sequence_id,
                        "message": next_msg,
                        "scheduled_time": state.next_scheduled_time,
                    })
        
        return actions
    
    def _build_lead_state(self, state: LeadSequenceState) -> Dict[str, Any]:
        """Build current lead state for condition checking"""
        return {
            "replied": state.total_replies > 0,
            "email_opened": state.total_opens > 0,
            "link_clicked": state.total_clicks > 0,
            "messages_sent": state.messages_sent,
            "days_in_sequence": (datetime.now() - state.enrolled_at).days,
        }
    
    async def process_action(self, action: Dict[str, Any]) -> bool:
        """
        Process a follow-up action
        
        Args:
            action: Action to process
            
        Returns:
            True if successful
        """
        lead_id = action["lead_id"]
        message = action["message"]
        
        state = self.lead_states.get(lead_id)
        if not state:
            return False
        
        sequence = self.sequences.get(state.sequence_id)
        if not sequence:
            return False
        
        # Send based on channel
        try:
            if message.channel == Channel.EMAIL and self.email_sender:
                await self.email_sender(lead_id, message)
            elif message.channel == Channel.SMS and self.sms_sender:
                await self.sms_sender(lead_id, message)
            elif message.channel == Channel.TASK and self.task_creator:
                await self.task_creator(lead_id, message)
            else:
                logger.warning(f"No sender configured for {message.channel.value}")
                return False
            
            # Update state
            message.sent = True
            message.sent_at = datetime.now()
            state.current_message_order = message.sequence_order
            state.messages_sent += 1
            
            # Schedule next message
            next_msg = sequence.get_next_message(
                self._build_lead_state(state),
                state.current_message_order
            )
            if next_msg:
                state.next_scheduled_time = next_msg.get_send_time(datetime.now())
            else:
                state.status = "completed"
                state.exit_at = datetime.now()
                sequence.total_completed += 1
            
            logger.info(f"Sent {message.channel.value} message {message.sequence_order} to {lead_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing action: {e}")
            return False
    
    def record_engagement(self,
                         lead_id: str,
                         engagement_type: str,
                         details: Optional[Dict] = None) -> None:
        """
        Record engagement from a lead
        
        Args:
            lead_id: Lead ID
            engagement_type: Type of engagement (open, click, reply, etc.)
            details: Additional details
        """
        state = self.lead_states.get(lead_id)
        if not state:
            return
        
        sequence = self.sequences.get(state.sequence_id)
        
        if engagement_type == "open":
            state.total_opens += 1
            state.messages_opened += 1
            logger.info(f"Lead {lead_id} opened email")
            
        elif engagement_type == "click":
            state.total_clicks += 1
            state.messages_clicked += 1
            logger.info(f"Lead {lead_id} clicked link")
            
        elif engagement_type == "reply":
            state.total_replies += 1
            logger.info(f"Lead {lead_id} replied")
            
            # Check if should exit sequence
            if sequence and sequence.exit_on_reply:
                self.exit_sequence(lead_id, "replied")
                
        elif engagement_type == "meeting_booked":
            logger.info(f"Lead {lead_id} booked meeting")
            if sequence and sequence.exit_on_meeting:
                self.exit_sequence(lead_id, "meeting_booked")
                
        elif engagement_type == "negative_response":
            logger.info(f"Lead {lead_id} responded negatively")
            if sequence and sequence.exit_on_negative:
                self.exit_sequence(lead_id, "not_interested")
        
        state.last_activity = datetime.now()
    
    def exit_sequence(self, lead_id: str, reason: str) -> None:
        """Exit a lead from their sequence"""
        state = self.lead_states.get(lead_id)
        if not state:
            return
        
        state.status = "exited"
        state.exit_reason = reason
        state.exit_at = datetime.now()
        
        sequence = self.sequences.get(state.sequence_id)
        if sequence:
            sequence.total_exited += 1
        
        logger.info(f"Lead {lead_id} exited sequence: {reason}")
    
    def pause_sequence(self, lead_id: str) -> None:
        """Pause a lead's sequence"""
        state = self.lead_states.get(lead_id)
        if state:
            state.status = "paused"
            logger.info(f"Paused sequence for {lead_id}")
    
    def resume_sequence(self, lead_id: str) -> None:
        """Resume a paused sequence"""
        state = self.lead_states.get(lead_id)
        if state:
            state.status = "active"
            logger.info(f"Resumed sequence for {lead_id}")
    
    def get_sequence_stats(self, sequence_id: Optional[str] = None) -> Dict[str, Any]:
        """Get sequence statistics"""
        if sequence_id:
            seq = self.sequences.get(sequence_id)
            if seq:
                return {
                    "id": seq.id,
                    "name": seq.name,
                    "enrolled": seq.total_enrolled,
                    "completed": seq.total_completed,
                    "exited": seq.total_exited,
                    "active": seq.total_enrolled - seq.total_completed - seq.total_exited,
                }
            return {}
        
        # All sequences
        return {
            "total_sequences": len(self.sequences),
            "total_leads": len(self.lead_states),
            "sequences": [self.get_sequence_stats(sid) for sid in self.sequences.keys()],
        }
    
    def get_lead_status(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Get lead's sequence status"""
        state = self.lead_states.get(lead_id)
        if not state:
            return None
        
        sequence = self.sequences.get(state.sequence_id)
        
        return {
            "lead_id": lead_id,
            "sequence": sequence.name if sequence else "Unknown",
            "status": state.status,
            "enrolled_at": state.enrolled_at.isoformat(),
            "messages_sent": state.messages_sent,
            "total_opens": state.total_opens,
            "total_clicks": state.total_clicks,
            "total_replies": state.total_replies,
            "exit_reason": state.exit_reason,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ═══ QUICK START ═══
# ═══════════════════════════════════════════════════════════════════════════════

async def demo():
    """Demo FollowUpAutomator functionality"""
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "FOLLOW-UP AUTOMATOR DEMO" + " " * 27 + "║")
    print("╚" + "═" * 68 + "╝")
    
    automator = FollowUpAutomator()
    
    # Show available sequences
    print("\n📋 Available Sequences:")
    for seq_id, seq in automator.sequences.items():
        print(f"  • {seq.name} ({len(seq.messages)} messages)")
        print(f"    Target: {seq.target_swarm or 'General'}")
    
    # Enroll a lead
    print(f"\n{'─' * 70}")
    print(f"  ENROLLING TEST LEADS")
    print(f"{'─' * 70}")
    
    test_leads = [
        ("lead_001", "seq_construction_standard", "John Smith - Elite Roofing"),
        ("lead_002", "seq_spirituality_standard", "Father Michael - Sacred Heart"),
        ("lead_003", "seq_growth_standard", "Sarah Johnson - TechStart"),
    ]
    
    for lead_id, seq_id, description in test_leads:
        state = automator.enroll_lead(lead_id, seq_id)
        if state:
            print(f"  ✓ Enrolled {description}")
            print(f"    Sequence: {automator.sequences[seq_id].name}")
            print(f"    Messages: {len(automator.sequences[seq_id].messages)}")
        else:
            print(f"  ✗ Failed to enroll {description}")
    
    # Show initial statuses
    print(f"\n{'─' * 70}")
    print(f"  LEAD STATUSES")
    print(f"{'─' * 70}")
    
    for lead_id, _, _ in test_leads:
        status = automator.get_lead_status(lead_id)
        if status:
            print(f"\n  {status['lead_id']}")
            print(f"    Sequence: {status['sequence']}")
            print(f"    Status: {status['status']}")
            print(f"    Enrolled: {status['enrolled_at']}")
    
    # Simulate time passing
    print(f"\n{'─' * 70}")
    print(f"  SIMULATING TIME PASSAGE")
    print(f"{'─' * 70}")
    
    # Simulate engagement
    print("\n  Recording engagements:")
    automator.record_engagement("lead_001", "open")
    automator.record_engagement("lead_001", "click")
    automator.record_engagement("lead_002", "reply")
    
    # Check statuses after engagement
    print(f"\n{'─' * 70}")
    print(f"  UPDATED STATUSES")
    print(f"{'─' * 70}")
    
    for lead_id, _, _ in test_leads:
        status = automator.get_lead_status(lead_id)
        if status:
            print(f"\n  {status['lead_id']}")
            print(f"    Opens: {status['total_opens']}")
            print(f"    Clicks: {status['total_clicks']}")
            print(f"    Replies: {status['total_replies']}")
            if status['exit_reason']:
                print(f"    Exit Reason: {status['exit_reason']}")
    
    # Show sequence stats
    print(f"\n{'─' * 70}")
    print(f"  SEQUENCE STATISTICS")
    print(f"{'─' * 70}")
    
    stats = automator.get_sequence_stats()
    print(f"  Total Sequences: {stats['total_sequences']}")
    print(f"  Total Enrolled: {stats['total_leads']}")
    print()
    for seq_stat in stats['sequences']:
        if seq_stat:
            print(f"  {seq_stat['name']}")
            print(f"    Enrolled: {seq_stat['enrolled']}")
            print(f"    Active: {seq_stat['active']}")
            print(f"    Completed: {seq_stat['completed']}")
            print(f"    Exited: {seq_stat['exited']}")
            print()
    
    # Show sequence details
    print(f"{'─' * 70}")
    print(f"  CONSTRUCTION SEQUENCE DETAILS")
    print(f"{'─' * 70}")
    
    seq = automator.sequences.get("seq_construction_standard")
    if seq:
        print(f"\n  Sequence: {seq.name}")
        print(f"  Messages: {len(seq.messages)}")
        print(f"  Exit on Reply: {seq.exit_on_reply}")
        print(f"  Skip Weekends: {seq.skip_weekends}")
        print()
        
        for msg in seq.messages:
            print(f"  [{msg.sequence_order}] {msg.channel.value.upper()}")
            if msg.subject:
                print(f"      Subject: {msg.subject[:50]}...")
            print(f"      Delay: +{msg.delay_days} days")
            print(f"      Condition: {msg.trigger_condition.value if msg.trigger_condition else 'None'}")
            print()


if __name__ == "__main__":
    asyncio.run(demo())
