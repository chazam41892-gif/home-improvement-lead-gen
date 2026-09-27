"""Tests for the Leviathan Growth portal (audit 2026-09-27).

`portal.py` serves the whole subscription funnel: public pages, session auth,
the module paywall, Stripe hand-off, a public lead-capture form, and the
Google OAuth callback. These run the real ASGI app against a throwaway SQLite
file and a `TestClient`, and assert exact status codes, redirect targets, and
the exact rows that land in the database.

Read from the implementation before asserting — several of these are
deliberate, easy-to-get-wrong behaviours:

  * `_require_user` raises `HTTPException(401)`, which the app's exception
    handler renders as `{"error": ..., "code": ...}` (not FastAPI's default
    `{"detail": ...}`).
  * `module_landing` redirects anonymous visitors to `/growth/login?next=...`
    but signed-in users below the tier to `/growth/profile?next=...`.
  * `api_login` and `google_callback` both re-anchor a `next`/`state` that does
    not start with `/growth/` back to `/growth/`, so neither is an open
    redirect.
  * `api_capture` writes a `leads` row with `score=0`, `score_breakdown="{}"`,
    a description truncated to 300 chars, and a location joined as
    `"{city}, {state} {zip}"` with the separator characters stripped.
  * `KeyVault` on this machine resolves real-looking values, so every Stripe
    and Google path here patches the vault rather than trusting what is
    installed.
"""
import json
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import main
from engine.database import Database
from engine.auth import auth_manager
from engine.growth_portal import portal as portal_mod
from engine.growth_portal import modules as modules_mod

GOOD_PASSWORD = "portal-test-pw"

# The four tiers the profile page sells, with the prices it renders.
PRICES = {"starter": "$97/mo", "growth": "$197/mo", "pro": "$497/mo",
          "enterprise": "$997/mo"}


# ── fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(Database, "db_file", str(tmp_path / "portal.db"))
    Database.initialize()
    auth_manager._ensure_tables()
    return Database


@pytest.fixture
def client(db):
    # No lifespan context manager: the portal routes do not depend on the
    # scheduler, and this keeps threads out of the test run.
    return TestClient(main.app)


@pytest.fixture
def anon(client):
    """A client with no session at all."""
    client.cookies.clear()
    return client


@pytest.fixture
def registry():
    before = dict(modules_mod.MODULE_REGISTRY)
    leadgen = modules_mod.MODULE_REGISTRY["leadgen"]
    saved = (leadgen.min_plan, leadgen.access_check, list(leadgen.tags))
    yield modules_mod.MODULE_REGISTRY
    modules_mod.MODULE_REGISTRY.clear()
    modules_mod.MODULE_REGISTRY.update(before)
    leadgen.min_plan, leadgen.access_check, tags = saved
    leadgen.tags[:] = tags


@pytest.fixture
def user(client, db):
    """Register an org owner and leave the client holding their session cookie."""
    r = client.post("/growth/api/register", json={
        "email": "owner@example.com", "password": GOOD_PASSWORD,
        "name": "Olive Owner", "org_name": "Olive Roofing"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    return auth_manager.get_user_by_email("owner@example.com")


def set_plan(user, plan):
    with Database.get_connection() as conn:
        conn.execute("UPDATE orgs SET plan = ? WHERE id = ?", (plan, user["org_id"]))
        conn.commit()


def lead_row(lead_id):
    with Database.get_connection() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def nurture_rows():
    with Database.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM nurture_sequences ORDER BY rowid")]


class FakeStripe:
    """Stands in for StripeIntegration so no checkout session is ever created."""
    is_configured = True
    calls: list = []

    async def create_checkout_session(self, plan, account_id, success_url, cancel_url):
        FakeStripe.calls.append({"kind": "checkout", "plan": plan,
                                 "account_id": account_id,
                                 "success_url": success_url,
                                 "cancel_url": cancel_url})
        return {"url": "https://checkout.stripe.test/c/session"}

    async def create_billing_portal(self, account_id, return_url):
        FakeStripe.calls.append({"kind": "portal", "account_id": account_id,
                                 "return_url": return_url})
        return {"url": "https://billing.stripe.test/session"}


@pytest.fixture
def stripe(monkeypatch):
    FakeStripe.calls = []
    monkeypatch.setattr(portal_mod, "StripeIntegration", FakeStripe)
    return FakeStripe


class UnconfiguredStripe:
    is_configured = False


@pytest.fixture
def no_stripe(monkeypatch):
    monkeypatch.setattr(portal_mod, "StripeIntegration", UnconfiguredStripe)


# ── the HTML shell ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,title", [
    ("/growth/", "Growth Portal"),
    ("/growth/login", "Login"),
    ("/growth/register", "Create account"),
    ("/growth/thank-you", "Thank you"),
])
def test_public_pages_serve_a_complete_html_document(anon, path, title):
    r = anon.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.startswith("<!DOCTYPE html>")
    assert r.text.rstrip().endswith("</html>")
    assert f"<title>{title} — Leviathan Growth</title>" in r.text
    assert "tailwindcss@2.2.19" in r.text
    assert '<body class="bg-gray-900 text-white">' in r.text


def test_the_thank_you_page_confirms_receipt(anon):
    r = anon.get("/growth/thank-you")
    assert "Lead received" in r.text
    assert 'href="/growth"' in r.text


# ── the catalog home ───────────────────────────────────────────────────────
def test_the_catalog_lists_every_registered_module(anon):
    r = anon.get("/growth/")
    assert r.status_code == 200
    for module in modules_mod.list_modules():
        assert module["name"] in r.text
        assert f'href="/growth/module/{module["slug"]}"' in r.text
        for tag in module["tags"]:
            assert f">{tag}</span>" in r.text


def test_an_anonymous_visitor_is_locked_out_of_a_paid_module(anon):
    """The default plan is `free`; leadgen needs `starter`."""
    r = anon.get("/growth/")
    assert "Subscribe from Starter" in r.text
    assert "Open Module" not in r.text
    assert "bg-blue-600 hover:bg-blue-700" in r.text


def test_a_free_visitor_is_offered_a_login_and_signup(anon):
    r = anon.get("/growth/")
    assert 'href="/growth/login"' in r.text
    assert "Create free account" in r.text
    assert "Logout" not in r.text


def test_a_paying_visitor_sees_the_open_cta_and_their_plan(client, user):
    set_plan(user, "starter")
    r = client.get("/growth/")
    assert "Open Module" in r.text
    assert "Subscribe from Starter" not in r.text
    assert "bg-emerald-500 hover:bg-emerald-600 text-white px-4 py-2 rounded font-semibold" in r.text


def test_a_signed_in_visitor_sees_their_name_and_plan_in_the_header(client, user):
    set_plan(user, "growth")
    r = client.get("/growth/")
    assert "Olive Owner — Growth" in r.text, "name and capitalised plan"
    assert 'href="/growth/profile"' in r.text
    assert 'href="/growth/logout"' in r.text


def test_an_unknown_plan_on_the_org_row_degrades_to_the_free_cta(client, user):
    set_plan(user, "not-a-real-plan")
    r = client.get("/growth/")
    assert "Subscribe from Starter" in r.text
    assert "— Not-A-Real-Plan" not in r.text


def test_the_cta_names_the_tier_actually_required(anon, registry):
    registry["leadgen"].min_plan = "enterprise"
    r = anon.get("/growth/")
    assert "Subscribe from Enterprise" in r.text


def test_an_empty_catalog_renders_a_placeholder_instead_of_a_broken_grid(anon, registry):
    registry.clear()
    r = anon.get("/growth/")
    assert r.status_code == 200
    assert "No modules available yet." in r.text
    assert 'class="grid md:grid-cols-2 lg:grid-cols-3 gap-6"' in r.text


# ── registration / login / logout ──────────────────────────────────────────
def test_registering_creates_an_owner_on_a_free_plan_and_starts_a_session(client, db):
    r = client.post("/growth/api/register", json={
        "email": "New@Example.com", "password": GOOD_PASSWORD,
        "name": "Nina New", "org_name": "New Nest"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile"
    assert "growth_token" in r.cookies

    created = auth_manager.get_user_by_email("new@example.com")
    assert created["name"] == "Nina New", "email is normalised to lower case"
    org = auth_manager.get_org(created["org_id"])
    assert org["name"] == "New Nest"
    assert org["plan"] == "free"
    assert created["role"] == "owner"


def test_the_session_cookie_is_httponly_lax_and_expires_in_seven_days(client, db):
    r = client.post("/growth/api/register", json={
        "email": "ck@example.com", "password": GOOD_PASSWORD,
        "name": "C K", "org_name": "CK"}, follow_redirects=False)
    header = r.headers["set-cookie"]
    assert "growth_token=" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Max-Age=604800" in header, "7 days in seconds"
    assert r.cookies["growth_token"]


def test_registering_the_same_email_twice_is_rejected_with_400(client, db):
    body = {"email": "dupe@example.com", "password": GOOD_PASSWORD,
            "name": "D", "org_name": "DCo"}
    first = client.post("/growth/api/register", json=body, follow_redirects=False)
    assert first.status_code == 302
    r = client.post("/growth/api/register", json=body)
    assert r.status_code == 400
    assert r.json()["error"] == "Email already registered"


def test_the_html_register_form_works_end_to_end(anon, db):
    """The real page posts urlencoded form data, not JSON."""
    anon.cookies.clear()
    r = anon.post("/growth/api/register", data={
        "email": "form@example.com", "password": GOOD_PASSWORD,
        "name": "Form User", "org_name": "Form Co"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile"
    assert auth_manager.get_user_by_email("form@example.com") is not None


def test_registering_without_a_next_parameter_lands_on_the_profile(client, db):
    r = client.post("/growth/api/register", data={}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile"


def test_logging_in_with_the_right_password_returns_the_token(client, user):
    client.cookies.clear()
    r = client.post("/growth/api/login", json={
        "email": "owner@example.com", "password": GOOD_PASSWORD}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/"
    assert "growth_token" in r.cookies


def test_logging_in_with_a_wrong_password_is_a_401(client, user):
    client.cookies.clear()
    r = client.post("/growth/api/login", json={
        "email": "owner@example.com", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json() == {"error": "Invalid email or password", "code": 401}


def test_logging_in_as_an_unknown_email_is_a_401_and_leaks_nothing(client, db):
    client.cookies.clear()
    r = client.post("/growth/api/login", json={
        "email": "ghost@example.com", "password": GOOD_PASSWORD})
    assert r.status_code == 401
    assert "not found" not in r.text.lower(), "must not distinguish unknown user"
    assert "growth_token" not in r.cookies


def test_a_logged_in_login_redirects_to_the_requested_next_page(client, user):
    client.cookies.clear()
    r = client.post("/growth/api/login?next=/growth/module/leadgen", json={
        "email": "owner@example.com", "password": GOOD_PASSWORD}, follow_redirects=False)
    assert r.headers["location"] == "/growth/module/leadgen"


@pytest.mark.parametrize("hostile", [
    "https://evil.example/steal",
    "http://evil.example/steal",
    "//evil.example/steal",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "/admin",
    "",
])
def test_a_login_next_pointing_off_site_is_re_anchored_to_the_portal(client, user, hostile):
    """An absolute or scheme-ful attacker URL must not become the destination."""
    client.cookies.clear()
    r = client.post("/growth/api/login?next=" + urllib.parse.quote(hostile), json={
        "email": "owner@example.com", "password": GOOD_PASSWORD},
        follow_redirects=False)
    assert r.headers["location"] == "/growth/", hostile


def test_a_relative_traversal_still_under_the_prefix_stays_on_site(client, user):
    """The guard is a `/growth/` prefix test, so `/growth/../x` is allowed.

    That is same-origin, so it is not an open redirect — pinned here so the
    guard's actual shape is documented rather than overstated.
    """
    client.cookies.clear()
    r = client.post("/growth/api/login?next=/growth/../admin", json={
        "email": "owner@example.com", "password": GOOD_PASSWORD},
        follow_redirects=False)
    assert r.headers["location"] == "/growth/../admin"
    assert not r.headers["location"].startswith(("http://", "https://", "//"))


def test_the_login_form_carries_next_into_both_the_form_and_the_google_link(anon):
    r = anon.get("/growth/login?next=/growth/profile")
    assert 'action="/growth/api/login?next=/growth/profile"' in r.text
    assert "/growth/auth/google/login?next=/growth/profile" in r.text
    assert "/growth/register?next=/growth/profile" in r.text


def test_the_login_and_register_pages_default_next_to_the_portal_root(anon):
    default = urllib.parse.quote("/growth/")
    assert f"/growth/api/login?next={default}" in anon.get("/growth/login").text
    assert f"/growth/auth/google/login?next={default}" in anon.get("/growth/register").text


def test_a_next_parameter_cannot_inject_markup_into_the_login_page(anon):
    r = anon.get("/growth/login?next=" + urllib.parse.quote('/growth/"><script>x</script>'))
    assert r.status_code == 200
    assert "<script>x</script>" not in r.text, "next must be percent-encoded, not raw"
    assert "%3Cscript%3E" in r.text


def test_the_register_page_and_its_google_link_agree_on_next(anon):
    r = anon.get("/growth/register?next=/growth/profile")
    assert "/growth/auth/google/login?next=/growth/profile" in r.text
    assert 'action="/growth/api/register"' in r.text


def test_logout_clears_the_cookie_and_returns_to_the_portal(client, user):
    assert client.get("/growth/api/me").status_code == 200
    r = client.get("/growth/logout", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/"
    header = r.headers["set-cookie"]
    assert "growth_token=" in header
    assert "Max-Age=0" in header, "the cookie must be expired, not merely unset"
    assert client.get("/growth/api/me").status_code == 401


# ── session enforcement ────────────────────────────────────────────────────
@pytest.mark.parametrize("method,path,body", [
    ("GET", "/growth/profile", None),
    ("GET", "/growth/api/me", None),
    ("GET", "/growth/api/billing-portal", None),
    ("POST", "/growth/api/subscribe", {"plan": "starter"}),
])
def test_protected_routes_reject_an_anonymous_visitor(anon, method, path, body):
    r = anon.request(method, path, json=body)
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized", "code": 401}


def test_a_garbage_session_cookie_is_treated_as_signed_out(anon):
    anon.cookies.set("growth_token", "not.a.real.jwt")
    r = anon.get("/growth/api/me")
    assert r.status_code == 401


def test_a_valid_token_for_a_deleted_user_is_treated_as_signed_out(anon, db):
    """A JWT survives its user; the user lookup must not."""
    ghost = auth_manager._create_jwt("no-such-user-id", "no-such-org", "g@x.com", "owner")
    anon.cookies.set("growth_token", ghost)
    assert anon.get("/growth/api/me").status_code == 401
    # ...and the public catalog still renders for the broken session.
    assert anon.get("/growth/").status_code == 200


def test_api_me_returns_the_user_and_org_rows(client, user):
    set_plan(user, "pro")
    body = client.get("/growth/api/me").json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["user"]["name"] == "Olive Owner"
    assert body["org"]["name"] == "Olive Roofing"
    assert body["org"]["plan"] == "pro"
    assert "password_hash" not in body["user"], "never serialise the hash"
    assert body["user"]["org_id"] == body["org"]["id"]


def test_the_modules_api_flags_access_for_the_signed_in_plan(anon, client, user):
    """Anonymous -> free -> locked; starter -> open."""
    body = anon.get("/growth/api/modules").json()
    assert len(body) == len(modules_mod.list_modules())
    assert body[0]["id"] == "leadgen"
    assert body[0]["access"] is False
    assert set(body[0]) == set(modules_mod.list_modules()[0]) | {"access"}

    set_plan(user, "starter")
    body = client.get("/growth/api/modules").json()
    assert body[0]["access"] is True


# ── the module paywall ─────────────────────────────────────────────────────
def test_an_anonymous_visitor_is_sent_to_login_with_a_next(client):
    r = client.get("/growth/module/leadgen", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/login?next=/growth/module/leadgen"


def test_a_visitor_below_the_required_tier_is_sent_to_the_pricing_page(client, user):
    set_plan(user, "free")
    r = client.get("/growth/module/leadgen", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile?next=/growth/module/leadgen"


def test_a_paying_visitor_reaches_the_leadgen_workspace(client, user):
    set_plan(user, "starter")
    r = client.get("/growth/module/leadgen")
    assert r.status_code == 200
    assert "Find developers who buy land" in r.text
    assert "Lead Gen Pro" in r.text
    assert 'id="search-form"' in r.text
    assert 'action="/growth/api/capture"' in r.text
    assert 'value="growth_portal_leadgen"' in r.text
    assert "Olive Owner" in r.text


def test_the_leadgen_workspace_offers_the_trade_dropdown_it_promises(client, user):
    set_plan(user, "starter")
    text = client.get("/growth/module/leadgen").text
    for value in ("land_developer", "general_contracting", "roofing", "hvac", "plumbing"):
        assert f'value="{value}"' in text


def test_the_leadgen_workspace_wires_its_search_to_the_real_api(client, user):
    set_plan(user, "starter")
    text = client.get("/growth/module/leadgen").text
    assert "fetch('/api/scout/search'" in text
    assert "num_results:10" in text


def test_a_module_slug_that_does_not_exist_is_a_404(client):
    r = client.get("/growth/module/not-a-real-module")
    assert r.status_code == 404
    assert r.json() == {"error": "Module not found", "code": 404}


def test_a_generic_module_gets_the_placeholder_workspace_not_the_leadgen_one(client, user, registry):
    registry["widget"] = modules_mod.Module(
        id="widget", name="Widget Pro", slug="widget", description="A widget",
        min_plan="starter", route_path="/module/widget")
    set_plan(user, "starter")
    r = client.get("/growth/module/widget")
    assert r.status_code == 200
    assert "<title>Widget Pro — Leviathan Growth</title>" in r.text
    assert ">Widget Pro</h1>" in r.text
    assert "Module interface loading..." in r.text
    assert "Olive Owner" in r.text
    assert 'id="search-form"' not in r.text, "a non-leadgen module must not get leadgen's UI"
    assert 'action="/growth/api/capture"' not in r.text


def test_a_generic_module_below_its_tier_still_hits_the_paywall(client, user, registry):
    registry["widget"] = modules_mod.Module(
        id="widget", name="Widget Pro", slug="widget", description="A widget",
        min_plan="enterprise", route_path="/module/widget")
    set_plan(user, "starter")
    r = client.get("/growth/module/widget", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile?next=/growth/module/widget"


def test_a_custom_access_check_overrides_the_tier_on_the_module_page(client, user, registry):
    """The bespoke check is authoritative, even when it is more permissive."""
    registry["leadgen"].access_check = lambda module, plan: True
    set_plan(user, "free")
    r = client.get("/growth/module/leadgen")
    assert r.status_code == 200
    assert "Find developers who buy land" in r.text

    registry["leadgen"].access_check = lambda module, plan: False
    set_plan(user, "enterprise")
    r = client.get("/growth/module/leadgen", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile?next=/growth/module/leadgen"


# ── the profile page ───────────────────────────────────────────────────────
def test_the_profile_shows_the_user_org_and_every_plan(client, user):
    r = client.get("/growth/profile")
    assert r.status_code == 200
    assert "Your Profile" in r.text
    assert "<strong>Name:</strong> Olive Owner" in r.text
    assert "<strong>Email:</strong> owner@example.com" in r.text
    assert "<strong>Company:</strong> Olive Roofing" in r.text
    assert "<strong>Current plan:</strong> Free" in r.text
    for plan, price in PRICES.items():
        assert price in r.text, plan
        assert f'name="plan" value="{plan}"' in r.text
    assert 'name="module_id" value="leadgen"' in r.text


def test_an_unconfigured_or_failing_subscription_lookup_still_renders_the_page(client, user):
    """`get_subscription` raising is caught; the page must not 500."""
    async def boom(self, account_id):
        raise RuntimeError("stripe unreachable")

    original = portal_mod.StripeIntegration.get_subscription
    portal_mod.StripeIntegration.get_subscription = boom
    try:
        r = client.get("/growth/profile")
    finally:
        portal_mod.StripeIntegration.get_subscription = original
    assert r.status_code == 200
    assert "<strong>Subscription status:</strong> none" in r.text
    assert r.text.count("— Subscribe") == 4, "no plan is marked active"


def test_the_active_plan_gets_a_manage_link_and_the_others_keep_subscribe(client, user, monkeypatch):
    async def active(self, account_id):
        active.seen = account_id
        return {"status": "active", "plan": "growth"}

    active.seen = None
    monkeypatch.setattr(portal_mod.StripeIntegration, "get_subscription", active)
    r = client.get("/growth/profile")
    assert r.status_code == 200
    assert active.seen == user["org_id"], "the org id is what Stripe is keyed on"
    assert "Manage Growth subscription" in r.text
    assert 'href="/growth/api/billing-portal"' in r.text
    assert "<strong>Subscription status:</strong> active" in r.text
    assert "border-emerald-500" in r.text, "the active tier is highlighted"
    assert r.text.count("— Subscribe") == 3, "exactly one plan is replaced"


def test_the_profile_html_escapes_hostile_identity_fields(client, db):
    """A name or company containing markup must not become live HTML."""
    client.post("/growth/api/register", json={
        "email": "xss@example.com", "password": GOOD_PASSWORD,
        "name": "<script>alert(1)</script>",
        "org_name": "<img src=x onerror=alert(2)>"}, follow_redirects=False)
    text = client.get("/growth/profile").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "<img src=x onerror=alert(2)>" not in text
    assert "&lt;img src=x onerror=alert(2)&gt;" in text


def test_the_leadgen_workspace_html_escapes_the_users_name(client, user):
    with Database.get_connection() as conn:
        conn.execute("UPDATE users SET name = ? WHERE id = ?",
                     ("<script>alert(3)</script>", user["id"]))
        conn.commit()
    set_plan(user, "starter")
    text = client.get("/growth/module/leadgen").text
    assert "<script>alert(3)</script>" not in text
    assert "&lt;script&gt;alert(3)&lt;/script&gt;" in text


# ── Stripe hand-off ────────────────────────────────────────────────────────
def test_subscribing_303s_to_a_stripe_checkout_session(client, user, stripe):
    set_plan(user, "free")
    r = client.post("/growth/api/subscribe", json={"plan": "pro", "module_id": "leadgen"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "https://checkout.stripe.test/c/session"

    (call,) = stripe.calls
    assert call["kind"] == "checkout"
    assert call["plan"] == "pro"
    assert call["account_id"] == user["org_id"]
    assert call["success_url"] == "http://testserver/growth/?subscribed=pro"
    assert call["cancel_url"] == "http://testserver/growth/profile?canceled=1"


def test_subscribing_defaults_the_module_to_leadgen(client, user, stripe):
    r = client.post("/growth/api/subscribe", json={"plan": "starter"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert stripe.calls[0]["plan"] == "starter"


def test_subscribing_to_an_unknown_module_is_a_404(client, user, stripe):
    r = client.post("/growth/api/subscribe", json={"plan": "starter", "module_id": "ghost"})
    assert r.status_code == 404
    assert r.json() == {"error": "Module not found", "code": 404}
    assert stripe.calls == [], "no checkout session may be created for a bad module"


def test_subscribing_without_stripe_configured_is_a_503(client, user, no_stripe):
    r = client.post("/growth/api/subscribe", json={"plan": "starter"})
    assert r.status_code == 503
    assert r.json() == {"error": "Stripe is not configured", "code": 503}


def test_the_billing_portal_303s_back_to_the_stripe_portal(client, user, stripe):
    r = client.get("/growth/api/billing-portal", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "https://billing.stripe.test/session"
    (call,) = stripe.calls
    assert call["kind"] == "portal"
    assert call["account_id"] == user["org_id"]
    assert call["return_url"] == "http://testserver/growth/profile"


def test_the_billing_portal_without_stripe_configured_is_a_503(client, user, no_stripe):
    r = client.get("/growth/api/billing-portal")
    assert r.status_code == 503
    assert r.json() == {"error": "Stripe is not configured", "code": 503}


# ── public lead capture ────────────────────────────────────────────────────
FULL_CAPTURE = {
    "full_name": "  Ada   Byron Lovelace  ",
    "email": "ada@example.com",
    "phone": "555-0100",
    "service_requested": "Roofing",
    "city": "Austin",
    "state": "TX",
    "zip": "78701",
    "source": "growth_portal_probe",
    "utm_source": "google",
    "utm_medium": "cpc",
    "utm_campaign": "spring",
    "budget_range": "10-20k",
    "description": "Z" * 400,
}


def test_a_json_capture_returns_the_new_lead_id_without_redirecting(anon, db):
    r = anon.post("/growth/api/capture", json=FULL_CAPTURE)
    assert r.status_code == 200
    assert r.headers.get("location") is None
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "captured"
    lead_id = body["lead_id"]
    assert len(lead_id) == 12
    assert set(lead_id) <= set("0123456789abcdef")
    assert lead_row(lead_id) is not None


def test_a_browser_form_post_is_redirected_to_the_thank_you_page(anon, db):
    r = anon.post("/growth/api/capture", data={
        "full_name": "Form F", "email": "f@example.com", "phone": "1",
        "service_requested": "HVAC"}, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/thank-you"
    with Database.get_connection() as conn:
        n = conn.execute("SELECT count(*) FROM leads WHERE title = 'Form F'").fetchone()[0]
    assert n == 1, "the lead is stored even though the browser gets a redirect"


def test_the_captured_lead_row_is_built_exactly_as_documented(anon, db):
    lead_id = anon.post("/growth/api/capture", json=FULL_CAPTURE).json()["lead_id"]
    row = lead_row(lead_id)
    assert row["id"] == lead_id
    assert row["title"] == FULL_CAPTURE["full_name"], "stored verbatim, not trimmed"
    assert row["url"] == ""
    assert row["industry"] == "Roofing"
    assert row["location"] == "Austin, TX 78701"
    assert row["source"] == "growth_portal_probe"
    assert row["email"] == "ada@example.com"
    assert row["phone"] == "555-0100"
    assert row["notes"] == '["Captured from growth_portal_probe"]'
    assert row["score_breakdown"] == "{}"
    assert row["score"] == 0
    assert row["found_at"], "a capture is stamped with a time"


def test_the_description_is_truncated_to_exactly_300_characters(anon, db):
    lead_id = anon.post("/growth/api/capture", json=FULL_CAPTURE).json()["lead_id"]
    row = lead_row(lead_id)
    assert len(row["snippet"]) == 300
    assert row["snippet"] == "Z" * 300


def test_a_short_description_is_stored_untruncated(anon, db):
    payload = dict(FULL_CAPTURE, description="short note")
    lead_id = anon.post("/growth/api/capture", json=payload).json()["lead_id"]
    assert lead_row(lead_id)["snippet"] == "short note"


def test_the_location_is_joined_and_stripped_whatever_geo_is_supplied(anon, db):
    cases = [
        ({"city": "Austin", "state": "TX", "zip": "78701"}, "Austin, TX 78701"),
        ({"city": "Austin"}, "Austin"),
        ({"city": "", "state": "", "zip": ""}, ""),
        ({"state": "TX"}, "TX"),
        ({"zip": "78701"}, "78701"),
    ]
    for geo, expected in cases:
        payload = {k: v for k, v in FULL_CAPTURE.items()
                   if k not in ("city", "state", "zip")}
        payload.update(geo)
        lead_id = anon.post("/growth/api/capture", json=payload).json()["lead_id"]
        assert lead_row(lead_id)["location"] == expected, geo


def test_an_empty_capture_body_still_produces_a_row_with_defaults(anon, db):
    r = anon.post("/growth/api/capture", json={})
    assert r.status_code == 200
    row = lead_row(r.json()["lead_id"])
    assert row["title"] == ""
    assert row["location"] == ""
    assert row["notes"] == '["Captured from growth_portal"]', "the default source"
    assert row["score"] == 0


def test_a_browser_post_with_no_fields_still_stores_a_lead(anon, db):
    r = anon.post("/growth/api/capture", data={}, follow_redirects=False)
    assert r.status_code == 302
    with Database.get_connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM leads WHERE title = ''").fetchone()[0] == 1


def test_two_identical_captures_create_two_distinct_leads(anon, db):
    a = anon.post("/growth/api/capture", json=FULL_CAPTURE).json()["lead_id"]
    b = anon.post("/growth/api/capture", json=FULL_CAPTURE).json()["lead_id"]
    assert a != b, "capture does not dedupe on content"
    assert lead_row(a) is not None and lead_row(b) is not None


# ── the normalised lead handed to CRM and nurture ──────────────────────────
class RecordingCrm:
    seen: list = []

    def __init__(self):
        pass

    async def push_lead(self, lead, provider="hubspot", config=None):
        RecordingCrm.seen.append(lead)
        return {"ok": True}


class RecordingNurture:
    seen: list = []

    def __init__(self):
        pass

    async def start_sequence(self, lead):
        RecordingNurture.seen.append(lead)
        return {"sequence_id": "seq-1"}


@pytest.fixture
def pipeline(monkeypatch):
    import engine.crm_push as crm_mod
    import engine.nurture as nurture_mod

    RecordingCrm.seen = []
    RecordingNurture.seen = []
    monkeypatch.setattr(crm_mod, "CrmPush", RecordingCrm)
    monkeypatch.setattr(nurture_mod, "NurtureEngine", RecordingNurture)
    return RecordingCrm, RecordingNurture


def test_the_lead_handed_to_crm_is_normalised_from_the_capture_form(anon, db, pipeline):
    anon.post("/growth/api/capture", json=FULL_CAPTURE)
    (lead,) = RecordingCrm.seen
    assert lead["first_name"] == "Ada", "leading and repeated spaces collapse"
    assert lead["last_name"] == "Byron Lovelace", "everything after the first token"
    assert lead["full_name"] == FULL_CAPTURE["full_name"]
    assert lead["email"] == "ada@example.com"
    assert lead["phone"] == "555-0100"
    assert lead["service_requested"] == "Roofing"
    assert lead["city"] == "Austin"
    assert lead["state"] == "TX"
    assert lead["zip"] == "78701"
    assert lead["source"] == "growth_portal_probe"
    assert (lead["utm_source"], lead["utm_medium"], lead["utm_campaign"]) == \
        ("google", "cpc", "spring")
    assert lead["budget_range"] == "10-20k"
    assert lead["capture_timestamp"]


def test_a_new_capture_starts_unscored_and_queued_for_immediate_follow_up(anon, db, pipeline):
    anon.post("/growth/api/capture", json=FULL_CAPTURE)
    (lead,) = RecordingCrm.seen
    assert lead["status"] == "new"
    assert lead["next_action"] == "Qualify and respond within 5 minutes"
    assert (lead["geo_score"], lead["urgency_score"], lead["budget_fit_score"],
            lead["service_fit_score"], lead["lead_value_score"]) == (0, 0, 0, 0, 0)
    assert lead["consent_flags"] == {"email": True, "sms": True, "call": True}
    assert lead["notes"] == ["Captured from growth_portal_probe"]


def test_a_single_word_name_yields_no_last_name(anon, db, pipeline):
    anon.post("/growth/api/capture", json=dict(FULL_CAPTURE, full_name="Cher"))
    (lead,) = RecordingCrm.seen
    assert lead["first_name"] == "Cher"
    assert lead["last_name"] == ""


def test_a_missing_name_yields_no_first_or_last_name(anon, db, pipeline):
    r = anon.post("/growth/api/capture", json={})
    (lead,) = RecordingCrm.seen
    assert lead["first_name"] == ""
    assert lead["last_name"] == ""
    assert lead["lead_id"] == r.json()["lead_id"]


def test_the_crm_and_the_nurture_queue_receive_the_same_lead_object(anon, db, pipeline):
    anon.post("/growth/api/capture", json=FULL_CAPTURE)
    (crm_lead,) = RecordingCrm.seen
    (nurture_lead,) = RecordingNurture.seen
    assert crm_lead == nurture_lead
    assert crm_lead is nurture_lead, "one normalised lead, two consumers"


def test_capture_queues_exactly_one_follow_up_sequence_per_lead(anon, db):
    """The real NurtureEngine runs here and persists one sequence row per lead.

    `_queue_followup` imports NurtureEngine inside the function body, so the
    patch has to land on the `engine.nurture` module attribute, not on a
    fixture that has already replaced it.
    """
    import engine.crm_push as crm_mod
    import engine.key_vault as kv

    class QuietCrm:
        def __init__(self):
            pass

        async def push_lead(self, lead, **kw):
            return {"ok": False}

    before = len(nurture_rows())
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(crm_mod, "CrmPush", QuietCrm)
        mp.setattr(kv.KeyVault, "get", lambda *a, **k: None)  # no webhook, no network
        anon.post("/growth/api/capture", json=dict(
            FULL_CAPTURE, email="seq@example.com", phone="555-0000"))
        anon.post("/growth/api/capture", json=dict(
            FULL_CAPTURE, email="seq2@example.com", phone="555-0001"))
    rows = nurture_rows()
    assert len(rows) == before + 2, "one sequence per capture, never deduped"
    (first, second) = rows[-2:]
    assert len(first["id"]) == 12
    assert first["id"] != second["id"]
    assert [r["lead_email"] for r in (first, second)] == \
        ["seq@example.com", "seq2@example.com"]
    assert first["lead_phone"] == "555-0000"


def test_a_failing_crm_push_does_not_lose_the_captured_lead(anon, db):
    import engine.crm_push as crm_mod
    import engine.nurture as nurture_mod
    import engine.key_vault as kv

    class BrokenCrm:
        def __init__(self):
            pass

        async def push_lead(self, lead, **kw):
            raise RuntimeError("crm is down")

    class BrokenNurture:
        def __init__(self):
            pass

        async def start_sequence(self, lead):
            raise RuntimeError("nurture is down")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(crm_mod, "CrmPush", BrokenCrm)
        mp.setattr(nurture_mod, "NurtureEngine", BrokenNurture)
        mp.setattr(kv.KeyVault, "get", lambda *a, **k: None)
        r = anon.post("/growth/api/capture", json=FULL_CAPTURE)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert lead_row(r.json()["lead_id"]) is not None, "the lead survives both failures"


# ── the outbound CRM webhook ───────────────────────────────────────────────
class RecordingWebhookClient:
    """An httpx.AsyncClient stand-in that records POSTs and never leaves the box."""
    posted: list = []
    fail = False

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        if RecordingWebhookClient.fail:
            raise RuntimeError("webhook unreachable")
        RecordingWebhookClient.posted.append((url, json))
        return type("R", (), {"status_code": 200, "text": "ok", "json": lambda: {}})()


def test_a_configured_webhook_receives_the_normalised_lead(anon, db, pipeline, monkeypatch):
    import engine.key_vault as kv

    RecordingWebhookClient.posted = []
    RecordingWebhookClient.fail = False
    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: "https://hooks.test/lead")
    monkeypatch.setattr(portal_mod.httpx, "AsyncClient", RecordingWebhookClient)

    r = anon.post("/growth/api/capture", json=FULL_CAPTURE)
    assert len(RecordingWebhookClient.posted) == 1
    url, payload = RecordingWebhookClient.posted[0]
    assert url == "https://hooks.test/lead"
    assert payload["lead_id"] == r.json()["lead_id"]
    assert payload["email"] == "ada@example.com"
    assert payload == RecordingCrm.seen[0]


def test_an_unreachable_webhook_does_not_fail_the_capture(anon, db, pipeline, monkeypatch):
    import engine.key_vault as kv

    RecordingWebhookClient.posted = []
    RecordingWebhookClient.fail = True
    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: "https://hooks.test/lead")
    monkeypatch.setattr(portal_mod.httpx, "AsyncClient", RecordingWebhookClient)

    r = anon.post("/growth/api/capture", json=FULL_CAPTURE)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert RecordingWebhookClient.posted == []


def test_no_webhook_url_means_no_outbound_http_at_all(anon, db, pipeline, monkeypatch):
    import engine.key_vault as kv

    def forbidden(*args, **kwargs):
        raise AssertionError("no HTTP may be attempted without a webhook url")

    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: None)
    monkeypatch.setattr(portal_mod.httpx, "AsyncClient", forbidden)
    r = anon.post("/growth/api/capture", json=FULL_CAPTURE)
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── Google OAuth: the redirect out ─────────────────────────────────────────
def test_google_login_is_503_when_the_client_id_is_absent(anon, monkeypatch):
    import engine.key_vault as kv

    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: None)
    r = anon.get("/growth/auth/google/login")
    assert r.status_code == 503
    assert r.json() == {
        "error": "Google OAuth client ID is not configured in KeyVault.", "code": 503}


def test_google_login_redirects_with_the_full_oauth_query(anon, monkeypatch):
    import engine.key_vault as kv

    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: "client-123")
    r = anon.get("/growth/auth/google/login?next=/growth/profile", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))
    assert q["client_id"] == "client-123"
    assert q["redirect_uri"] == "http://testserver/growth/auth/google/callback"
    assert q["response_type"] == "code"
    assert q["scope"] == "openid email profile"
    assert q["state"] == "/growth/profile"
    assert q["access_type"] == "online"
    assert q["prompt"] == "select_account"


def test_google_login_defaults_the_state_to_the_portal_root(anon, monkeypatch):
    import engine.key_vault as kv

    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: "client-123")
    r = anon.get("/growth/auth/google/login", follow_redirects=False)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).query))
    assert q["state"] == "/growth/"


# ── Google OAuth: the callback ────────────────────────────────────────────
class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeOAuthClient:
    """Records both calls the callback makes so the request shape can be asserted."""
    token_response = None
    userinfo_response = None
    token_exc = None
    calls: list = []

    def __init__(self, *args, **kwargs):
        FakeOAuthClient.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None):
        FakeOAuthClient.calls.append(("POST", url, data))
        if FakeOAuthClient.token_exc:
            raise FakeOAuthClient.token_exc
        return FakeOAuthClient.token_response

    async def get(self, url, headers=None):
        FakeOAuthClient.calls.append(("GET", url, headers))
        return FakeOAuthClient.userinfo_response


@pytest.fixture
def oauth(monkeypatch):
    import engine.key_vault as kv

    FakeOAuthClient.calls = []
    FakeOAuthClient.token_exc = None
    FakeOAuthClient.token_response = FakeResponse(200, {"access_token": "AT-1"})
    FakeOAuthClient.userinfo_response = FakeResponse(
        200, {"email": "guser@example.com", "name": "Gus Google", "sub": "gsub-1"})
    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: "client-123")
    monkeypatch.setattr(portal_mod.httpx, "AsyncClient", FakeOAuthClient)
    return FakeOAuthClient


def test_the_callback_without_a_code_is_a_400(anon, db):
    r = anon.get("/growth/auth/google/callback")
    assert r.status_code == 400
    assert r.json() == {"error": "Missing authorization code from Google.", "code": 400}


def test_the_callback_with_unconfigured_credentials_is_a_503(anon, db, monkeypatch):
    import engine.key_vault as kv

    monkeypatch.setattr(kv.KeyVault, "get", lambda *a, **k: None)
    r = anon.get("/growth/auth/google/callback?code=abc")
    assert r.status_code == 503
    assert "not fully configured" in r.json()["error"]


def test_the_callback_exchanges_the_code_then_fetches_the_profile(anon, db, oauth):
    r = anon.get("/growth/auth/google/callback?code=auth-code&state=/growth/profile",
                 follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/growth/profile"

    post_call, get_call = oauth.calls
    assert post_call[0] == "POST"
    assert post_call[1] == "https://oauth2.googleapis.com/token"
    assert post_call[2] == {
        "code": "auth-code",
        "client_id": "client-123",
        "client_secret": "client-123",
        "redirect_uri": "http://testserver/growth/auth/google/callback",
        "grant_type": "authorization_code",
    }
    assert get_call[0] == "GET"
    assert get_call[1] == "https://www.googleapis.com/oauth2/v3/userinfo"
    assert get_call[2] == {"Authorization": "Bearer AT-1"}


def test_a_successful_callback_registers_the_google_user_and_starts_a_session(anon, db, oauth):
    r = anon.get("/growth/auth/google/callback?code=auth-code&state=/growth/profile",
                 follow_redirects=False)
    assert r.status_code == 302
    created = auth_manager.get_user_by_google_id("gsub-1")
    assert created is not None
    assert created["email"] == "guser@example.com"
    assert created["name"] == "Gus Google"
    token = r.cookies["growth_token"]
    assert auth_manager.verify_jwt(token)["sub"] == created["id"]


def test_a_second_google_login_reuses_the_existing_user_and_the_same_org(anon, db, oauth):
    anon.get("/growth/auth/google/callback?code=auth-code", follow_redirects=False)
    first = auth_manager.get_user_by_google_id("gsub-1")
    with Database.get_connection() as conn:
        orgs_before = conn.execute("SELECT count(*) FROM orgs").fetchone()[0]
        conn.commit()
    r = anon.get("/growth/auth/google/callback?code=auth-code", follow_redirects=False)
    assert r.status_code == 302
    assert auth_manager.get_user_by_google_id("gsub-1")["id"] == first["id"]
    with Database.get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM orgs").fetchone()[0] == orgs_before, \
            "a returning Google user must not get a second org"


def test_a_google_login_for_a_known_email_links_the_id_instead_of_duplicating(anon, db, oauth):
    anon.post("/growth/api/register", json={
        "email": "existing@example.com", "password": GOOD_PASSWORD,
        "name": "Ex Existing", "org_name": "Ex Co"}, follow_redirects=False)
    anon.cookies.clear()
    original = auth_manager.get_user_by_email("existing@example.com")

    oauth.userinfo_response = FakeResponse(
        200, {"email": "existing@example.com", "sub": "gsub-link"})
    r = anon.get("/growth/auth/google/callback?code=auth-code&state=/growth/",
                 follow_redirects=False)
    assert r.status_code == 302
    linked = auth_manager.get_user_by_google_id("gsub-link")
    assert linked is not None
    assert linked["id"] == original["id"], "the password account is kept, not replaced"
    assert auth_manager.verify_jwt(r.cookies["growth_token"])["sub"] == original["id"]


def test_a_name_missing_from_google_falls_back_to_given_name_then_a_default(anon, db, oauth):
    oauth.userinfo_response = FakeResponse(
        200, {"email": "g2@example.com", "given_name": "Geo", "sub": "gsub-2"})
    anon.get("/growth/auth/google/callback?code=auth-code", follow_redirects=False)
    assert auth_manager.get_user_by_google_id("gsub-2")["name"] == "Geo"

    oauth.userinfo_response = FakeResponse(
        200, {"email": "g3@example.com", "sub": "gsub-3"})
    anon.get("/growth/auth/google/callback?code=auth-code", follow_redirects=False)
    assert auth_manager.get_user_by_google_id("gsub-3")["name"] == "Google User"


def test_a_google_profile_without_an_email_is_rejected(anon, db, oauth):
    oauth.userinfo_response = FakeResponse(200, {"sub": "gsub-no-email"})
    r = anon.get("/growth/auth/google/callback?code=auth-code")
    assert r.status_code == 400
    assert "did not include email" in r.json()["error"]
    assert auth_manager.get_user_by_google_id("gsub-no-email") is None


def test_a_google_profile_without_a_subject_is_rejected(anon, db, oauth):
    oauth.userinfo_response = FakeResponse(200, {"email": "no-sub@example.com"})
    r = anon.get("/growth/auth/google/callback?code=auth-code")
    assert r.status_code == 400
    assert auth_manager.get_user_by_email("no-sub@example.com") is None


def test_a_rejected_code_is_refused_before_any_user_is_created(anon, db, oauth):
    oauth.token_response = FakeResponse(400, text="invalid_grant: bad code")
    r = anon.get("/growth/auth/google/callback?code=stale")
    assert r.status_code == 500
    assert "token exchange failed" in r.json()["error"]
    assert "invalid_grant" in r.json()["error"], "the provider's reason is surfaced"
    assert auth_manager.get_user_by_google_id("gsub-1") is None


def test_a_failed_profile_fetch_is_refused(anon, db, oauth):
    oauth.userinfo_response = FakeResponse(403, text="forbidden")
    r = anon.get("/growth/auth/google/callback?code=auth-code")
    assert r.status_code == 500
    assert "userinfo request failed" in r.json()["error"]
    assert auth_manager.get_user_by_google_id("gsub-1") is None


def test_a_network_failure_during_the_exchange_is_reported_as_500(anon, db, oauth):
    oauth.token_exc = RuntimeError("connection reset")
    r = anon.get("/growth/auth/google/callback?code=auth-code")
    assert r.status_code == 500
    assert "OAuth login failed" in r.json()["error"]
    assert auth_manager.get_user_by_google_id("gsub-1") is None


def test_an_off_site_state_is_re_anchored_to_the_portal_root(anon, db, oauth):
    """`state` becomes the post-login Location, so it must not be an open redirect."""
    for hostile in ("https://evil.example/steal", "//evil.example", "http://x"):
        r = anon.get("/growth/auth/google/callback?code=auth-code&state=" +
                     urllib.parse.quote(hostile), follow_redirects=False)
        assert r.headers["location"] == "/growth/", hostile


def test_the_callback_defaults_the_state_to_the_portal_root(anon, db, oauth):
    r = anon.get("/growth/auth/google/callback?code=auth-code", follow_redirects=False)
    assert r.headers["location"] == "/growth/"


def test_the_callback_session_cookie_matches_the_registered_user(anon, db, oauth):
    r = anon.get("/growth/auth/google/callback?code=auth-code", follow_redirects=False)
    created = auth_manager.get_user_by_google_id("gsub-1")
    payload = auth_manager.verify_jwt(r.cookies["growth_token"])
    assert payload["sub"] == created["id"]
    assert payload["org_id"] == created["org_id"]
    assert "HttpOnly" in r.headers["set-cookie"]
    assert "Max-Age=604800" in r.headers["set-cookie"]


# ── the page builder and session helpers ───────────────────────────────────
def test_page_injects_the_title_body_and_extra_head_once():
    html = portal_mod._page("My Title", "<p>hi</p>", '<meta name="x">')
    assert "<title>My Title — Leviathan Growth</title>" in html
    assert "<p>hi</p>" in html
    assert html.count('<meta name="x">') == 1
    assert html.startswith("<!DOCTYPE html>")


def test_page_with_no_extra_head_still_produces_valid_markup():
    assert portal_mod._page("T", "B").count("<head>") == 1


def test_a_bare_request_has_no_session_and_require_user_raises_401():
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/growth/", "query_string": b"",
             "headers": [], "scheme": "http", "server": ("t", 80),
             "client": ("1.2.3.4", 1234), "root_path": ""}
    request = Request(scope)
    assert portal_mod._get_cookie_token(request) is None
    assert portal_mod._current_user(request) is None
    with pytest.raises(Exception) as exc:
        portal_mod._require_user(request)
    assert getattr(exc.value, "status_code", None) == 401


def test_the_leadgen_workspace_renders_without_network_or_stripe(anon, db):
    """The page must build from a dict alone — no hidden I/O."""
    html = portal_mod._leadgen_module_html({"user": {"name": "Solo"}})
    assert "Solo" in html
    assert "&lt;script&gt;" in portal_mod._leadgen_module_html(
        {"user": {"name": "<script>x</script>"}})


# ── pydantic request models ────────────────────────────────────────────────
def test_the_lead_capture_model_fills_every_optional_field():
    model = portal_mod.LeadCaptureRequest(full_name="A B", email="a@b.com", phone="1",
                                          service_requested="roofing")
    dumped = model.model_dump()
    assert dumped["source"] == "growth_portal"
    for optional in ("city", "state", "zip", "budget_range", "description",
                     "utm_source", "utm_medium", "utm_campaign"):
        assert dumped[optional] == "", optional


def test_the_lead_capture_model_requires_the_core_four_fields():
    with pytest.raises(Exception):
        portal_mod.LeadCaptureRequest(full_name="A B", email="a@b.com")


def test_the_lead_capture_model_rejects_a_malformed_email():
    with pytest.raises(Exception):
        portal_mod.LeadCaptureRequest(full_name="A B", email="not-an-email",
                                      phone="1", service_requested="x")


def test_the_subscribe_model_records_the_plan_and_module():
    model = portal_mod.SubscribeRequest(plan="pro", module_id="leadgen")
    assert (model.plan, model.module_id) == ("pro", "leadgen")
