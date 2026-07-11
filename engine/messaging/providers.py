"""Real messaging providers for follow-up automation.

Each provider returns a result dict and only sends if its credentials are
configured. If credentials are missing, it logs a warning and returns a
simulated result so the nurture engine keeps working in local/dev mode.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class SMSProvider:
    name = "twilio"

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "")
        self.base_url = "https://api.twilio.com/2010-04-01"

    @property
    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    async def send(self, to: str, body: str) -> Dict[str, Any]:
        if not self.is_configured:
            logger.warning("Twilio not configured — SMS not sent to %s", to)
            return {"ok": False, "provider": self.name, "simulated": True, "error": "Twilio not configured"}

        url = f"{self.base_url}/Accounts/{self.account_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    data={"From": self.from_number, "To": to, "Body": body},
                    auth=(self.account_sid, self.auth_token),
                )
            if resp.status_code >= 400:
                logger.error("Twilio SMS failed: %s", resp.text)
                return {"ok": False, "provider": self.name, "error": resp.text[:300]}
            data = resp.json()
            return {"ok": True, "provider": self.name, "sid": data.get("sid")}
        except Exception as e:
            logger.error("Twilio SMS request failed: %s", e)
            return {"ok": False, "provider": self.name, "error": str(e)}


class EmailProvider:
    name = "sendgrid"

    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY", "")
        self.from_email = os.getenv("SENDGRID_FROM_EMAIL", os.getenv("BUSINESS_EMAIL", ""))
        self.base_url = "https://api.sendgrid.com/v3"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.from_email)

    async def send(self, to: str, subject: str, body: str, html: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_configured:
            logger.warning("SendGrid not configured — email not sent to %s", to)
            return {"ok": False, "provider": self.name, "simulated": True, "error": "SendGrid not configured"}

        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self.from_email},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body},
            ],
        }
        if html:
            payload["content"].append({"type": "text/html", "value": html})

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/mail/send",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            if resp.status_code >= 400:
                logger.error("SendGrid email failed: %s", resp.text)
                return {"ok": False, "provider": self.name, "error": resp.text[:300]}
            return {"ok": True, "provider": self.name}
        except Exception as e:
            logger.error("SendGrid email request failed: %s", e)
            return {"ok": False, "provider": self.name, "error": str(e)}


class CallProvider:
    name = "twilio_call"

    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER", "")
        self.base_url = "https://api.twilio.com/2010-04-01"

    @property
    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    async def queue(self, to: str, message: str) -> Dict[str, Any]:
        """Queue a manual call reminder rather than auto-dialing."""
        if not self.is_configured:
            logger.warning("Twilio not configured — call reminder not queued for %s", to)
            return {"ok": False, "provider": self.name, "simulated": True, "error": "Twilio not configured"}

        # For compliance, we do not auto-dial. We log a call task for a human.
        return {
            "ok": True,
            "provider": self.name,
            "queued": True,
            "to": to,
            "note": message,
            "manual": True,
        }
