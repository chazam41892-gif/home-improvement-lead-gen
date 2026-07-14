"""Growth portal — B2B module catalog, auth, billing, and subscription gating.

Serves growth.leviathansi.xyz. Users land on the module catalog, click a
module, create a profile, subscribe via Stripe, then access the module.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

import html as _html

from ..auth import auth_manager
from ..stripe_integration import StripeIntegration
from ..database import Database
from ..key_vault import KeyVault
from .modules import list_modules, get_module, can_access_module
from .tracking import _record_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/growth", tags=["growth"])

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ───────────────────────────── Pydantic models

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    org_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SubscribeRequest(BaseModel):
    plan: str
    module_id: str


class LeadCaptureRequest(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    service_requested: str
    city: str = ""
    state: str = ""
    zip: str = ""
    budget_range: str = ""
    description: str = ""
    source: str = "growth_portal"
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""


# ───────────────────────────── HTML helpers

def _page(title: str, body: str, extra_head: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Leviathan Growth</title>
<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
{extra_head}
</head>
<body class="bg-gray-900 text-white">
{body}
</body>
</html>"""


def _get_cookie_token(request: Request) -> Optional[str]:
    return request.cookies.get("growth_token")


def _current_user(request: Request) -> Optional[Dict[str, Any]]:
    token = _get_cookie_token(request)
    if not token:
        return None
    payload = auth_manager.verify_jwt(token)
    if not payload:
        return None
    user = auth_manager.get_user(payload["sub"])
    if not user:
        return None
    org = auth_manager.get_org(user["org_id"])
    payload["user"] = user
    payload["org"] = org
    return payload


def _require_user(request: Request) -> Dict[str, Any]:
    user = _current_user(request)
    if not user:
        raise HTTPException(401, "Unauthorized")
    return user


# ───────────────────────────── Portal pages

@router.get("/", response_class=HTMLResponse)
async def portal_home(request: Request):
    """B2B module catalog at growth.leviathansi.xyz"""
    user = _current_user(request)
    plan = user.get("org", {}).get("plan", "free") if user else "free"

    cards = []
    for m in list_modules():
        access = can_access_module(m["id"], plan)
        cta = "Open Module" if access else f"Subscribe from {m['min_plan'].capitalize()}"
        btn_class = "bg-emerald-500 hover:bg-emerald-600" if access else "bg-blue-600 hover:bg-blue-700"
        cards.append(f"""
        <div class="bg-gray-800 rounded-xl p-6 shadow-lg hover:shadow-2xl transition">
          <div class="text-4xl mb-4">{m['icon']}</div>
          <h3 class="text-xl font-bold mb-2">{m['name']}</h3>
          <p class="text-gray-400 mb-4">{m['description']}</p>
          <div class="flex flex-wrap gap-2 mb-4">
            {''.join(f'<span class="text-xs bg-gray-700 px-2 py-1 rounded">{t}</span>' for t in m['tags'])}
          </div>
          <a href="/growth/module/{m['slug']}" class="inline-block {btn_class} text-white px-4 py-2 rounded font-semibold">
            {cta}
          </a>
        </div>
        """)

    cards_html = "".join(cards) if cards else "<p class='text-gray-400'>No modules available yet.</p>"

    auth_bar = ""
    if user:
        auth_bar = f"""
        <div class="flex items-center gap-4">
          <span class="text-sm text-gray-400">{user['user']['name']} — {plan.capitalize()}</span>
          <a href="/growth/profile" class="text-sm text-emerald-400 hover:underline">Profile</a>
          <a href="/growth/logout" class="text-sm text-red-400 hover:underline">Logout</a>
        </div>
        """
    else:
        auth_bar = """
        <div class="flex items-center gap-4">
          <a href="/growth/login" class="text-emerald-400 hover:underline">Login</a>
          <a href="/growth/register" class="bg-emerald-500 hover:bg-emerald-600 text-white px-4 py-2 rounded">Create free account</a>
        </div>
        """

    body = f"""
    <header class="border-b border-gray-800">
      <div class="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
        <a href="/growth" class="text-2xl font-bold tracking-tight">Leviathan <span class="text-emerald-400">Growth</span></a>
        {auth_bar}
      </div>
    </header>
    <main class="max-w-6xl mx-auto px-4 py-12">
      <div class="text-center mb-16">
        <h1 class="text-4xl md:text-5xl font-extrabold mb-4">AI-powered B2B modules for growth</h1>
        <p class="text-xl text-gray-400 max-w-2xl mx-auto">Subscribe to the modules your business needs. Start with Lead Gen Pro for home improvement, real estate, and land developers.</p>
      </div>
      <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {cards_html}
      </div>
    </main>
    """
    return _page("Growth Portal", body)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    body = """
    <div class="min-h-screen flex items-center justify-center px-4">
      <div class="bg-gray-800 p-8 rounded-xl max-w-md w-full">
        <h1 class="text-2xl font-bold mb-6">Create your account</h1>
        <form action="/growth/api/register" method="POST" class="space-y-4">
          <input type="text" name="name" placeholder="Your name" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
          <input type="email" name="email" placeholder="Email" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
          <input type="password" name="password" placeholder="Password" required minlength="8" class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
          <input type="text" name="org_name" placeholder="Company name" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
          <button type="submit" class="w-full bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-2 rounded">Create account</button>
        </form>
        <p class="mt-4 text-sm text-gray-400">Already have an account? <a href="/growth/login" class="text-emerald-400 hover:underline">Login</a></p>
      </div>
    </div>
    """
    return _page("Create account", body)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    body = """
    <div class="min-h-screen flex items-center justify-center px-4">
      <div class="bg-gray-800 p-8 rounded-xl max-w-md w-full">
        <h1 class="text-2xl font-bold mb-6">Log in to Leviathan Growth</h1>
        <form action="/growth/api/login" method="POST" class="space-y-4">
          <input type="email" name="email" placeholder="Email" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
          <input type="password" name="password" placeholder="Password" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
          <button type="submit" class="w-full bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-2 rounded">Log in</button>
        </form>
        <p class="mt-4 text-sm text-gray-400">No account? <a href="/growth/register" class="text-emerald-400 hover:underline">Create one</a></p>
      </div>
    </div>
    """
    return _page("Login", body)


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/growth/", status_code=302)
    resp.delete_cookie("growth_token")
    return resp


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    user = _require_user(request)
    org = user["org"]
    stripe = StripeIntegration()

    sub_status = {"status": "none"}
    try:
        sub_status = await stripe.get_subscription(org["id"])
    except Exception as e:
        logger.debug("No subscription found: %s", e)

    plans_html = ""
    for plan_id, cents in [("starter", 9700), ("growth", 19700), ("pro", 49700), ("enterprise", 99700)]:
        price = f"${cents/100:.0f}/mo"
        active = sub_status.get("plan") == plan_id
        btn = f"""
        <form action="/growth/api/subscribe" method="POST" class="inline">
          <input type="hidden" name="plan" value="{plan_id}">
          <input type="hidden" name="module_id" value="leadgen">
          <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 rounded">
            {price} — Subscribe
          </button>
        </form>
        """
        if active:
            btn = f"""
            <a href="/growth/api/billing-portal" class="block text-center bg-gray-600 hover:bg-gray-500 text-white font-bold py-2 rounded">
              Manage {plan_id.capitalize()} subscription
            </a>
            """
        plans_html += f"""
        <div class="bg-gray-800 p-6 rounded-xl border {'border-emerald-500' if active else 'border-gray-700'}">
          <h3 class="text-xl font-bold mb-2">{plan_id.capitalize()}</h3>
          <p class="text-2xl font-bold text-emerald-400 mb-4">{price}</p>
          {btn}
        </div>
        """

    body = f"""
    <header class="border-b border-gray-800">
      <div class="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
        <a href="/growth" class="text-2xl font-bold tracking-tight">Leviathan <span class="text-emerald-400">Growth</span></a>
        <a href="/growth/logout" class="text-sm text-red-400 hover:underline">Logout</a>
      </div>
    </header>
    <main class="max-w-4xl mx-auto px-4 py-12">
      <h1 class="text-3xl font-bold mb-8">Your Profile</h1>
      <div class="bg-gray-800 p-6 rounded-xl mb-8">
        <p><strong>Name:</strong> {_html.escape(user['user']['name'])}</p>
        <p><strong>Email:</strong> {_html.escape(user['user']['email'])}</p>
        <p><strong>Company:</strong> {_html.escape(org['name'])}</p>
        <p><strong>Current plan:</strong> {_html.escape(org.get('plan','free')).capitalize()}</p>
        <p><strong>Subscription status:</strong> {_html.escape(sub_status.get('status','none'))}</p>
      </div>
      <h2 class="text-2xl font-bold mb-4">Available plans</h2>
      <div class="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
        {plans_html}
      </div>
    </main>
    """
    return _page("Profile", body)


@router.get("/module/{module_slug}", response_class=HTMLResponse)
async def module_landing(request: Request, module_slug: str):
    module = get_module(module_slug)
    if not module:
        raise HTTPException(404, "Module not found")

    user = _current_user(request)
    if not user:
        return RedirectResponse(f"/growth/login?next=/growth/module/{module_slug}", status_code=302)

    org = user["org"]
    if not can_access_module(module.id, org.get("plan", "free")):
        return RedirectResponse(f"/growth/profile?next=/growth/module/{module_slug}", status_code=302)

    # Lead Gen Pro module landing
    if module.id == "leadgen":
        body = _leadgen_module_html(user)
        return _page("Lead Gen Pro", body)

    # Generic module placeholder
    body = f"""
    <header class="border-b border-gray-800">
      <div class="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
        <a href="/growth" class="text-2xl font-bold tracking-tight">Leviathan <span class="text-emerald-400">Growth</span></a>
          <span class="text-gray-400">{_html.escape(user['user']['name'])}</span>
      </div>
    </header>
    <main class="max-w-4xl mx-auto px-4 py-12 text-center">
      <h1 class="text-3xl font-bold mb-4">{module.name}</h1>
      <p class="text-gray-400">Module interface loading...</p>
    </main>
    """
    return _page(module.name, body)


def _leadgen_module_html(user: Dict[str, Any]) -> str:
    return f"""
    <header class="border-b border-gray-800">
      <div class="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
        <a href="/growth" class="text-2xl font-bold tracking-tight">Leviathan <span class="text-emerald-400">Growth</span></a>
        <div class="flex items-center gap-4">
          <a href="/growth/profile" class="text-sm text-emerald-400 hover:underline">Profile</a>
          <span class="text-sm text-gray-400">{_html.escape(user['user']['name'])}</span>
        </div>
      </div>
    </header>
    <main class="max-w-6xl mx-auto px-4 py-12">
      <div class="text-center mb-12">
        <h1 class="text-4xl font-bold mb-4">Find developers who buy land</h1>
        <p class="text-xl text-gray-400">Target land developers, real estate investors, and home improvement buyers in any market.</p>
      </div>
      <div class="grid lg:grid-cols-2 gap-8">
        <div class="bg-gray-800 p-8 rounded-xl">
          <h2 class="text-2xl font-bold mb-4">Start a lead search</h2>
          <form id="search-form" class="space-y-4">
            <input type="text" id="location" placeholder="City, State or ZIP" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
            <select id="trade" class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
              <option value="land_developer">Land Developers</option>
              <option value="general_contracting">General Contractors</option>
              <option value="roofing">Roofing</option>
              <option value="hvac">HVAC</option>
              <option value="plumbing">Plumbing</option>
            </select>
            <button type="submit" class="w-full bg-emerald-500 hover:bg-emerald-600 text-white font-bold py-2 rounded">Search leads</button>
          </form>
          <div id="search-results" class="mt-6 space-y-3"></div>
        </div>
        <div class="bg-gray-800 p-8 rounded-xl">
          <h2 class="text-2xl font-bold mb-4">Capture an inbound lead</h2>
          <form action="/growth/api/capture" method="POST" class="space-y-3">
            <input type="text" name="full_name" placeholder="Full name" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
            <input type="email" name="email" placeholder="Email" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
            <input type="tel" name="phone" placeholder="Phone" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
            <input type="text" name="service_requested" placeholder="Service / trade needed" required class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
            <div class="grid grid-cols-3 gap-2">
              <input type="text" name="city" placeholder="City" class="bg-gray-700 border border-gray-600 rounded px-3 py-2">
              <input type="text" name="state" placeholder="State" class="bg-gray-700 border border-gray-600 rounded px-3 py-2">
              <input type="text" name="zip" placeholder="ZIP" class="bg-gray-700 border border-gray-600 rounded px-3 py-2">
            </div>
            <input type="text" name="budget_range" placeholder="Budget range (optional)" class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
            <textarea name="description" placeholder="Tell us about the project" rows="3" class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2"></textarea>
            <input type="hidden" name="source" value="growth_portal_leadgen">
            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 rounded">Submit lead</button>
          </form>
        </div>
      </div>
    </main>
    <script>
      document.getElementById('search-form').addEventListener('submit', async (e) => {{
        e.preventDefault();
        const location = document.getElementById('location').value;
        const trade = document.getElementById('trade').value;
        const res = await fetch('/api/scout/search', {{
          method: 'POST',
          headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{industry:trade, location:location, num_results:10}})
        }});
        const data = await res.json();
        const container = document.getElementById('search-results');
        container.innerHTML = '';
        if (!data.ok) {{ container.innerHTML = '<p class="text-red-400">'+ (data.error || 'Search failed') +'</p>'; return; }}
        (data.leads || []).forEach(l => {{
          container.innerHTML += `<div class="bg-gray-700 p-3 rounded"><div class="font-bold">${{l.title}}</div><div class="text-sm text-gray-300">${{l.snippet || ''}}</div></div>`;
        }});
      }});
    </script>
    """


# ───────────────────────────── API endpoints

@router.post("/api/register")
async def api_register(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else dict(await request.form())
    try:
        result = auth_manager.register(
            email=body.get("email", ""),
            password=body.get("password", ""),
            name=body.get("name", ""),
            org_name=body.get("org_name", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    resp = RedirectResponse("/growth/profile", status_code=302)
    resp.set_cookie("growth_token", result["token"], httponly=True, max_age=604800, samesite="lax")
    return resp


@router.post("/api/login")
async def api_login(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else dict(await request.form())
    try:
        result = auth_manager.login(
            email=body.get("email", ""),
            password=body.get("password", ""),
        )
    except ValueError as e:
        raise HTTPException(401, str(e))

    next_url = request.query_params.get("next", "/growth/")
    # Validate redirect URL to prevent open redirect attacks
    if not next_url.startswith("/growth/"):
        next_url = "/growth/"
    resp = RedirectResponse(next_url, status_code=302)
    resp.set_cookie("growth_token", result["token"], httponly=True, max_age=604800, samesite="lax")
    return resp


@router.post("/api/subscribe")
async def api_subscribe(request: Request):
    user = _require_user(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else dict(await request.form())
    plan = body.get("plan", "")
    module_id = body.get("module_id", "leadgen")

    module = get_module(module_id)
    if not module:
        raise HTTPException(404, "Module not found")

    stripe = StripeIntegration()
    if not stripe.is_configured:
        raise HTTPException(503, "Stripe is not configured")

    org_id = user["org_id"]
    success_url = f"{request.url_for('portal_home')}?subscribed={plan}"
    cancel_url = f"{request.url_for('profile_page')}?canceled=1"

    session = await stripe.create_checkout_session(plan, org_id, str(success_url), str(cancel_url))
    return RedirectResponse(session["url"], status_code=303)


@router.get("/api/billing-portal")
async def api_billing_portal(request: Request):
    user = _require_user(request)
    stripe = StripeIntegration()
    if not stripe.is_configured:
        raise HTTPException(503, "Stripe is not configured")

    return_url = str(request.url_for("profile_page"))
    session = await stripe.create_billing_portal(user["org_id"], return_url)
    return RedirectResponse(session["url"], status_code=303)


@router.get("/api/me")
async def api_me(request: Request):
    user = _require_user(request)
    return {
        "user": user["user"],
        "org": user["org"],
    }


@router.get("/api/modules")
async def api_modules(request: Request):
    user = _current_user(request)
    plan = user.get("org", {}).get("plan", "free") if user else "free"
    return [
        {**m, "access": can_access_module(m["id"], plan)}
        for m in list_modules()
    ]


@router.post("/api/capture")
async def api_capture(request: Request):
    """Public lead capture form → normalized lead → CRM webhook."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else dict(await request.form())

    lead_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    lead = {
        "lead_id": lead_id,
        "source": body.get("source", "growth_portal"),
        "capture_timestamp": now,
        "full_name": body.get("full_name", ""),
        "first_name": body.get("full_name", "").split()[0] if body.get("full_name") else "",
        "last_name": " ".join(body.get("full_name", "").split()[1:]) if len(body.get("full_name", "").split()) > 1 else "",
        "email": body.get("email", ""),
        "phone": body.get("phone", ""),
        "company_name": body.get("company_name", ""),
        "service_requested": body.get("service_requested", ""),
        "description": body.get("description", ""),
        "city": body.get("city", ""),
        "state": body.get("state", ""),
        "zip": body.get("zip", ""),
        "geo_score": 0,
        "urgency_score": 0,
        "budget_fit_score": 0,
        "service_fit_score": 0,
        "lead_value_score": 0,
        "status": "new",
        "next_action": "Qualify and respond within 5 minutes",
        "utm_source": body.get("utm_source", ""),
        "utm_medium": body.get("utm_medium", ""),
        "utm_campaign": body.get("utm_campaign", ""),
        "budget_range": body.get("budget_range", ""),
        "consent_flags": {"email": True, "sms": True, "call": True},
        "notes": [f"Captured from {body.get('source','growth_portal')}"],
    }

    # Store in database
    with Database.get_connection() as conn:
        conn.execute("""
            INSERT INTO leads (id, title, url, snippet, industry, location, source, score, found_at, email, phone, notes, score_breakdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lead_id,
            lead.get("full_name", ""),
            "",
            lead.get("description", "")[:300],
            lead.get("service_requested", ""),
            f"{lead.get('city','')}, {lead.get('state','')} {lead.get('zip','')}".strip(", "),
            lead.get("source", ""),
            0,
            now,
            lead.get("email", ""),
            lead.get("phone", ""),
            json.dumps(lead.get("notes", [])),
            json.dumps({}),
        ))
        conn.commit()

    # Trigger CRM webhook / follow-up
    await _push_to_crm(lead)
    await _queue_followup(lead)

    # If browser form POST, redirect to thank-you page
    if not request.headers.get("content-type", "").startswith("application/json"):
        return RedirectResponse("/growth/thank-you", status_code=302)

    return {"ok": True, "lead_id": lead_id, "status": "captured"}


@router.get("/thank-you", response_class=HTMLResponse)
async def thank_you_page(request: Request):
    body = """
    <div class="min-h-screen flex items-center justify-center px-4 text-center">
      <div class="bg-gray-800 p-8 rounded-xl max-w-lg">
        <div class="text-5xl mb-4">✅</div>
        <h1 class="text-2xl font-bold mb-2">Lead received</h1>
        <p class="text-gray-400 mb-6">A member of our team will reach out within minutes.</p>
        <a href="/growth" class="inline-block bg-emerald-500 hover:bg-emerald-600 text-white px-6 py-2 rounded font-semibold">Back to portal</a>
      </div>
    </div>
    """
    return _page("Thank you", body)


async def _push_to_crm(lead: Dict[str, Any]):
    """Push captured lead to CRM via existing crm_push + internal webhook."""
    from ..crm_push import CrmPush
    try:
        crm = CrmPush()
        await crm.push_lead(lead)
    except Exception as e:
        logger.warning("CRM push failed for lead %s: %s", lead.get("lead_id"), e)

    # Internal webhook notification (n8n-ready)
    webhook_url = KeyVault.get("lead_webhook_url") or ""
    if webhook_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(webhook_url, json=lead)
        except Exception as e:
            logger.warning("Lead webhook POST failed: %s", e)


async def _queue_followup(lead: Dict[str, Any]):
    """Queue immediate follow-up sequence."""
    from ..nurture import NurtureEngine
    try:
        engine = NurtureEngine()
        await engine.start_sequence(lead)
    except Exception as e:
        logger.warning("Follow-up queue failed for lead %s: %s", lead.get("lead_id"), e)
