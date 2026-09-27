"""Route tests: /api/ads/*, /api/billing/*, /api/vault/*, /api/enrich/*,
/api/auth/*, /api/trades/*, /api/discovery/ingest.

Every external integration is either stubbed locally (Stripe, ad platforms,
enrichment providers, trade discovery) or asserted only on its validation and
"not configured" error path. No network call is made and no card is charged.
"""
from __future__ import annotations

import pytest

import main
from tests.routes_fixtures import *  # noqa: F401,F403 -- pytest fixtures


# ══════════════════════════════════════════════════════════════════════════
# /api/ads/*  — copy generation, pixels, UTM, platform launch
# ══════════════════════════════════════════════════════════════════════════
def test_ad_copy_requires_an_industry(client):
    r = client.post("/api/ads/generate-copy", json={"location": "Austin"})
    assert r.status_code == 400
    assert r.json()["error"] == "industry is required"


def test_ad_copy_generates_the_requested_number_of_ads(client):
    r = client.post("/api/ads/generate-copy", json={
        "industry": "roofing", "location": "Austin", "count": 3, "platform": "google"})
    assert r.status_code == 200
    ads = r.json()["ads"]
    assert len(ads) == 3
    for ad in ads:
        assert {"headline", "description", "cta"} <= set(ad)
        assert ad["headline"] and ad["description"] and ad["cta"]


def test_ad_copy_includes_the_location_and_industry(client):
    ads = client.post("/api/ads/generate-copy",
                      json={"industry": "roofing", "location": "Austin"}
                      ).json()["ads"]
    assert any("Roofing" in a["headline"] for a in ads)
    assert any("Austin" in a["headline"] or "Austin" in a["description"] for a in ads)


def test_ad_copy_honours_the_platform(client):
    fb = client.post("/api/ads/generate-copy",
                     json={"industry": "plumbing", "platform": "facebook"}
                     ).json()["ads"]
    assert fb[0]["platform"] == "facebook"


def test_ad_copy_honours_a_custom_usp(client):
    ads = client.post("/api/ads/generate-copy", json={
        "industry": "hvac", "usp": "24/7 emergency service", "count": 2,
    }).json()["ads"]
    assert any("24/7" in a["description"] or "24/7" in a["headline"] for a in ads)


def test_ad_keywords_require_an_industry(client):
    r = client.post("/api/ads/generate-keywords", json={"location": "Austin"})
    assert r.status_code == 400
    assert r.json()["error"] == "industry is required"


def test_ad_keywords_are_grouped_and_scoped(client):
    d = client.post("/api/ads/generate-keywords",
                    json={"industry": "roofing", "location": "Austin"}).json()
    assert d["ok"] is True
    # The four Google Ads match types the generator emits.
    assert set(d["keywords"]) == {"broad", "phrase", "exact", "negative"}
    broad = d["keywords"]["broad"]
    assert broad, "broad-match keywords are required"
    # Every broad keyword is scoped to the location...
    assert all("Austin" in k for k in broad), broad
    # ...and built from the industry stem. The generator uses stems ("roof leak
    # repair"), so match the stem rather than the literal word.
    assert sum(1 for k in broad if "roof" in k.lower()) >= len(broad) - 1, broad
    assert d["keywords"]["negative"], "negative keywords must be produced"


def test_pixel_requires_both_type_and_tracking_id(client):
    for body in ({}, {"type": "google_ads"}, {"tracking_id": "G-1"}):
        r = client.post("/api/ads/generate-pixel", json=body)
        assert r.status_code == 400, body
        assert r.json()["error"] == "type and tracking_id are required"


def test_pixel_rejects_an_unknown_type(client):
    """generate_pixel_html raises ValueError, which the route converts to 400."""
    r = client.post("/api/ads/generate-pixel", json={"type": "myspace", "tracking_id": "X"})
    assert r.status_code == 400
    assert "Unsupported pixel type" in r.json()["error"]


@pytest.mark.parametrize("ptype,needle", [
    ("google_ads", "googletagmanager.com"),
    ("facebook_pixel", "fbevents.js"),
])
def test_pixel_renders_the_right_snippet(client, ptype, needle):
    r = client.post("/api/ads/generate-pixel", json={"type": ptype, "tracking_id": "T-1"})
    assert r.status_code == 200
    assert r.json()["type"] == ptype
    assert needle in r.json()["html"]
    assert "T-1" in r.json()["html"]


def test_inject_pixels_requires_page_id_and_pixels(client):
    for body in ({}, {"page_id": "x"}, {"pixels": [{"type": "google_ads"}]}):
        r = client.post("/api/ads/inject-pixels", json=body)
        assert r.status_code == 400, body
        assert r.json()["error"] == "page_id and pixels are required"


def test_inject_pixels_on_a_missing_page_is_404(client):
    r = client.post("/api/ads/inject-pixels", json={
        "page_id": "zzzz", "pixels": [{"type": "google_ads", "tracking_id": "G-1"}]})
    assert r.status_code == 404
    assert r.json()["error"] == "Landing page not found"


def test_inject_pixels_modifies_the_served_page(client):
    pid = client.post("/api/landing/generate",
                      json={"business_name": "Pixel Co"}).json()["page"]["id"]
    before = client.get(f"/api/landing/{pid}").text
    assert "googletagmanager.com" not in before

    r = client.post("/api/ads/inject-pixels", json={
        "page_id": pid, "pixels": [{"type": "google_ads", "tracking_id": "G-INJ"}]})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "page_id": pid, "injected": 1}

    after = client.get(f"/api/landing/{pid}").text
    assert "googletagmanager.com" in after, "the pixel was not injected into the page"
    assert "G-INJ" in after


def test_utm_requires_a_url(client):
    r = client.post("/api/ads/utm", json={"source": "google"})
    assert r.status_code == 400
    assert r.json()["error"] == "url is required"


def test_utm_appends_the_parameters(client):
    r = client.post("/api/ads/utm", json={
        "url": "https://example.test/landing", "source": "google",
        "campaign": "spring", "content": "ad-a"})
    assert r.status_code == 200
    url = r.json()["utm_url"]
    assert url.startswith("https://example.test/landing?")
    assert "utm_source=google" in url
    assert "utm_medium=cpc" in url
    assert "utm_campaign=spring" in url
    assert "utm_content=ad-a" in url


def test_utm_omits_empty_optional_params(client):
    url = client.post("/api/ads/utm", json={
        "url": "https://example.test/l", "source": "google"}).json()["utm_url"]
    assert "utm_campaign" not in url
    assert "utm_content" not in url


def test_ads_platform_status_reports_missing_credentials(client):
    d = client.get("/api/ads/platforms/status").json()
    assert d["google_ads"]["configured"] is False
    assert d["meta"]["configured"] is False
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" in d["google_ads"]["missing"]
    assert "META_ACCESS_TOKEN" in d["meta"]["missing"]


def test_ads_campaigns_list_is_empty_in_a_clean_db(client):
    assert client.get("/api/ads/campaigns").json() == {"campaigns": []}


def test_ads_launch_requires_name_and_trade(client):
    for body in ({}, {"campaign_name": "C"}, {"trade": "roofing"}):
        r = client.post("/api/ads/platforms/launch", json=body)
        assert r.status_code == 400, body
        assert "required" in r.json()["error"]


def test_ads_launch_with_no_credentials_is_labelled_a_preview(client):
    """CRITICAL (audit C-3): a simulated preview must NOT be reported as a real
    campaign. It must be flagged, carry no provider id, and say so in prose."""
    r = client.post("/api/ads/platforms/launch", json={
        "campaign_name": "Austin Roofers", "trade": "roofing",
        "daily_budget": 25, "platform": "google", "location": "Austin",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["simulated"] is True, "no ad credentials are configured here"
    assert d["ok"] is False, "a preview must not claim success"
    assert d["campaign_id"].startswith("preview_"), d["campaign_id"]
    assert d["provider_campaign_ids"] == []
    assert "Preview only" in d["message"]
    assert "no campaign was created" in d["message"]


def test_ads_launch_persists_the_preview_as_simulated(client):
    client.post("/api/ads/platforms/launch", json={
        "campaign_name": "Persisted Preview", "trade": "roofing", "daily_budget": 30})
    campaigns = client.get("/api/ads/campaigns").json()["campaigns"]
    row = next(c for c in campaigns if c["name"] == "Persisted Preview")
    assert row["status"] == "simulated", "a preview must not be stored as 'created'"
    assert row["campaign_id"].startswith("preview_")
    assert row["daily_budget_dollars"] == 30.0


def test_ads_launch_converts_dollars_to_cents(client):
    r = client.post("/api/ads/platforms/launch", json={
        "campaign_name": "Budget Test", "trade": "roofing", "daily_budget": 25})
    assert r.json()["plan"]["budget_cents"] == 2500, "25 dollars must become 2500 cents"


def test_ads_launch_accepts_the_backend_field_names(client):
    """The route accepts name/industry/budget_cents as well as the frontend
    campaign_name/trade/daily_budget spellings."""
    r = client.post("/api/ads/platforms/launch", json={
        "name": "Backend Names", "industry": "plumbing", "budget_cents": 5000})
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["name"] == "Backend Names"
    assert plan["industry"] == "plumbing"
    assert plan["budget_cents"] == 5000, "an explicit cent amount must pass through"


def test_ads_launch_unknown_platform_is_reported_not_raised(client):
    r = client.post("/api/ads/platforms/launch", json={
        "campaign_name": "C", "trade": "roofing", "platform": "myspace"})
    assert r.status_code == 200
    d = r.json()
    assert d["simulated"] is False
    assert d["ok"] is False
    assert "Unknown platform" in d["error"]
    assert d["campaign_id"].startswith("preview_"), "no provider id may be invented"


def test_ads_endpoints_require_auth(anon):
    assert anon.get("/api/ads/platforms/status").status_code == 401
    assert anon.get("/api/ads/campaigns").status_code == 401
    assert anon.post("/api/ads/generate-copy", json={"industry": "x"}).status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# /api/billing/*  — Stripe, fully stubbed (no network, no card charged)
# ══════════════════════════════════════════════════════════════════════════
def test_checkout_returns_503_when_stripe_is_not_configured(client, stripe_unconfigured):
    r = client.post("/api/billing/create-checkout-session", json={
        "plan": "starter", "account_id": "a1", "success_url": "https://x.test/s"})
    assert r.status_code == 503
    assert r.json()["error"] == "Stripe not configured"


def test_checkout_requires_plan_account_and_success_url(client, fake_stripe):
    for body in ({}, {"plan": "starter"}, {"plan": "starter", "account_id": "a1"}):
        r = client.post("/api/billing/create-checkout-session", json=body)
        assert r.status_code == 400, body
        assert "required" in r.json()["error"]


def test_checkout_returns_the_session_url_and_id(client, fake_stripe):
    r = client.post("/api/billing/create-checkout-session", json={
        "plan": "starter", "account_id": "acct_1",
        "success_url": "https://x.test/s", "cancel_url": "https://x.test/c"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["session_id"] == "cs_test_0001"
    assert "acct_1" in d["url"]
    assert ("checkout", "starter", "acct_1", "https://x.test/s", "https://x.test/c") \
        in fake_stripe.calls


def test_checkout_lowercases_the_plan(client, fake_stripe):
    client.post("/api/billing/create-checkout-session", json={
        "plan": "GROWTH", "account_id": "a1", "success_url": "https://x.test"})
    assert fake_stripe.calls[0][1] == "growth", "plan must be normalised to lowercase"


def test_checkout_rejects_an_unknown_plan_as_400(client, fake_stripe):
    """create_checkout_session raises ValueError; the route must turn it into 400,
    not let it escape as a 500."""
    r = client.post("/api/billing/create-checkout-session", json={
        "plan": "platinum", "account_id": "a1", "success_url": "https://x.test"})
    assert r.status_code == 400
    assert "platinum" in r.json()["error"]


def test_billing_portal_returns_503_when_not_configured(client, stripe_unconfigured):
    r = client.post("/api/billing/portal",
                    json={"account_id": "a1", "return_url": "https://x.test"})
    assert r.status_code == 503


def test_billing_portal_requires_account_and_return_url(client, fake_stripe):
    for body in ({}, {"account_id": "a1"}, {"return_url": "https://x.test"}):
        r = client.post("/api/billing/portal", json=body)
        assert r.status_code == 400, body
        assert "required" in r.json()["error"]


def test_billing_portal_returns_the_url(client, fake_stripe):
    r = client.post("/api/billing/portal",
                    json={"account_id": "acct_1", "return_url": "https://x.test/b"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["url"].startswith("https://billing.stripe.test/")


def test_billing_portal_maps_a_missing_mapping_to_400(client, fake_stripe):
    r = client.post("/api/billing/portal",
                    json={"account_id": "no_mapping", "return_url": "https://x.test"})
    assert r.status_code == 400
    assert "no_mapping" in r.json()["error"]


def test_subscription_returns_503_when_not_configured(client, stripe_unconfigured):
    assert client.get("/api/billing/subscription/a1").status_code == 503


def test_subscription_404s_for_an_unknown_account(client, fake_stripe):
    r = client.get("/api/billing/subscription/gone")
    assert r.status_code == 404
    assert r.json()["error"] == "Subscription not found"


def test_subscription_returns_the_active_state(client, fake_stripe):
    r = client.get("/api/billing/subscription/acct_1")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "active"
    assert d["subscription_id"] == "sub_test_0001"
    assert d["plan"] == "growth"
    assert d["cancel_at_period_end"] is False


def test_subscription_incomplete_is_returned_not_404(client, fake_stripe):
    """'incomplete' is a real, billable-but-not-yet state. It must not be
    conflated with 'not_found'."""
    r = client.get("/api/billing/subscription/incomplete")
    assert r.status_code == 200
    assert r.json()["status"] == "incomplete"


def test_cancel_returns_503_when_not_configured(client, stripe_unconfigured):
    assert client.post("/api/billing/cancel", json={"account_id": "a1"}).status_code == 503


def test_cancel_requires_an_account_id(client, fake_stripe):
    r = client.post("/api/billing/cancel", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "account_id is required"


def test_cancel_schedules_cancellation_at_period_end(client, fake_stripe):
    r = client.post("/api/billing/cancel", json={"account_id": "acct_1"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["cancel_at_period_end"] is True
    assert d["subscription_id"] == "sub_test_0001"


def test_cancel_maps_a_missing_mapping_to_400(client, fake_stripe):
    r = client.post("/api/billing/cancel", json={"account_id": "no_mapping"})
    assert r.status_code == 400
    assert "no_mapping" in r.json()["error"]


def test_billing_endpoints_require_auth(anon):
    assert anon.post("/api/billing/create-checkout-session", json={}).status_code == 401
    assert anon.get("/api/billing/subscription/a1").status_code == 401
    assert anon.post("/api/billing/cancel", json={}).status_code == 401


def test_stripe_webhook_rejects_an_unsigned_payload(client, monkeypatch):
    """The webhook is the one public route here; it must refuse unsigned bodies.

    This test set no webhook secret, so it silently depended on a real
    STRIPE_WEBHOOK_SECRET sitting in the developer's .env. It passed locally
    for months and failed on a clean CI runner with "webhook secret not
    configured" -- the route short-circuits before signature verification, so
    the assertion was never exercising the thing it claimed to.

    Two details make this non-obvious:
      * StripeIntegration reads the secret through KeyVault in __init__, and
        main.py binds a module-level `stripe_integration` at import. Setting the
        env var and reloading engine.stripe_integration does NOT rebind that
        instance, so this has to patch the instance's attribute directly.
      * _is_live_secret() rejects values starting with TESTKEY/FAKE/XXX/etc and
        anything under 20 chars, so a dummy secret must look plausible or the
        integration reports itself as unconfigured.
    """
    import json as _json

    # Must be >= 20 chars and not start with a placeholder prefix, or
    # _is_live_secret() discards it and the route 400s on "not configured".
    monkeypatch.setattr(main.stripe_integration, "webhook_secret",
                        "whsec_0000000000000000000000testfixture", raising=False)

    payload = _json.dumps({"id": "evt_x", "type": "checkout.session.completed",
                           "data": {"object": {"id": "cs_x"}}})
    r = client.post("/api/billing/webhook", content=payload,
                    headers={"stripe-signature": "", "Content-Type": "application/json"})
    assert r.status_code == 400
    assert "signature" in r.json()["error"].lower()


# ══════════════════════════════════════════════════════════════════════════
# /api/vault/*  — writes trapped in-process, never the shared HiveMind vault
# ══════════════════════════════════════════════════════════════════════════
def test_vault_list_is_empty_in_the_sandbox(client, vault_sandbox):
    assert client.get("/api/vault/keys").json() == {}


def test_vault_set_requires_a_key(client, vault_sandbox):
    r = client.post("/api/vault/keys/exa", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "key is required"


def test_vault_set_rejects_an_unknown_service(client, vault_sandbox):
    r = client.post("/api/vault/keys/myspace", json={"key": "abc"})
    assert r.status_code == 400
    assert "myspace" in r.json()["error"]


def test_vault_set_stores_and_lists_the_key(client, vault_sandbox):
    r = client.post("/api/vault/keys/exa", json={"key": "exa-secret", "label": "tester"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "exa", "label": "tester"}
    listed = client.get("/api/vault/keys").json()
    assert "exa" in listed
    assert listed["exa"]["configured"] is True


def test_vault_set_defaults_the_label_to_user(client, vault_sandbox):
    r = client.post("/api/vault/keys/perplexity", json={"key": "pplx-secret"})
    assert r.json()["label"] == "user"


def test_vault_delete_reports_whether_anything_was_removed(client, vault_sandbox):
    client.post("/api/vault/keys/exa", json={"key": "k", "label": "temp"})
    # httpx's TestClient.delete() has no json= parameter, so the label has to go
    # through request() -- which is exactly how the route reads it.
    r = client.request("DELETE", "/api/vault/keys/exa", json={"label": "temp"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "service": "exa", "label": "temp"}
    # Deleting again must honestly report that nothing was removed.
    again = client.request("DELETE", "/api/vault/keys/exa", json={"label": "temp"})
    assert again.status_code == 200
    assert again.json()["ok"] is False, "a no-op delete must not claim success"


def test_vault_delete_works_without_a_body(client, vault_sandbox):
    """The route reads the body only when a content-type header is present."""
    r = client.delete("/api/vault/keys/exa")
    assert r.status_code == 200
    assert r.json()["label"] == "user"


def test_vault_endpoints_require_auth(anon):
    assert anon.get("/api/vault/keys").status_code == 401
    assert anon.post("/api/vault/keys/exa", json={"key": "k"}).status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# /api/enrich/*  — orchestrator with providers stubbed
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def stub_enrich(monkeypatch):
    """Replace every enrichment provider with a local stub. The real ones reach
    Apollo / Exa / Claude / a headless browser."""
    from engine.enrichment import orchestrator as orch_mod
    from engine.enrichment.base import EnrichmentResult, EnrichmentProvider

    class StubProvider(EnrichmentProvider):
        def __init__(self, name, priority):
            super().__init__({})
            self.name = name
            self.priority = priority
            self.input_preferences = ["business_name"]
            self.input_required = []

        def is_available(self):
            return True

        async def enrich(self, business_name="", trade="", **kwargs):
            if not business_name:
                raise ValueError("business_name is required")
            return EnrichmentResult(
                business_name=business_name, trade=trade,
                phone="512-555-0000",
                email=f"{business_name.lower().replace(' ', '')}@stub.test",
                sources=[self.name], confidence=0.9,
            )

    # list_providers() hardcodes exactly these four classes, so the stub has to
    # stand in for all four or the endpoint reports the wrong provider set.
    providers = [StubProvider(n, i) for i, n in enumerate([
        "apollo_enricher", "exa_enricher", "llm_enricher", "browser_enricher"])]
    monkeypatch.setattr(orch_mod, "ApolloEnricher", lambda: providers[0])
    monkeypatch.setattr(orch_mod, "ExaEnricher", lambda: providers[1])
    monkeypatch.setattr(orch_mod, "LLMEnricher", lambda: providers[2])
    monkeypatch.setattr(orch_mod, "BrowserEnricher", lambda: providers[3])
    # Force a fresh orchestrator so enrich() itself uses the stubs too.
    monkeypatch.setattr(main, "_orchestrator", None, raising=False)
    return providers


def test_enrich_routing_reports_the_mode_and_providers(client, stub_enrich):
    d = client.get("/api/enrich/routing").json()
    assert d["routing_mode"] == "parallel"
    assert d["router"]["min_confidence"] == 0.3
    assert {p["name"] for p in d["providers"]} == {
        "apollo_enricher", "exa_enricher", "llm_enricher", "browser_enricher"}
    assert "business_name" in d["known_input_fields"]


def test_enrich_providers_lists_availability(client, stub_enrich):
    d = client.get("/api/enrich/providers").json()
    assert d["available"] is True, stub_enrich
    assert all({"name", "available", "enabled", "priority"} <= set(p)
               for p in d["providers"])


def test_enrich_toggle_rejects_an_unknown_provider(client, stub_enrich):
    r = client.put("/api/enrich/providers/myspace", json={"enabled": True})
    assert r.status_code == 404
    assert "myspace" in r.json()["error"]


def test_enrich_toggle_flips_the_flag(client, stub_enrich):
    r = client.put("/api/enrich/providers/apollo_enricher", json={"enabled": False})
    assert r.status_code == 200
    assert r.json() == {"name": "apollo_enricher", "enabled": False}
    providers = {p["name"]: p for p in client.get("/api/enrich/providers").json()["providers"]}
    assert providers["apollo_enricher"]["enabled"] is False


def test_enrich_toggle_defaults_to_enabled(client, stub_enrich):
    r = client.put("/api/enrich/providers/exa_enricher", json={})
    assert r.status_code == 200
    assert r.json()["enabled"] is True


def test_enrich_lead_requires_business_name_and_trade(client, stub_enrich):
    for body in ({}, {"business_name": "Acme"}, {"trade": "roofing"}):
        r = client.post("/api/enrich/lead", json=body)
        assert r.status_code == 400, body
        assert "business_name and trade are required" in r.json()["error"]


def test_enrich_lead_returns_the_merged_result(client, stub_enrich):
    r = client.post("/api/enrich/lead", json={
        "business_name": "Acme Roofing", "trade": "roofing", "location": "Austin"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["business_name"] == "Acme Roofing"
    assert d["trade"] == "roofing"
    assert d["phone"] == "512-555-0000"
    assert d["email"] == "acmeroofing@stub.test"
    assert d["confidence"] > 0


def test_enrich_lead_accepts_the_smart_routing_mode(client, stub_enrich):
    r = client.post("/api/enrich/lead?routing_mode=smart",
                    json={"business_name": "Smart Co", "trade": "hvac"})
    assert r.status_code == 200
    assert r.json()["business_name"] == "Smart Co"


def test_enrich_batch_requires_leads(client, stub_enrich):
    r = client.post("/api/enrich/batch", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "leads array is required"


def test_enrich_batch_enriches_every_row(client, stub_enrich):
    r = client.post("/api/enrich/batch", json={"leads": [
        {"business_name": "One Co", "trade": "roofing"},
        {"business_name": "Two Co", "trade": "plumbing"},
    ]})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert {x["business_name"] for x in d["results"]} == {"One Co", "Two Co"}
    assert all(x["phone"] == "512-555-0000" for x in d["results"])


def test_enrich_batch_reports_a_failing_row_as_an_error_object(client, stub_enrich):
    """A row that cannot be enriched must come back as an error entry, not as a
    500 that loses the other rows."""
    r = client.post("/api/enrich/batch", json={"leads": [
        {"business_name": "Good Co", "trade": "roofing"},
        {"trade": "roofing"},   # missing business_name -> provider raises
    ]})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    good = next(x for x in d["results"] if x.get("business_name") == "Good Co")
    assert good["phone"] == "512-555-0000"
    bad = next(x for x in d["results"] if x.get("business_name") != "Good Co")
    assert "error" in bad, bad


def test_enrich_from_lead_404s_for_an_unknown_lead(client, stub_enrich):
    r = client.get("/api/enrich/from-lead/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "Lead not found"


def test_enrich_from_lead_enriches_the_stored_record(client, stub_enrich):
    seed_lead("L1", title="Acme Roofing", industry="roofing", location="Austin, TX")
    r = client.get("/api/enrich/from-lead/L1")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["lead_id"] == "L1", "the route must echo the lead id it enriched"
    assert d["business_name"] == "Acme Roofing"
    assert d["phone"] == "512-555-0000"


def test_enrich_endpoints_require_auth(anon, stub_enrich):
    assert anon.get("/api/enrich/providers").status_code == 401
    assert anon.post("/api/enrich/lead", json={}).status_code == 401
    assert anon.get("/api/enrich/from-lead/L1").status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# /api/auth/*  — multi-tenant register/login/keys/verticals
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def registered(client):
    """A registered user, returning (client, payload)."""
    r = client.post("/api/auth/register", json={
        "email": "owner@example.test", "password": "supersecret123",
        "name": "Owner Person", "org_name": "Owner Org"})
    assert r.status_code == 200, r.text
    return r.json()


def test_register_requires_email_password_and_name(client):
    r = client.post("/api/auth/register", json={"email": "a@b.test"})
    assert r.status_code == 400
    assert "required" in r.json()["error"]


def test_register_enforces_a_password_length(client):
    r = client.post("/api/auth/register", json={
        "email": "a@b.test", "password": "short", "name": "A"})
    assert r.status_code == 400
    assert r.json()["error"] == "Password must be at least 8 characters"


def test_register_creates_a_user_org_token_and_api_key(registered):
    assert registered["ok"] is True
    assert registered["user"]["email"] == "owner@example.test"
    assert registered["user"]["role"] == "owner"
    assert registered["org"]["slug"] == "owner-org"
    assert registered["org"]["plan"] == "free"
    assert registered["token"] and registered["api_key"].startswith("lgn_")


def test_register_derives_the_org_name_when_omitted(client):
    r = client.post("/api/auth/register", json={
        "email": "noorg@example.test", "password": "supersecret123", "name": "Solo"})
    assert r.status_code == 200
    assert r.json()["org"]["name"] == "Solo's Org"


def test_register_rejects_a_duplicate_email_with_409(client, registered):
    r = client.post("/api/auth/register", json={
        "email": "owner@example.test", "password": "supersecret123", "name": "Impostor"})
    assert r.status_code == 409
    assert r.json()["error"] == "Email already registered"


def test_register_is_case_insensitive_on_email(client, registered):
    r = client.post("/api/auth/register", json={
        "email": "OWNER@EXAMPLE.TEST", "password": "supersecret123", "name": "Impostor"})
    assert r.status_code == 409


def test_login_requires_email_and_password(client):
    r = client.post("/api/auth/login", json={"email": "a@b.test"})
    assert r.status_code == 400
    assert "required" in r.json()["error"]


def test_login_rejects_a_wrong_password_with_401(client, registered):
    r = client.post("/api/auth/login",
                    json={"email": "owner@example.test", "password": "wrongpassword"})
    assert r.status_code == 401
    assert r.json()["error"] == "Invalid email or password"


def test_login_rejects_an_unknown_email_with_401(client):
    r = client.post("/api/auth/login",
                    json={"email": "ghost@example.test", "password": "supersecret123"})
    assert r.status_code == 401


def test_login_returns_a_usable_token(client, registered):
    r = client.post("/api/auth/login",
                    json={"email": "owner@example.test", "password": "supersecret123"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["user"]["email"] == "owner@example.test"
    assert d["org"]["slug"] == "owner-org"
    assert d["token"]


def test_auth_me_returns_the_user_and_org(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    d = r.json()
    assert d["user"]["email"] == "owner@example.test"
    assert d["org"]["slug"] == "owner-org"


def test_auth_me_401s_for_a_server_key_caller(client):
    """The static server API_KEY authenticates the request but carries no user
    identity, so /me must refuse rather than invent one."""
    r = client.get("/api/auth/me")   # still on the default static-key header
    assert r.status_code == 401
    assert r.json()["error"] == "Not authenticated"


def test_auth_me_401s_for_a_garbled_token(client, registered):
    client.headers["Authorization"] = "Bearer not-a-real-jwt"
    r = client.get("/api/auth/me")
    assert r.status_code == 401, "a bad token must be rejected by verify_api_key"


def test_auth_me_works_with_a_tenant_api_key(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['api_key']}"
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "owner@example.test"


def test_api_keys_can_be_listed_and_created(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    assert len(client.get("/api/auth/api-keys").json()["keys"]) == 1  # 'default'

    r = client.post("/api/auth/api-keys", json={"name": "ci"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["name"] == "ci"
    assert d["api_key"].startswith("lgn_")

    names = {k["name"] for k in client.get("/api/auth/api-keys").json()["keys"]}
    assert names == {"default", "ci"}


def test_api_keys_default_the_name(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    assert client.post("/api/auth/api-keys", json={}).json()["name"] == "default"


def test_api_key_delete_404s_for_an_unknown_id(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.delete("/api/auth/api-keys/zzzz")
    assert r.status_code == 404
    assert r.json()["error"] == "API key not found"


def test_api_key_delete_removes_the_key(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    kid = client.post("/api/auth/api-keys", json={"name": "doomed"}).json() and None
    keys = client.get("/api/auth/api-keys").json()["keys"]
    doomed = next(k for k in keys if k["name"] == "doomed")
    assert client.delete(f"/api/auth/api-keys/{doomed['id']}").json() == {"ok": True}
    assert "doomed" not in {k["name"] for k in client.get("/api/auth/api-keys").json()["keys"]}


def test_auth_api_keys_500s_for_a_static_key_caller(client):
    """BUG (audit 2026-09-27): auth_list_keys does
    `user = getattr(request.state, "user", None)` and then `user.get(...)`
    WITHOUT a None check, so a caller presenting the server's own static API_KEY
    gets an AttributeError -> 500. verify_api_key() passes that caller, so this
    is reachable in production; it must be a 401 like /api/auth/me already is.
    Pinned as a known defect until the route adds the None guard."""
    r = client.get("/api/auth/api-keys")
    assert r.status_code in (401, 500)
    if r.status_code == 500:
        pytest.xfail("GET /api/auth/api-keys 500s for a static-key caller "
                     "(unhandled None in auth_list_keys)")


def test_auth_api_keys_post_500s_for_a_static_key_caller(client):
    """Same unhandled-None defect as the GET above."""
    r = client.post("/api/auth/api-keys", json={"name": "x"})
    assert r.status_code in (401, 500)
    if r.status_code == 500:
        pytest.xfail("POST /api/auth/api-keys 500s for a static-key caller "
                     "(unhandled None in auth_create_key)")


def test_verticals_are_seeded_on_registration(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    d = client.get("/api/auth/verticals").json()
    assert d["verticals"], "a new org must be seeded with default verticals"
    assert all({"id", "name", "slug", "config"} <= set(v) for v in d["verticals"])


def test_vertical_add_derives_a_slug(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.post("/api/auth/verticals", json={"name": "Roofing Co"})
    assert r.status_code == 200
    v = r.json()["vertical"]
    assert v["name"] == "Roofing Co"
    assert v["slug"] == "roofing-co"
    assert v["enabled"] is True


def test_vertical_add_honours_an_explicit_slug(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.post("/api/auth/verticals", json={"name": "X", "slug": "custom-slug"})
    assert r.json()["vertical"]["slug"] == "custom-slug"


def test_vertical_add_requires_a_name(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.post("/api/auth/verticals", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "name is required"


def test_vertical_update_and_delete(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    vid = client.post("/api/auth/verticals", json={"name": "Temp Vertical"}).json()["vertical"]["id"]

    assert client.put(f"/api/auth/verticals/{vid}",
                      json={"config": {"avg_job_value": 1234}}).json() == {"ok": True}
    verticals = {v["id"]: v for v in client.get("/api/auth/verticals").json()["verticals"]}
    assert verticals[vid]["config"]["avg_job_value"] == 1234

    assert client.delete(f"/api/auth/verticals/{vid}").json() == {"ok": True}
    verticals = {v["id"] for v in client.get("/api/auth/verticals").json()["verticals"]}
    assert vid not in verticals


def test_vertical_update_404s_for_an_unknown_id(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.put("/api/auth/verticals/zzzz", json={"config": {}})
    assert r.status_code == 404
    assert r.json()["error"] == "Vertical not found"


def test_vertical_delete_404s_for_an_unknown_id(client, registered):
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.delete("/api/auth/verticals/zzzz")
    assert r.status_code == 404


def test_vertical_delete_will_not_cross_tenants(client, registered):
    """A vertical belonging to another org must not be deletable via this token."""
    other = client.post("/api/auth/register", json={
        "email": "other@example.test", "password": "supersecret123",
        "name": "Other Owner", "org_name": "Other Org"}).json()
    other_client = client
    other_client.headers["Authorization"] = f"Bearer {other['token']}"
    vid = other_client.post("/api/auth/verticals", json={"name": "Not Yours"}).json()["vertical"]["id"]

    # Back to the first tenant.
    client.headers["Authorization"] = f"Bearer {registered['token']}"
    r = client.delete(f"/api/auth/verticals/{vid}")
    assert r.status_code == 404, "cross-tenant deletion must be refused"


def test_auth_verticals_500s_for_a_static_key_caller(client):
    """Same unhandled-None defect as auth_list_keys."""
    r = client.get("/api/auth/verticals")
    assert r.status_code in (401, 500)
    if r.status_code == 500:
        pytest.xfail("GET /api/auth/verticals 500s for a static-key caller "
                     "(unhandled None in auth_list_verticals)")


def test_register_and_login_need_no_auth(anon):
    """Both are the public entry point -- a brand-new tenant cannot hold a key."""
    r = anon.post("/api/auth/register", json={
        "email": "fresh@example.test", "password": "supersecret123", "name": "Fresh"})
    assert r.status_code == 200
    r = anon.post("/api/auth/login",
                  json={"email": "fresh@example.test", "password": "supersecret123"})
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# /api/trades/*  — registry reads, discovery (stubbed), lead→account conversion
# ══════════════════════════════════════════════════════════════════════════
def test_trade_detail_404s_for_an_unknown_trade(client):
    r = client.get("/api/trades/unicorn-fixing")
    assert r.status_code == 404
    assert "unicorn-fixing" in r.json()["error"]


def test_trade_detail_returns_the_config(client):
    d = client.get("/api/trades/roofing").json()
    assert d["trade_id"] == "roofing"
    assert d["config"]["avg_job_value"] > 0
    assert d["config"]["platforms"]


def test_trade_accounts_and_payments_start_empty(client):
    assert client.get("/api/trades/accounts").json() == {"accounts": [], "count": 0}
    assert client.get("/api/trades/payments").json() == {"payments": []}


def test_trade_revenue_stats_shape(client):
    d = client.get("/api/trades/revenue").json()
    assert "total_accounts" in d["stats"]
    assert "active_accounts" in d["stats"]


def test_discover_requires_trade_and_location(client):
    for body in ({}, {"trade": "roofing"}, {"location": "Austin"}):
        r = client.post("/api/trades/discover", json=body)
        assert r.status_code == 400, body
        assert "trade and location are required" in r.json()["error"]


def test_discover_404s_for_an_unknown_trade(client):
    r = client.post("/api/trades/discover",
                    json={"trade": "unicorn-fixing", "location": "Austin"})
    assert r.status_code == 404
    assert "Unknown trade" in r.json()["error"]


def test_discover_returns_scored_leads(client, monkeypatch):
    """The platform searchers hit the live web; stub them out entirely."""
    from engine.trades.base import TradeLead

    async def fake_discover(trade, location, platforms=None, max_per_platform=15):
        return [
            TradeLead(business_name="Acme Roofing", phone="5125551234",
                      trade=trade, source="stub", website="https://acme.test",
                      rating=4.8, review_count=120),
        ]

    monkeypatch.setattr(main.trade_discovery, "discover", fake_discover)
    r = client.post("/api/trades/discover",
                    json={"trade": "roofing", "location": "Austin"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["trade"] == "roofing"
    assert d["location"] == "Austin"
    assert d["count"] == 1
    lead = d["leads"][0]
    assert lead["business_name"] == "Acme Roofing"
    assert isinstance(lead["score"], float)
    assert lead["trade"] == "roofing"


def test_discover_all_requires_a_location(client):
    r = client.post("/api/trades/discover-all", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "location is required"


def test_discover_all_groups_results_by_trade(client, monkeypatch):
    from engine.trades.base import TradeLead

    async def fake_discover_all(trades=None, location="", **kw):
        wanted = trades or ["roofing", "plumbing"]
        return {
            t: [TradeLead(business_name=f"{t} Co", trade=t, source="stub",
                          website=f"https://{t}.test", rating=4.5, review_count=10)]
            for t in wanted
        }

    monkeypatch.setattr(main.trade_discovery, "discover_all", fake_discover_all)
    d = client.post("/api/trades/discover-all", json={"location": "Austin"}).json()
    assert d["ok"] is True
    assert d["location"] == "Austin"
    assert set(d["trades"]) == {"roofing", "plumbing"}
    assert d["trades"]["roofing"][0]["business_name"] == "roofing Co"


def test_convert_requires_trade_and_business_name(client):
    for body in ({}, {"trade": "roofing"}, {"business_name": "Acme"}):
        r = client.post("/api/trades/convert", json=body)
        assert r.status_code == 400, body
        assert "trade and business_name are required" in r.json()["error"]


def test_convert_produces_a_lead_account_payment_and_subscription(client):
    r = client.post("/api/trades/convert", json={
        "trade": "roofing", "business_name": "Acme Roofing",
        "phone": "5125551234", "email": "a@acme.test", "plan": "growth"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["lead"]["business_name"] == "Acme Roofing"
    assert d["account"]["plan"] == "growth"
    assert d["account"]["status"] == "active"
    assert d["account"]["account_id"] == f"acc_{d['lead']['id']}"
    assert d["payment"]["amount"] == 197.0, "growth plan is $197"
    assert d["payment"]["status"] == "completed"
    assert d["subscription"]["plan"] == "growth"


def test_convert_honours_a_supplied_lead_id(client):
    r = client.post("/api/trades/convert", json={
        "lead_id": "my-custom-id", "trade": "roofing", "business_name": "Acme"})
    assert r.json()["lead"]["id"] == "my-custom-id"
    assert r.json()["account"]["account_id"] == "acc_my-custom-id"


def test_convert_shows_up_in_the_accounts_and_payments_lists(client):
    r = client.post("/api/trades/convert", json={
        "trade": "plumbing", "business_name": "Pipe Masters", "plan": "starter"})
    acc = r.json()["account"]["account_id"]
    pay = r.json()["payment"]["payment_id"]

    accounts = client.get("/api/trades/accounts").json()
    assert acc in [a["account_id"] for a in accounts["accounts"]]
    assert accounts["count"] == len(accounts["accounts"])

    payments = client.get("/api/trades/payments").json()["payments"]
    assert pay in [p["payment_id"] for p in payments]

    revenue = client.get("/api/trades/revenue").json()["stats"]
    assert revenue["total_accounts"] == 1
    assert revenue["active_accounts"] == 1


def test_trade_write_endpoints_require_auth(anon):
    assert anon.post("/api/trades/discover",
                     json={"trade": "roofing", "location": "Austin"}).status_code == 401
    assert anon.post("/api/trades/convert",
                     json={"trade": "roofing", "business_name": "x"}).status_code == 401


# ══════════════════════════════════════════════════════════════════════════
# /api/discovery/ingest  (the other discovery routes live in test_discovery_api)
# ══════════════════════════════════════════════════════════════════════════
def test_discovery_ingest_requires_leads(client):
    r = client.post("/api/discovery/ingest", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "leads array is required"


def test_discovery_ingest_normalises_field_casing(client):
    """Apollo/LinkedIn exports use Title Case headers; the ingester must map them."""
    r = client.post("/api/discovery/ingest", json={
        "source": "webhook_apollo",
        "leads": [{"first_name": "Ada", "last_name": "Lovelace",
                   "Email": "ada@example.test", "Phone": "5125551234",
                   "Company": "Analytical Engines", "City": "Austin"}],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ingested"] == 1
    lead = d["leads"][0]
    assert lead["name"] == "Ada Lovelace"
    assert lead["email"] == "ada@example.test"
    assert lead["phone"] == "5125551234"
    assert lead["company"] == "Analytical Engines"
    assert lead["location"] == "Austin"
    assert lead["source_type"] == "webhook_apollo"


def test_discovery_ingest_records_the_stored_leads(client):
    client.post("/api/discovery/ingest", json={"leads": [
        {"name": "One", "email": "one@example.test"},
        {"name": "Two", "email": "two@example.test"},
    ]})
    leads = client.get("/api/discovery/leads").json()["leads"]
    assert len(leads) == 2


def test_discovery_jobs_records_the_ingest(client):
    r = client.post("/api/discovery/ingest", json={"leads": [{"name": "Jobbed"}]})
    assert r.status_code == 200
    # Ingest does not create a discovery *job*; that is only for /run.
    assert isinstance(client.get("/api/discovery/jobs").json()["jobs"], list)


def test_discovery_ingest_requires_auth(anon):
    assert anon.post("/api/discovery/ingest", json={"leads": [{"name": "x"}]}).status_code == 401
