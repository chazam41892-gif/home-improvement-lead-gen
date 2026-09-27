"""Shared fixtures for the main.py route tests (test_routes_*).

Imported explicitly per test module (`from tests.routes_fixtures import *`) because
pytest only auto-loads conftest.py, and the repo's tests/conftest.py is shared
with the pre-existing suite (its `client` fixture there deliberately uses the
lifespan context manager, which we must avoid -- see below).

ISOLATION CONTRACT -- everything here exists so these tests never touch the
developer's real machine state:

* ``Database.set_db_file`` is pointed at ``tmp_path`` so no route can read or
  write the real ``data/lead_gen.db``. Verified: main.py routes such as
  ``/api/ads/campaigns`` and ``/api/trades/convert`` open the DB directly.
* ``TestClient(app)`` is deliberately NOT used as a context manager, so the
  ``lifespan`` hook never runs. The lifespan would (a) load/save real lead state
  and (b) start the 30-second nurture loop, which can dispatch real SMS/email.
* The KeyVault classmethods are monkeypatched because ``KeyVault.set_key``
  resolves to the *shared* HiveMind / ``~/.lvtn`` vault -- writing a test key
  there would leak into every other project on the box.
* The Stripe SDK calls are replaced with local coroutines so no route can reach
  api.stripe.com. A live ``STRIPE_SECRET_KEY`` is present in this checkout's
  ``.env``, so ``stripe_integration.is_configured`` can be genuinely True and
  the un-stubbed path would charge a real card.

Tests that DO want the real external integration are explicit about it: they
either assert the "not configured" 503/400 branch, or they stub the SDK and say
so in the docstring.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from engine.auth import auth_manager
from engine.database import Database
from engine.router import DEFAULT_ROUTING_CONFIG


API_KEY = "test-api-key-for-ci-only"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture
def isolated_db(tmp_path, request):
    """Point the whole app at a throwaway SQLite file.

    ``auth_manager._ensure_tables()`` is required because ``Database.initialize()``
    creates the leads/ads/nurture tables but NOT users/orgs/api_keys/verticals,
    which AuthManager owns (tests/test_growth_portal.py already does this).
    Without it every /api/auth/* route 500s with "no such table: users".
    """
    original = Database.db_file
    Database.set_db_file(str(tmp_path / "routes_test.db"))
    Database.initialize()
    auth_manager._ensure_tables()
    yield Database.db_file
    Database.set_db_file(original)


@pytest.fixture
def clean_state(isolated_db):
    """Isolated DB + empty in-memory engines so route tests start from zero.

    Without the engine wipe, /api/leads and friends would assert against whatever
    leads earlier tests in the session happened to leave in main.engine.
    """
    saved_leads = dict(main.engine._leads)
    saved_history = list(main.engine._search_history)
    saved_pages = dict(main.landing_gen._pages)
    saved_exa = main.engine._exa
    saved_pplx = main.engine._perplexity
    saved_disc_leads = list(main.discovery_engine._leads_db)
    saved_disc_jobs = dict(main.discovery_engine.jobs)

    main.engine._leads.clear()
    main.engine._search_history.clear()
    main.landing_gen._pages.clear()
    main._buckets.clear()
    # DiscoveryEngine is a process singleton too, so its ingest buffer would
    # otherwise leak between tests and make /api/discovery/leads non-deterministic.
    main.discovery_engine._leads_db.clear()
    main.discovery_engine.jobs.clear()
    # Search keys live on the process-wide engine singleton; a test that calls
    # set_exa_key() would otherwise make every later test think Exa is live.
    main.engine._exa = None
    main.engine._perplexity = None
    # Re-assert the shipped routing config: PUT /api/routing/config mutates the
    # module-level SmartRouter and the app is a process-wide singleton, so a test
    # that disables a step would otherwise leak into every later test.
    main.engine.set_routing_config(DEFAULT_ROUTING_CONFIG)

    yield

    main.engine._leads.clear()
    main.engine._leads.update(saved_leads)
    main.engine._search_history[:] = saved_history
    main.landing_gen._pages.clear()
    main.landing_gen._pages.update(saved_pages)
    main.engine._exa = saved_exa
    main.engine._perplexity = saved_pplx
    main.discovery_engine._leads_db.clear()
    main.discovery_engine._leads_db.extend(saved_disc_leads)
    main.discovery_engine.jobs.clear()
    main.discovery_engine.jobs.update(saved_disc_jobs)
    main._buckets.clear()


@pytest.fixture
def client(clean_state):
    """Authenticated TestClient. No context manager -> no lifespan, no bg loops."""
    c = TestClient(main.app, raise_server_exceptions=False)
    c.headers.update(AUTH)
    return c


@pytest.fixture
def anon(clean_state):
    """Unauthenticated TestClient, for the 401 assertions."""
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def vault_sandbox(monkeypatch):
    """KeyVault writes are trapped in-process.

    Real KeyVault.set_key/delete_key fall through to the HiveMind vault and then
    the ~/.lvtn unified vault -- both shared with every other project on the box.
    """
    store: dict[tuple[str, str], str] = {}

    def _set(service, key, label="user"):
        store[(service, label)] = key
        return True

    def _del(service, label="user"):
        return store.pop((service, label), None) is not None

    def _get(service):
        return store.get((service, "user")) or store.get((service, "env"))

    def _list(cls):
        out: dict[str, dict] = {}
        for (svc, lbl) in store:
            out.setdefault(svc, {"configured": True, "keys": []})
            out[svc]["keys"].append({"label": lbl})
        return out

    monkeypatch.setattr(main.KeyVault, "set_key", staticmethod(_set))
    monkeypatch.setattr(main.KeyVault, "delete_key", staticmethod(_del))
    monkeypatch.setattr(main.KeyVault, "get", classmethod(lambda cls, s: _get(s)))
    monkeypatch.setattr(main.KeyVault, "list", classmethod(_list))
    return store


@pytest.fixture
def fake_stripe(monkeypatch):
    """Fully local StripeIntegration doubles -- no network, no charges.

    The route closes over the module-level ``main.stripe_integration``, so this
    patches that instance's methods (and the is_configured flag) in place.
    """
    inst = main.stripe_integration
    calls: list[tuple] = []

    async def create_checkout_session(plan, account_id, success_url, cancel_url):
        calls.append(("checkout", plan, account_id, success_url, cancel_url))
        if plan not in {"starter", "growth", "pro", "enterprise"}:
            raise ValueError(f"Unknown plan: {plan}")
        return {"url": f"https://checkout.stripe.test/s/{account_id}",
                "session_id": "cs_test_0001"}

    async def create_billing_portal(account_id, return_url):
        calls.append(("portal", account_id, return_url))
        if account_id == "no_mapping":
            raise ValueError(f"No mapping found for account {account_id}")
        return {"url": "https://billing.stripe.test/p/portal"}

    async def get_subscription(account_id):
        calls.append(("get_subscription", account_id))
        if account_id == "gone":
            return {"status": "not_found", "account_id": account_id}
        if account_id == "incomplete":
            return {"status": "incomplete", "account_id": account_id}
        return {"account_id": account_id, "subscription_id": "sub_test_0001",
                "status": "active", "plan": "growth",
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
                "cancel_at_period_end": False}

    async def cancel_subscription(account_id):
        calls.append(("cancel", account_id))
        if account_id == "no_mapping":
            raise ValueError(f"No mapping found for account {account_id}")
        return {"ok": True, "subscription_id": "sub_test_0001",
                "status": "active", "cancel_at_period_end": True}

    # `is_configured` is a read-only @property on StripeIntegration, so it has to
    # be patched on the class, not the instance. It reads self.secret_key, so also
    # force a value that _is_live_secret() accepts.
    from engine.stripe_integration import StripeIntegration
    monkeypatch.setattr(StripeIntegration, "is_configured", property(lambda self: True))
    monkeypatch.setattr(inst, "secret_key", "sk_test_locally_stubbed", raising=False)
    monkeypatch.setattr(inst, "create_checkout_session", create_checkout_session)
    monkeypatch.setattr(inst, "create_billing_portal", create_billing_portal)
    monkeypatch.setattr(inst, "get_subscription", get_subscription)
    monkeypatch.setattr(inst, "cancel_subscription", cancel_subscription)
    inst.calls = calls
    return inst


@pytest.fixture
def stripe_unconfigured(monkeypatch):
    """Force the 'no live Stripe key' branch -- used for the 503 paths."""
    from engine.stripe_integration import StripeIntegration
    monkeypatch.setattr(StripeIntegration, "is_configured", property(lambda self: False))


def seed_lead(lead_id="L1", *, title="Acme Roofing", score=70.0, **over):
    """Put a real LeadResult into main.engine and return its id."""
    from engine.scout import LeadResult
    from engine.utils.scoring import score_lead as _score

    ls = _score(title=title, snippet=over.pop("snippet", "roof repair in Austin TX"),
                url=over.pop("url", f"https://{lead_id}.example.com"))
    lead = LeadResult(
        id=lead_id,
        title=title,
        url=f"https://{lead_id}.example.com",
        snippet=over.pop("snippet", "roof repair in Austin TX"),
        industry=over.pop("industry", "roofing"),
        location=over.pop("location", "Austin, TX"),
        source=over.pop("source", "exa"),
        score=ls,
        found_at="2026-01-01T00:00:00",
    )
    lead.score.total = score
    for k, v in over.items():
        setattr(lead, k, v)
    main.engine._leads[lead_id] = lead
    return lead_id
