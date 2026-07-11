"""Tests for the Leviathan Growth portal."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app)


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
