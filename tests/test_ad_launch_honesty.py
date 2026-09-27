"""Regression tests: the ad launcher must never fabricate a success (audit C-3).

Before the fix, POST /api/ads/platforms/launch returned HTTP 200 with ok=True and a
real-looking `camp_...` id while the provider reported simulated=True, and the UI
alerted "Campaign created!".

All of these run with NO ad credentials, which is exactly the condition that
previously produced the lie.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

LAUNCH = "/api/ads/platforms/launch"
PAYLOAD = {
    "platform": "google",
    "name": "REGRESSION-TEST-CAMPAIGN",
    "industry": "roofing",
    "location": "Austin, TX",
    "budget_cents": 1000,
    "daily_budget": 10,
    "usp": "fast estimates",
    "count": 1,
    "objective": "leads",
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c


def test_launch_does_not_fabricate_campaign_id(client):
    """With no ad credentials the result must be flagged simulated, and the id must
    NOT look like a real created campaign."""
    r = client.post(LAUNCH, json=PAYLOAD)
    assert r.status_code == 200, r.text[:300]
    d = r.json()

    # The truth must be visible at the TOP level so the UI can see it.
    assert "simulated" in d, f"top-level 'simulated' missing: {sorted(d)}"
    assert d["simulated"] is True, (
        f"expected simulated=True with no ad credentials, got ok={d.get('ok')} "
        f"simulated={d.get('simulated')}"
    )


def test_launch_does_not_claim_ok_when_simulated(client):
    """`ok` must be derived from the provider, not hard-coded True."""
    r = client.post(LAUNCH, json=PAYLOAD)
    d = r.json()
    if d.get("simulated"):
        assert d.get("ok") is False, (
            f"ok must not be True when simulated; got ok={d.get('ok')!r}"
        )


def test_simulated_campaign_id_is_not_a_created_campaign(client):
    """A preview id must be distinguishable from a created campaign id."""
    r = client.post(LAUNCH, json=PAYLOAD)
    d = r.json()
    cid = d.get("campaign_id", "")
    if d.get("simulated"):
        assert not cid.startswith("camp_"), (
            f"simulated launch must not mint a real-looking 'camp_' id, got {cid!r}"
        )
        assert cid.startswith("preview_"), f"expected preview_ id, got {cid!r}"


def test_simulated_launch_persists_as_simulated(client):
    """The DB row must say 'simulated', not 'created' -- otherwise the campaign list
    shows a phantom live campaign."""
    from engine.database import Database

    r = client.post(LAUNCH, json=PAYLOAD)
    d = r.json()
    if not d.get("simulated"):
        pytest.skip("ad credentials present; this is the preview-path regression only")

    cid = d["campaign_id"]
    with Database.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM ad_campaigns WHERE campaign_id = ?", (cid,)
        ).fetchone()
    assert row is not None, f"expected a persisted row for {cid}"
    assert row["status"] == "simulated", (
        f"persisted status must be 'simulated', got {row['status']!r}"
    )


def test_ui_source_does_not_alert_campaign_created_unconditionally():
    """Guard the frontend: the success alert must be behind a simulated check."""
    from pathlib import Path
    html = Path(__file__).resolve().parents[1] / "static" / "index.html"
    src = html.read_text(encoding="utf-8")
    i = src.find("/api/ads/platforms/launch")
    assert i != -1, "launch call not found in index.html"
    window = src[i:i + 1400]
    assert "data.simulated" in window, (
        "UI must branch on data.simulated before announcing a created campaign"
    )
    # the bare unconditional alert must not survive
    assert "alert('Campaign created! ' + (data.campaign_id || ''))" in window
    assert window.index("data.simulated") < window.index("alert('Campaign created!"), (
        "the simulated check must come BEFORE the success alert"
    )
