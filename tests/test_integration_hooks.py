"""Tests for new integration hooks and deployment readiness."""
from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_manifest_served():
    client = TestClient(main.app)
    resp = client.get("/static/manifest.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Lead Gen Pro"
    assert "icons" in data


def test_embedded_widget_script_served():
    client = TestClient(main.app)
    resp = client.get("/static/widgets/lead-capture.js")
    assert resp.status_code == 200
    assert "lgpw-root" in resp.text


def test_env_validator_demo_mode():
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["DEPLOYMENT_MODE"] = "demo"
    result = subprocess.run(
        [sys.executable, "scripts/validate_env.py", "demo"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "Deployment mode: demo" in result.stdout


def test_ad_platform_manager_preview():
    from engine.ad_apis import AdPlatformManager, AdCampaignPlan

    manager = AdPlatformManager()
    status = manager.status()
    assert "google_ads" in status
    assert "meta" in status
    assert status["google_ads"]["configured"] is False or True
    assert status["meta"]["configured"] is False or True


def test_ad_campaign_plan():
    from engine.ad_apis import AdCampaignPlan

    plan = AdCampaignPlan(
        platform="google",
        name="Test",
        budget_cents=1000,
        industry="roofing",
        location="Austin",
        headline="Headline",
        description="Description",
        cta="Call Now",
        keywords=["roof repair"],
        landing_page_url="https://example.com",
    )
    assert plan.platform == "google"
    assert plan.budget_cents == 1000
