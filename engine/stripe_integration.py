from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import stripe

logger = logging.getLogger(__name__)

_DATA_DIR = "data"
_MAPPINGS_FILE = os.path.join(_DATA_DIR, "stripe_mappings.jsonl")

PLANS = {
    "starter": 9700,
    "growth": 19700,
    "pro": 49700,
    "enterprise": 99700,
}


class StripeIntegration:
    def __init__(self):
        self.secret_key = os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        stripe.api_key = self.secret_key
        self._price_ids = {
            plan: os.getenv(f"STRIPE_PRICE_{plan.upper()}", "")
            for plan in PLANS
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.secret_key)

    def _read_mappings(self) -> list[dict]:
        if not os.path.exists(_MAPPINGS_FILE):
            return []
        records = []
        with open(_MAPPINGS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def _write_mappings(self, mappings: list[dict]):
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_MAPPINGS_FILE, "w") as f:
            for record in mappings:
                f.write(json.dumps(record, default=str) + "\n")

    def _append_mapping(self, mapping: dict):
        os.makedirs(_DATA_DIR, exist_ok=True)
        with open(_MAPPINGS_FILE, "a") as f:
            f.write(json.dumps(mapping, default=str) + "\n")

    async def create_checkout_session(
        self, plan: str, account_id: str, success_url: str, cancel_url: str
    ) -> dict:
        amount = PLANS.get(plan)
        if not amount:
            raise ValueError(f"Unknown plan: {plan}")

        price_id = self._price_ids.get(plan, "")

        if price_id:
            line_item = {"price": price_id, "quantity": 1}
        else:
            line_item = {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"{plan.capitalize()} Plan"},
                    "unit_amount": amount,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }

        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[line_item],
            metadata={"account_id": account_id, "plan": plan},
            success_url=success_url,
            cancel_url=cancel_url,
        )

        return {"url": session.url, "session_id": session.id}

    async def handle_webhook(self, payload: bytes, sig_header: str) -> dict:
        if not self.webhook_secret:
            raise ValueError("Webhook secret not configured")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, self.webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            raise ValueError(f"Webhook signature verification failed: {e}")

        event_type = event.get("type")
        data = event["data"]["object"]

        handler = {
            "checkout.session.completed": self._on_checkout_completed,
            "customer.subscription.deleted": self._on_subscription_deleted,
            "invoice.payment_succeeded": self._on_invoice_paid,
            "invoice.payment_failed": self._on_invoice_failed,
        }.get(event_type)

        if handler:
            await handler(data)

        return {"received": True, "type": event_type}

    async def _on_checkout_completed(self, session: dict):
        account_id = session.get("metadata", {}).get("account_id")
        plan = session.get("metadata", {}).get("plan", "starter")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        if not account_id or not customer_id:
            logger.warning("Checkout session missing account_id or customer")
            return

        self._append_mapping({
            "account_id": account_id,
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "plan": plan,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "Checkout completed: account=%s customer=%s sub=%s",
            account_id, customer_id, subscription_id,
        )

    async def _on_subscription_deleted(self, subscription: dict):
        sub_id = subscription.get("id")
        mappings = self._read_mappings()
        updated = False
        for m in mappings:
            if m.get("stripe_subscription_id") == sub_id:
                m["status"] = "cancelled"
                m["cancelled_at"] = datetime.now(timezone.utc).isoformat()
                updated = True
                break
        if updated:
            self._write_mappings(mappings)
            logger.info("Subscription deleted: %s", sub_id)

    async def _on_invoice_paid(self, invoice: dict):
        subscription_id = invoice.get("subscription")
        customer_id = invoice.get("customer")
        amount_paid = invoice.get("amount_paid", 0)
        logger.info(
            "Invoice paid: sub=%s customer=%s amount=%d",
            subscription_id, customer_id, amount_paid,
        )

    async def _on_invoice_failed(self, invoice: dict):
        subscription_id = invoice.get("subscription")
        customer_id = invoice.get("customer")
        logger.warning(
            "Invoice failed: sub=%s customer=%s",
            subscription_id, customer_id,
        )

    async def get_subscription(self, account_id: str) -> dict:
        mappings = self._read_mappings()
        for m in mappings:
            if m.get("account_id") == account_id:
                sub_id = m.get("stripe_subscription_id")
                if not sub_id:
                    return {"status": "incomplete", "account_id": account_id}
                try:
                    sub = stripe.Subscription.retrieve(sub_id)
                    return {
                        "account_id": account_id,
                        "subscription_id": sub.id,
                        "status": sub.status,
                        "plan": m.get("plan", "unknown"),
                        "current_period_start": sub.current_period_start,
                        "current_period_end": sub.current_period_end,
                        "cancel_at_period_end": sub.cancel_at_period_end,
                    }
                except stripe.error.StripeError as e:
                    logger.error("Failed to retrieve subscription: %s", e)
                    return {"status": "error", "error": str(e), "account_id": account_id}
        return {"status": "not_found", "account_id": account_id}

    async def cancel_subscription(self, account_id: str) -> dict:
        mappings = self._read_mappings()
        for m in mappings:
            if m.get("account_id") == account_id:
                sub_id = m.get("stripe_subscription_id")
                if not sub_id:
                    raise ValueError(f"No subscription found for account {account_id}")
                try:
                    sub = stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
                    m["cancel_at_period_end"] = True
                    self._write_mappings(mappings)
                    return {
                        "ok": True,
                        "subscription_id": sub.id,
                        "status": sub.status,
                        "cancel_at_period_end": sub.cancel_at_period_end,
                    }
                except stripe.error.StripeError as e:
                    logger.error("Failed to cancel subscription: %s", e)
                    raise ValueError(f"Stripe error: {e}")
        raise ValueError(f"No mapping found for account {account_id}")

    async def create_billing_portal(self, account_id: str, return_url: str) -> dict:
        mappings = self._read_mappings()
        customer_id = None
        for m in mappings:
            if m.get("account_id") == account_id:
                customer_id = m.get("stripe_customer_id")
                break

        if not customer_id:
            raise ValueError(f"No Stripe customer found for account {account_id}")

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return {"url": session.url}
