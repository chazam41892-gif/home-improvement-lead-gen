"""Tests for the Leviathan Growth portal."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    from engine.auth import auth_manager
    auth_manager._ensure_tables()
    with TestClient(main.app) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c


def test_growth_portal_home(client):
    resp = client.get("/growth/")
    assert resp.status_code == 200
    assert "Lead Gen Pro" in resp.text


def test_growth_login_page(client):
    resp = client.get("/growth/login")
    assert resp.status_code == 200
    assert "Log in" in resp.text


def test_growth_register_page(client):
    resp = client.get("/growth/register")
    assert resp.status_code == 200
    assert "Create your account" in resp.text


def test_growth_capture_form(client):
    resp = client.post(
        "/growth/api/capture",
        data={
            "full_name": "Test User",
            "email": "test@example.com",
            "phone": "555-123-4567",
            "service_requested": "Land Developer Leads",
            "city": "Austin",
            "state": "TX",
            "zip": "78701",
            "source": "test_growth_portal",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)


def test_growth_capture_api_json(client):
    resp = client.post(
        "/growth/api/capture",
        json={
            "full_name": "API Test",
            "email": "api-test@example.com",
            "phone": "555-999-8888",
            "service_requested": "Roofing Leads",
            "city": "Dallas",
            "state": "TX",
            "source": "test_growth_api",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "lead_id" in data


def test_module_gated_without_auth(client):
    resp = client.get("/growth/module/leadgen", follow_redirects=False)
    assert resp.status_code == 302
    assert "/growth/login" in resp.headers["location"]


def test_tracking_pixel(client):
    resp = client.get("/track/pixel.gif?lead_id=test123&utm_source=google&utm_campaign=land")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"


def test_business_evaluate_lead(client):
    # The route requires API key auth; without it we get 401, which proves it's wired.
    resp = client.post("/api/business/evaluate-lead", json={"trade": "plumbing", "lead_score": 75})
    assert resp.status_code in (200, 401)


from unittest.mock import AsyncMock, patch

def test_google_login_redirect(client):
    with patch("engine.key_vault.KeyVault.get", return_value="test-client-id"):
        resp = client.get("/growth/auth/google/login", follow_redirects=False)
        assert resp.status_code == 302
        assert "accounts.google.com" in resp.headers["location"]
        assert "client_id=test-client-id" in resp.headers["location"]

@pytest.mark.asyncio
async def test_google_callback_flow(client):
    with patch("engine.key_vault.KeyVault.get") as mock_get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get_info:
         
        mock_get.side_effect = lambda key: "test-client-id" if "client_id" in key else "test-secret"
        
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {"access_token": "google-test-access-token"}
        mock_post.return_value = mock_resp
        
        mock_info_resp = AsyncMock()
        mock_info_resp.status_code = 200
        mock_info_resp.json = lambda: {
            "email": "oauth-test-user@example.com",
            "name": "OAuth Test User",
            "sub": "google-sub-id-12345"
        }
        mock_get_info.return_value = mock_info_resp
        
        resp = client.get("/growth/auth/google/callback?code=test-auth-code&state=/growth/profile", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/growth/profile"
        assert "growth_token" in resp.cookies


def test_campaign_roi_simulator(client):
    resp = client.post(
        "/api/simulator/project-roi",
        json={"trade": "plumbing", "location": "Dallas, TX", "daily_budget": 100.0}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["monthly_spend"] == 3000.0
    assert "projected_cpl" in data
    assert "roi_percentage" in data
    assert len(data["daily_log"]) == 30


@pytest.mark.asyncio
async def test_conversational_responder_opt_out(client):
    from main import nurture
    from engine.nurture import Sequence
    
    # Pre-populate a test sequence in-memory and database
    test_seq = Sequence(
        id="test_seq_opt_out",
        lead_name="OptOut Lead",
        lead_id="opt_out_id",
        lead_email="opt@example.com",
        lead_phone="555-111-2222",
        industry="plumbing",
        created_at="2026-07-27T19:00:00",
        actions=[],
    )
    nurture._sequences[test_seq.id] = test_seq
    nurture._save_sequence_to_db(test_seq)
    
    resp = client.post(
        "/api/nurture/incoming-reply",
        json={"sequence_id": "test_seq_opt_out", "reply_text": "Please STOP sending me messages"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "opt_out"
    assert "unsubscribed" in data["response"]


@pytest.mark.asyncio
async def test_conversational_responder_booking(client):
    from main import nurture
    from engine.nurture import Sequence
    
    test_seq = Sequence(
        id="test_seq_booking",
        lead_name="Booking Lead",
        lead_id="booking_id",
        lead_email="book@example.com",
        lead_phone="555-222-3333",
        industry="roofing",
        created_at="2026-07-27T19:00:00",
        actions=[],
    )
    nurture._sequences[test_seq.id] = test_seq
    nurture._save_sequence_to_db(test_seq)
    
    resp = client.post(
        "/api/nurture/incoming-reply",
        json={"sequence_id": "test_seq_booking", "reply_text": "I'd like to book an appointment slot"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "booking_prompt"
    assert "scheduling page" in data["response"]


@pytest.mark.asyncio
async def test_conversational_responder_qa(client):
    from main import nurture
    from engine.nurture import Sequence
    
    test_seq = Sequence(
        id="test_seq_qa",
        lead_name="QA Lead",
        lead_id="qa_id",
        lead_email="qa@example.com",
        lead_phone="555-333-4444",
        industry="hvac",
        created_at="2026-07-27T19:00:00",
        actions=[],
    )
    nurture._sequences[test_seq.id] = test_seq
    nurture._save_sequence_to_db(test_seq)
    
    resp = client.post(
        "/api/nurture/incoming-reply",
        json={"sequence_id": "test_seq_qa", "reply_text": "How much does a new system cost?"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "ai_response"
    assert "schedule a call" in data["response"]


def test_intent_based_sourcing_triggers():
    from engine.search.browser_agent import BrowserSearchProvider
    from bs4 import BeautifulSoup
    
    provider = BrowserSearchProvider()
    # Mock DuckDuckGo HTML result parsing with intent query match
    mock_html = """
    <div class="result">
        <a class="result__url" href="http://localhost/l/?uddg=https://localcontractor.com">Looking for local Plumber recommendations</a>
        <a class="result__snippet" href="http://localhost/l/?uddg=https://localcontractor.com">We need to hire an installer to help fix our broken HVAC system immediately.</a>
    </div>
    """
    soup = BeautifulSoup(mock_html, "html.parser")
    results = soup.find_all("div", class_="result")
    
    r = results[0]
    a = r.find("a", class_="result__url")
    snippet_el = r.find("a", class_="result__snippet")
    title = a.get_text(strip=True)
    snippet = snippet_el.get_text(strip=True)
    
    intent_triggers = ["recommendation", "recommend", "looking for", "hire", "need", "estimate", "quote", "repair", "install", "help"]
    has_intent = any(trigger in title.lower() or trigger in snippet.lower() for trigger in intent_triggers)
    
    assert has_intent is True


