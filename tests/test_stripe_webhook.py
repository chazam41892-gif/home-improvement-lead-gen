"""Regression tests for the Stripe webhook path (audit 2026-09-27, C-2 / H-2 / H-5).

These are the tests the suite was MISSING: nothing in tests/ referenced
construct_event, which is exactly why a 100%-failing webhook stayed green.

All secrets here are fake test values. No real key is ever used.
"""
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from main import app

FAKE_WEBHOOK_SECRET = "whsec_test_only_not_a_real_secret"


def _sign(payload: str, secret: str = FAKE_WEBHOOK_SECRET) -> str:
    ts = int(time.time())
    v1_payload = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    v1_body = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1_payload},v1={v1_body}"


def _event(event_type: str, obj: dict, event_id: str = "evt_test") -> str:
    return json.dumps({
        "id": event_id,
        "object": "event",
        "type": event_type,
        "data": {"object": obj},
    })


@pytest.fixture
def stripe(monkeypatch):
    """Patch the REAL module-level StripeIntegration that the route closes over.

    main.py:229 builds `stripe_integration = StripeIntegration()` at import time, so
    patching __init__ or constructing a fresh instance has no effect on the route.
    We also redirect the mappings file so these tests never touch real records.
    """
    import engine.stripe_integration as si
    import main as main_mod

    inst = main_mod.stripe_integration
    monkeypatch.setattr(inst, "webhook_secret", FAKE_WEBHOOK_SECRET, raising=False)
    monkeypatch.setattr(inst, "secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(si, "_MAPPINGS_FILE", "data/_test_stripe_mappings.jsonl",
                        raising=False)
    inst._write_mappings([])

    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c, inst


def _post(client, payload: str, sig: str | None = None):
    return client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"stripe-signature": sig or _sign(payload),
                 "Content-Type": "application/json"},
    )


# ── the bug: every valid event returned 500 ──────────────────────────────
def test_valid_webhook_returns_200_not_500(stripe):
    """Regression for audit C-2: on stripe>=12 StripeObject is not a dict, so
    `event.get('type')` raised AttributeError and the route 500'd for EVERY
    valid event -- no payment was ever recorded."""
    c, _ = stripe
    payload = _event("checkout.session.completed", {
        "object": "checkout.session", "id": "cs_test_1",
        "metadata": {"account_id": "acct_test_1", "plan": "growth"},
        "customer": "cus_test_1", "subscription": "sub_test_1",
    })
    r = _post(c, payload)
    assert r.status_code == 200, f"valid webhook returned {r.status_code}: {r.text[:300]}"
    assert r.json()["type"] == "checkout.session.completed"


def test_invoice_payment_failed_returns_200(stripe):
    c, _ = stripe
    payload = _event("invoice.payment_failed", {
        "object": "invoice", "id": "in_test_1",
        "subscription": "sub_test_1", "customer": "cus_test_1",
    })
    r = _post(c, payload)
    assert r.status_code == 200, f"invoice.payment_failed returned {r.status_code}"
    assert r.json()["type"] == "invoice.payment_failed"


def test_subscription_updated_returns_200(stripe):
    c, _ = stripe
    payload = _event("customer.subscription.updated", {
        "object": "subscription", "id": "sub_test_1",
        "status": "active", "customer": "cus_test_1",
    })
    r = _post(c, payload)
    assert r.status_code == 200, f"subscription.updated returned {r.status_code}"


def test_failed_payment_marks_subscription_past_due(stripe):
    """Regression for audit H-2: _on_invoice_failed was logger-only, so a bouncing
    card left the account `active` -- direct revenue leakage."""
    c, inst = stripe
    inst._write_mappings([{
        "account_id": "acct_test_1",
        "stripe_subscription_id": "sub_pastdue_1",
        "status": "active",
    }])
    payload = _event("invoice.payment_failed", {
        "object": "invoice", "id": "in_pd",
        "subscription": "sub_pastdue_1", "customer": "cus_test_1",
    })
    r = _post(c, payload)
    assert r.status_code == 200

    row = next(x for x in inst._read_mappings()
               if x["stripe_subscription_id"] == "sub_pastdue_1")
    assert row["status"] == "past_due", f"expected past_due, got {row['status']!r}"


def test_successful_payment_restores_active(stripe):
    """A later successful invoice must clear past_due."""
    c, inst = stripe
    inst._write_mappings([{
        "account_id": "acct_test_1",
        "stripe_subscription_id": "sub_recover_1",
        "status": "past_due",
    }])
    payload = _event("invoice.payment_succeeded", {
        "object": "invoice", "id": "in_ok",
        "subscription": "sub_recover_1", "customer": "cus_test_1",
        "amount_paid": 19700,
    })
    r = _post(c, payload)
    assert r.status_code == 200

    row = next(x for x in inst._read_mappings()
               if x["stripe_subscription_id"] == "sub_recover_1")
    assert row["status"] == "active", f"expected active, got {row['status']!r}"


# ── signature verification must KEEP rejecting ──────────────────────────
def test_wrong_secret_is_rejected(stripe):
    c, _ = stripe
    payload = _event("checkout.session.completed",
                     {"object": "checkout.session", "id": "cs_x"})
    ts = int(time.time())
    r = _post(c, payload, sig=f"t={ts},v1={'0' * 64}")
    assert r.status_code == 400


def test_missing_signature_is_rejected(stripe):
    c, _ = stripe
    payload = _event("checkout.session.completed",
                     {"object": "checkout.session", "id": "cs_y"})
    r = c.post("/api/billing/webhook", content=payload,
               headers={"stripe-signature": "", "Content-Type": "application/json"})
    assert r.status_code == 400


def test_tampered_payload_is_rejected(stripe):
    c, _ = stripe
    payload = _event("checkout.session.completed",
                     {"object": "checkout.session", "id": "cs_z"})
    sig = _sign(payload)
    tampered = payload.replace("cs_z", "cs_TAMPERED")
    r = _post(c, tampered, sig=sig)
    assert r.status_code == 400


def test_replay_of_same_event_is_idempotent(stripe):
    """A redelivered checkout event must not raise and must not double-grant."""
    c, inst = stripe
    inst._write_mappings([])
    payload = _event("checkout.session.completed", {
        "object": "checkout.session", "id": "cs_replay",
        "metadata": {"account_id": "acct_replay", "plan": "starter"},
        "customer": "cus_replay", "subscription": "sub_replay",
    })
    first = _post(c, payload)
    second = _post(c, payload)
    assert first.status_code == 200
    assert second.status_code == 200
    rows = [x for x in inst._read_mappings() if x.get("account_id") == "acct_replay"]
    assert len(rows) == 1, f"expected 1 mapping after replay, got {len(rows)}"
