import json
import logging
from datetime import datetime
from typing import Any, Optional

from .base import TradeLead
from engine.database import Database

logger = logging.getLogger(__name__)


class ConversionPipeline:
    """
    Full lead-to-revenue pipeline:
    lead → account → nurture → payment → subscription
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        import os
        db_path = os.path.join(data_dir, "lead_gen.db")
        Database.set_db_file(db_path)
        Database.initialize()

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
        try:
            with Database.get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trade_accounts (
                        account_id, lead_id, business_name, phone, email, address, website, trade, source, plan, status, created_at, monthly_fee, leads_generated, conversions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    account["account_id"],
                    account["lead_id"],
                    account["business_name"],
                    account["phone"],
                    account["email"],
                    account["address"],
                    account["website"],
                    account["trade"],
                    account["source"],
                    account["plan"],
                    account["status"],
                    account["created_at"],
                    account["monthly_fee"],
                    account["leads_generated"],
                    account["conversions"]
                ))
                conn.commit()
        except Exception as e:
            logger.error("Failed to save trade account: %s", e)

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
        try:
            with Database.get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trade_payments (
                        payment_id, account_id, amount, method, status, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    payment["payment_id"],
                    payment["account_id"],
                    payment["amount"],
                    payment["method"],
                    payment["status"],
                    payment["timestamp"]
                ))
                conn.commit()
        except Exception as e:
            logger.error("Failed to save trade payment: %s", e)
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
        accounts = []
        try:
            with Database.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM trade_accounts")
                for r in cursor.fetchall():
                    accounts.append(dict(r))
        except Exception as e:
            logger.error("Failed to read trade accounts: %s", e)
        return accounts

    def get_payments(self) -> list[dict]:
        payments = []
        try:
            with Database.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM trade_payments")
                for r in cursor.fetchall():
                    payments.append(dict(r))
        except Exception as e:
            logger.error("Failed to read trade payments: %s", e)
        return payments

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
