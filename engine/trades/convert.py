import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from .base import TradeLead

logger = logging.getLogger(__name__)


class ConversionPipeline:
    """
    Full lead-to-revenue pipeline:
    lead → account → nurture → payment → subscription
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self._leads_file = os.path.join(data_dir, "trade_leads.jsonl")
        self._accounts_file = os.path.join(data_dir, "trade_accounts.jsonl")
        self._payments_file = os.path.join(data_dir, "trade_payments.jsonl")
        os.makedirs(data_dir, exist_ok=True)

    async def convert_to_account(self, lead: TradeLead, plan: str = "starter") -> dict:
        """
        Convert a trade lead into a paying account.
        Returns account record with lead → account → payment info.
        """
        account = {
            "account_id": f"acc_{lead.id}",
            "lead_id": lead.id,
            "business_name": lead.business_name,
            "phone": lead.phone,
            "email": lead.email,
            "address": lead.address,
            "website": lead.website,
            "trade": lead.trade,
            "source": lead.source,
            "plan": plan,
            "status": "active",
            "created_at": datetime.now().isoformat(),
            "monthly_fee": self._plan_fee(plan),
            "leads_generated": 0,
            "conversions": 0,
        }
        self._append_jsonl(self._accounts_file, account)
        lead.converted = True
        lead.account_id = account["account_id"]
        lead.status = "converted"
        logger.info("Lead %s converted to account %s", lead.id, account["account_id"])
        return account

    async def record_payment(self, account_id: str, amount: float, method: str = "stripe") -> dict:
        payment = {
            "payment_id": f"pay_{account_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "account_id": account_id,
            "amount": amount,
            "method": method,
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
        }
        self._append_jsonl(self._payments_file, payment)
        logger.info("Payment recorded: %s for account %s ($%.2f)", payment["payment_id"], account_id, amount)
        return payment

    async def create_subscription(self, account_id: str, plan: str = "starter") -> dict:
        monthly = self._plan_fee(plan)
        subscription = {
            "subscription_id": f"sub_{account_id}",
            "account_id": account_id,
            "plan": plan,
            "monthly_fee": monthly,
            "status": "active",
            "started_at": datetime.now().isoformat(),
            "next_billing": datetime.now().isoformat(),
        }
        logger.info("Subscription created: %s ($%.2f/mo)", subscription["subscription_id"], monthly)
        return subscription

    def get_accounts(self) -> list[dict]:
        return self._read_jsonl(self._accounts_file)

    def get_payments(self) -> list[dict]:
        return self._read_jsonl(self._payments_file)

    def get_revenue_stats(self) -> dict:
        payments = self.get_payments()
        accounts = self.get_accounts()
        total_revenue = sum(p.get("amount", 0) for p in payments)
        monthly_recurring = sum(
            self._plan_fee(a.get("plan", "starter"))
            for a in accounts
            if a.get("status") == "active"
        )
        return {
            "total_accounts": len(accounts),
            "active_accounts": sum(1 for a in accounts if a.get("status") == "active"),
            "total_payments": len(payments),
            "total_revenue": total_revenue,
            "monthly_recurring_revenue": monthly_recurring,
            "average_revenue_per_account": round(total_revenue / len(accounts), 2) if accounts else 0,
        }

    def _plan_fee(self, plan: str) -> float:
        fees = {"starter": 97, "growth": 197, "pro": 497, "enterprise": 997}
        return fees.get(plan, 97)

    def _append_jsonl(self, path: str, record: dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _read_jsonl(self, path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
