"""Regression: a placeholder credential must never read as 'configured'.

Audit 2026-09-27. The unified vault (`~/.lvtn/unified_vault`) holds an 18-char
value under `stripe_secret` that is a placeholder, not a live key.
`StripeIntegration.is_configured` was `bool(self.secret_key)`, so it returned True
and the API attempted a real Stripe call, which raised AuthenticationError —
instead of cleanly reporting "not configured".

These tests pin the fix in the standalone copy.
"""
import pytest

from engine.stripe_integration import (
    StripeIntegration, _is_live_secret, PLACEHOLDER_PREFIXES, _MIN_SECRET_LEN,
)


# ── the predicate ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("placeholder", [
    "FAKE_NOT_A_REAL_KEY",
    "fake_not_a_real_key",
    "XXXXXXXXXXXXXXXXXXXX",
    "CHANGEME_CHANGEME_1",
    "PLACEHOLDER_VALUE_X",
    "YOUR_API_KEY_HERE__",
    "REPLACEME_PLACEHOLD",
    "TODO_add_real_key",
    "DUMMY_KEY_FOR_TEST",
    "short",
    "",
    None,
])
def test_placeholders_are_not_live(placeholder):
    assert _is_live_secret(placeholder) is False


def test_realistic_length_key_accepted():
    assert _is_live_secret("sk_live_" + "a" * 40) is True


def test_too_short_is_rejected_even_without_a_placeholder_prefix():
    """An 18-char non-placeholder is still not a plausible Stripe secret."""
    assert _is_live_secret("a" * (_MIN_SECRET_LEN - 1)) is False


def test_whitespace_only_rejected():
    assert _is_live_secret("   ") is False
    assert _is_live_secret("   \n ") is False


def test_surrounding_whitespace_does_not_break_a_real_key():
    assert _is_live_secret("  sk_live_" + "b" * 30 + "  ") is True


# ── the integration actually honours it ───────────────────────────────────
def test_integration_reports_unconfigured_with_a_placeholder(monkeypatch):
    import engine.stripe_integration as si

    monkeypatch.setattr(si.KeyVault, "get",
                        lambda name: "FAKE_NOT_A_REAL_KEY" if name == "stripe_secret" else "")
    inst = si.StripeIntegration()
    assert inst.is_configured is False, "a placeholder must not read as configured"
    assert inst.secret_key == "", "the placeholder must not reach the SDK"


def test_integration_accepts_a_real_looking_key(monkeypatch):
    import engine.stripe_integration as si

    monkeypatch.setattr(si.KeyVault, "get",
                        lambda name: "sk_live_" + "c" * 40 if name == "stripe_secret" else "")
    inst = si.StripeIntegration()
    assert inst.is_configured is True
    assert inst.secret_key.startswith("sk_live_")


def test_checkout_raises_rather_than_calling_stripe_when_unconfigured(monkeypatch):
    """The guard must short-circuit BEFORE any network call."""
    import asyncio
    import engine.stripe_integration as si

    monkeypatch.setattr(si.KeyVault, "get", lambda name: "FAKE_NOT_A_REAL_KEY"
                        if name == "stripe_secret" else "")
    inst = si.StripeIntegration()

    def explode(*a, **k):
        raise AssertionError("must not call Stripe with an unconfigured client")

    # raising=False: the stripe SDK exposes no `Checkout`/`checkout` attribute, and
    # the point is to prove those paths are never reached.
    monkeypatch.setattr(si.stripe, "Checkout", explode, raising=False)
    monkeypatch.setattr(si.stripe, "checkout", explode, raising=False)

    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(inst.create_checkout_session("growth", "acct_1", "", ""))
