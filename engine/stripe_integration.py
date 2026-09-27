from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import stripe
from stripe.params.checkout import SessionCreateParamsLineItem

from engine.key_vault import KeyVault

logger = logging.getLogger(__name__)

_DATA_DIR = "data"
_MAPPINGS_FILE = os.path.join(_DATA_DIR, "stripe_mappings.jsonl")

PLANS = {
    "starter": 9700,
    "growth": 19700,
    "pro": 49700,
    "enterprise": 99700,
}


class _StripeAccessor:
    """Version-agnostic reader for Stripe payloads (audit 2026-09-27, C-2).

    stripe>=12 removed the dict base class from `StripeObject`, so `.get()` raises
    AttributeError on installed stripe 15.2.0. stripe<=11 payloads are plain dicts.
    This callable handles BOTH so the webhook path never depends on the SDK major:

        g = _StripeAccessor(event)
        g("type")            # subscript first, then attribute, then default
        g("amount_paid", 0)  # explicit default
        g("metadata") or {}  # returns None when absent
    """

    __slots__ = ("_obj",)

    def __init__(self, obj):
        self._obj = obj

    def __call__(self, key, default=None):
        obj = self._obj
        if obj is None:
            return default
        # dict-like
        if isinstance(obj, dict):
            val = obj.get(key, default)
            return default if val is None else val
        # stripe.StripeObject: __getitem__ works and raises KeyError when absent
        try:
            val = obj[key]
        except (KeyError, TypeError, IndexError):
            val = getattr(obj, key, default)
        except Exception:
            val = default
        if val is None:
            return default
        return val


#: Credential placeholders that must never be treated as live config.
#: Audit 2026-09-27: the unified vault holds an 18-char `FAKE…` value under
#: `stripe_secret`. `is_configured` was `bool(self.secret_key)`, so that
#: placeholder read as CONFIGURED and a real Stripe API call was attempted with a
#: bogus key, raising a confusing AuthenticationError instead of "not configured".
PLACEHOLDER_PREFIXES = (
    "FAKE",
    "XXX",
    "CHANGEME",
    "CHANGE_ME",
    "PLACEHOLDER",
    "YOUR_",
    "REPLACE_",
    "TODO",
    "DUMMY",
    "TESTKEY",
)
_MIN_SECRET_LEN = 20  # real Stripe secret keys are far longer than a placeholder


def _is_live_secret(value) -> bool:
    """True only for something that could plausibly be a real credential."""
    if not value:
        return False
    v = value.strip()
    if len(v) < _MIN_SECRET_LEN:
        return False
    return not v.upper().startswith(PLACEHOLDER_PREFIXES)


class StripeIntegration:
    def __init__(self):
        raw_secret = KeyVault.get("stripe_secret") or ""
        raw_webhook = KeyVault.get("stripe_webhook") or ""
        # Do not propagate a placeholder into the SDK: doing so causes a real
        # network call that fails with a confusing AuthenticationError instead of
        # a clean "not configured".
        self.secret_key = raw_secret if _is_live_secret(raw_secret) else ""
        self.webhook_secret = raw_webhook if _is_live_secret(raw_webhook) else ""
        if raw_secret and not self.secret_key:
            logger.warning(
                "stripe_secret is a placeholder, not a live key — billing disabled "
                "until a real STRIPE secret key is configured"
            )
        stripe.api_key = self.secret_key
        self._price_ids = {plan: KeyVault.get(f"stripe_price_{plan}") or "" for plan in PLANS}

    @property
    def is_configured(self) -> bool:
        return _is_live_secret(self.secret_key)

    def _read_mappings(self) -> list[dict]:
        from engine.database import Database

        mappings = []
        try:
            with Database.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM stripe_mappings")
                for r in cursor.fetchall():
                    m = dict(r)
                    m["cancel_at_period_end"] = bool(m["cancel_at_period_end"])
                    mappings.append(m)
        except Exception as e:
            logger.error("Failed to read Stripe mappings from database: %s", e)
        return mappings

    def _write_mappings(self, mappings: list[dict]):
        from engine.database import Database

        try:
            with Database.get_connection() as conn:
                conn.execute("DELETE FROM stripe_mappings")
                for m in mappings:
                    conn.execute(
                        """
                        INSERT INTO stripe_mappings (
                            account_id, stripe_customer_id, stripe_subscription_id, plan, status, created_at, cancelled_at, cancel_at_period_end
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            m.get("account_id"),
                            m.get("stripe_customer_id"),
                            m.get("stripe_subscription_id"),
                            m.get("plan"),
                            m.get("status"),
                            m.get("created_at"),
                            m.get("cancelled_at"),
                            1 if m.get("cancel_at_period_end") else 0,
                        ),
                    )
                conn.commit()
        except Exception as e:
            logger.error("Failed to write Stripe mappings to database: %s", e)

    def _append_mapping(self, mapping: dict):
        from engine.database import Database

        try:
            with Database.get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stripe_mappings (
                        account_id, stripe_customer_id, stripe_subscription_id, plan, status, created_at, cancelled_at, cancel_at_period_end
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        mapping.get("account_id"),
                        mapping.get("stripe_customer_id"),
                        mapping.get("stripe_subscription_id"),
                        mapping.get("plan"),
                        mapping.get("status"),
                        mapping.get("created_at"),
                        mapping.get("cancelled_at"),
                        1 if mapping.get("cancel_at_period_end") else 0,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error("Failed to append Stripe mapping to database: %s", e)

    async def create_checkout_session(
        self, plan: str, account_id: str, success_url: str, cancel_url: str
    ) -> dict:
        # Audit 2026-09-27: no guard here meant an unconfigured client still called
        # Stripe and surfaced a confusing AuthenticationError (or, before the
        # placeholder fix, an actual network round-trip with a FAKE key).
        if not self.is_configured:
            raise RuntimeError(
                "Stripe is not configured — set a real stripe_secret before creating a checkout session."
            )

        amount = PLANS.get(plan)
        if not amount:
            raise ValueError(f"Unknown plan: {plan}")

        price_id = self._price_ids.get(plan, "")

        # Typed against the SDK's own TypedDict so the inline-price shape is
        # checked at compile time. Runtime value is byte-identical to the plain
        # dict literal it replaces; the two branches are mutually exclusive, so
        # the declared type has to be the shared supertype of both.
        line_item: SessionCreateParamsLineItem
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

        # CRITICAL (audit 2026-09-27, C-2): `event` is a stripe.StripeObject, NOT a
        # dict subclass in stripe>=12 (installed: 15.2.0). Calling .get() on it raised
        # AttributeError, so EVERY valid webhook returned HTTP 500 and no payment was
        # ever recorded. Subscribing the underscore-prefixed accessors below makes this
        # work identically on stripe 11 (dict-like) and stripe 15 (object-like).
        _g = _StripeAccessor(event)
        event_type = _g("type")
        data = _g("data")["object"]

        handler = {
            "checkout.session.completed": self._on_checkout_completed,
            "customer.subscription.deleted": self._on_subscription_deleted,
            "customer.subscription.updated": self._on_subscription_updated,
            "invoice.payment_succeeded": self._on_invoice_paid,
            "invoice.payment_failed": self._on_invoice_failed,
        }.get(event_type)

        if handler:
            await handler(data)

        return {"received": True, "type": event_type}

    async def _on_checkout_completed(self, session):
        g = _StripeAccessor(session)
        metadata = g("metadata") or {}
        account_id = _StripeAccessor(metadata)("account_id")
        plan = _StripeAccessor(metadata)("plan", "starter")
        customer_id = g("customer")
        subscription_id = g("subscription")

        if not account_id or not customer_id:
            logger.warning("Checkout session missing account_id or customer")
            return

        self._append_mapping(
            {
                "account_id": account_id,
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "plan": plan,
                "status": "active",
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        logger.info(
            "Checkout completed: account=%s customer=%s sub=%s",
            account_id,
            customer_id,
            subscription_id,
        )

    async def _on_subscription_deleted(self, subscription):
        await self._apply_subscription_state(
            _StripeAccessor(subscription)("id"), "cancelled", reason="subscription deleted"
        )

    async def _on_subscription_updated(self, subscription):
        """Mirror Stripe's subscription status into our local record (audit H-5).

        Previously nothing observed subscription.status changes, so a customer whose
        card bounced stayed `active` in our records for weeks.
        """
        g = _StripeAccessor(subscription)
        await self._apply_subscription_state(g("id"), g("status", "active"), reason="subscription.updated")

    async def _apply_subscription_state(self, sub_id, status, reason: str = ""):
        """Single writer for subscription state so paid/failed/deleted/updated all
        funnel through one code path (audit H-2/H-5)."""
        if not sub_id:
            return False
        mappings = self._read_mappings()
        updated = False
        for m in mappings:
            if m.get("stripe_subscription_id") == sub_id:
                m["status"] = status
                if reason:
                    m["status_reason"] = reason
                m["status_updated_at"] = datetime.now(UTC).isoformat()
                updated = True
        if updated:
            self._write_mappings(mappings)
        return updated

    async def _on_invoice_paid(self, invoice):
        g = _StripeAccessor(invoice)
        subscription_id = g("subscription")
        customer_id = g("customer")
        amount_paid = g("amount_paid", 0)
        # A successful payment clears any past_due state (audit H-2).
        if subscription_id:
            await self._apply_subscription_state(subscription_id, "active", reason="invoice paid")
        logger.info(
            "Invoice paid: sub=%s customer=%s amount=%s",
            subscription_id,
            customer_id,
            amount_paid,
        )

    async def _on_invoice_failed(self, invoice):
        g = _StripeAccessor(invoice)
        subscription_id = g("subscription")
        customer_id = g("customer")
        # HIGH (audit H-2): this used to be logger-only, leaving the account `active`
        # after a failed payment -> direct revenue leakage.
        if subscription_id:
            await self._apply_subscription_state(subscription_id, "past_due", reason="invoice payment failed")
        logger.warning(
            "Invoice failed: sub=%s customer=%s -- marked past_due",
            subscription_id,
            customer_id,
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
                    # current_period_start/end moved from the Subscription object
                    # to its first SubscriptionItem in Stripe API 2025-03-31 (SDK
                    # pin: 2026-05-27.dahlia), so they are no longer declared on
                    # Subscription. Read them version-agnostically via the same
                    # accessor used for webhooks: item-level first, then the legacy
                    # top-level field. Both keys stay in the response either way.
                    g = _StripeAccessor(sub)
                    # Subscription.items is a ListObject (payload under .data) in
                    # stripe>=9, a bare list on old SDKs / dict payloads -- accept
                    # both. The accessor already returns the default for a missing
                    # key, so an absent/None .data collapses to an empty list.
                    items = g("items")
                    if isinstance(items, (list, tuple)):
                        item_list = list(items)
                    else:
                        item_list = list(_StripeAccessor(items)("data") or [])
                    first_item = _StripeAccessor(item_list[0] if item_list else None)
                    period_start = first_item("current_period_start", g("current_period_start"))
                    period_end = first_item("current_period_end", g("current_period_end"))
                    return {
                        "account_id": account_id,
                        "subscription_id": sub.id,
                        "status": sub.status,
                        "plan": m.get("plan", "unknown"),
                        "current_period_start": period_start,
                        "current_period_end": period_end,
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
