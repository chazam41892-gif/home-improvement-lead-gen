def test_get_trades(client):
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 44


def test_get_trade_detail(client):
    resp = client.get("/api/trades/plumbing")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trade_id"] == "plumbing"


def test_get_trade_revenue(client):
    resp = client.get("/api/trades/revenue")
    assert resp.status_code == 200


def test_get_crm_analytics(client):
    resp = client.get("/api/crm/analytics")
    assert resp.status_code == 200


def test_get_settings(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["exa_key_configured"] is False
    assert data["perplexity_key_configured"] is False


def test_get_routing_config(client):
    resp = client.get("/api/routing/config")
    assert resp.status_code == 200


def test_get_stats(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200


def test_get_nurture_stats(client):
    resp = client.get("/api/nurture/stats")
    assert resp.status_code == 200


def test_get_leads(client):
    resp = client.get("/api/leads")
    assert resp.status_code == 200


def test_get_schedules(client):
    resp = client.get("/api/schedules")
    assert resp.status_code == 200


def test_create_schedule(client):
    resp = client.post("/api/schedules", json={"query": "plumber in Austin"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


def test_crm_sync_lead(client):
    resp = client.post("/api/crm/sync_lead", json={
        "lead_name": "John Doe",
        "business": "Test Plumbing Co",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "synced"


def test_trade_convert(client):
    resp = client.post("/api/trades/convert", json={
        "trade": "plumbing",
        "business_name": "Test Plumbing Co",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "lead" in data
    assert "account" in data
    assert "payment" in data
    assert "subscription" in data


def test_discover_trade_missing_params(client):
    resp = client.post("/api/trades/discover", json={})
    assert resp.status_code == 400


def test_search_multi(client):
    resp = client.post("/api/search/multi", json={"query": "plumber in Austin"})
    assert resp.status_code == 200


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "uptime_sec" in data
    assert "auth_enabled" in data
    assert "stripe_configured" in data


def test_leads_pagination(client):
    resp = client.get("/api/leads?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "returned" in data
    assert "offset" in data
    assert "limit" in data
