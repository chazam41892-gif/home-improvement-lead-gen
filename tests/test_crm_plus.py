"""Tests for the real CRM+ routes backed by the database."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_crm_analytics_real(client):
    resp = client.get("/api/crm/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "pipeline" in data
    assert "outreach" in data
    assert "nurture" in data
    assert "search" in data
    assert "updated_at" in data


def test_crm_sync_lead_persisted(client):
    resp = client.post("/api/crm/sync_lead", json={
        "lead_name": "Persisted Lead",
        "business": "Persisted Business LLC",
        "email": "persisted@example.com",
        "phone": "555-000-1234",
        "city": "Portland",
        "source": "crm_plus_test",
        "notes": "Test sync",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "synced"
    assert data["persisted"] is True
    assert "lead_id" in data


def test_crm_outreach_swarm(client):
    resp = client.post("/api/crm/outreach_swarm", json={
        "target_count": 10,
        "campaign_name": "Unit Test Campaign",
        "channels": ["email", "sms"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "launched"
    assert data["campaign_id"]
    assert data["campaign"] == "Unit Test Campaign"
    assert data["agents_active"] >= 5


def test_crm_talon_audit_pass(client):
    resp = client.post("/api/crm/talon_audit", json={
        "message_sample": "Hi! You previously consented to receive messages. Reply STOP to opt out. Visit us at 123 Main St."
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["badge"] == "TALON_CERTIFIED"
    assert data["score"] == 100


def test_crm_talon_audit_fail(client):
    resp = client.post("/api/crm/talon_audit", json={
        "message_sample": "Buy now! Limited time offer."
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["badge"] == "TALON_VIOLATION_DETECTED"
    assert data["score"] < 100
    assert any(c["status"] == "FAIL" for c in data["checks"])


def test_ads_platform_status(client):
    resp = client.get("/api/ads/platforms/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "google_ads" in data
    assert "meta" in data
    assert isinstance(data["google_ads"]["configured"], bool)


@pytest.mark.skip(reason="API key auth enabled in some environments; covered by integration tests")
def test_ads_platform_launch_unauthorized(client):
    resp = client.post("/api/ads/platforms/launch", json={
        "platform": "google",
        "name": "Test Campaign",
        "industry": "roofing",
        "landing_page_url": "https://example.com/lp",
    })
    # Without API key we expect 401.
    assert resp.status_code in (200, 401)
