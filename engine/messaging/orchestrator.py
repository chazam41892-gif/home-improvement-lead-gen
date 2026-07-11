"""Messaging orchestrator — dispatches SMS/email/call follow-ups."""
from __future__ import annotations

import logging
from typing import Any, Dict

from .providers import SMSProvider, EmailProvider, CallProvider

logger = logging.getLogger(__name__)


class MessagingOrchestrator:
    def __init__(self):
        self.sms = SMSProvider()
        self.email = EmailProvider()
        self.call = CallProvider()

    async def send_sms(self, to: str, body: str) -> Dict[str, Any]:
        return await self.sms.send(to, body)

    async def send_email(self, to: str, subject: str, body: str, html: str = "") -> Dict[str, Any]:
        return await self.email.send(to, subject, body, html=html or None)

    async def queue_call(self, to: str, note: str) -> Dict[str, Any]:
        return await self.call.queue(to, note)

    def status(self) -> Dict[str, Any]:
        return {
            "sms": {"provider": self.sms.name, "configured": self.sms.is_configured},
            "email": {"provider": self.email.name, "configured": self.email.is_configured},
            "call": {"provider": self.call.name, "configured": self.call.is_configured},
        }
