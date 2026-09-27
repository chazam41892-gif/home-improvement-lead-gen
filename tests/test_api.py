def test_get_trades(client):
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 45


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


def test_vault_list_keys(client):
    resp = client.get("/api/vault/keys")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "exa" in data
    assert "anthropic" in data
    assert "stripe_secret" in data


def test_vault_set_and_delete_key(client):
    resp = client.post("/api/vault/keys/exa", json={"key": "test_key_abc123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["service"] == "exa"

    resp = client.post("/api/vault/keys/unknown_service", json={"key": "test"})
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data

    resp = client.delete("/api/vault/keys/exa")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    resp = client.delete("/api/vault/keys/unknown_service")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


def test_vault_delete_nonexistent(client):
    resp = client.delete("/api/vault/keys/clearbit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


def test_enrich_providers(client):
    resp = client.get("/api/enrich/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "providers" in data
    assert "available" in data
    names = [p["name"] for p in data["providers"]]
    assert "exa_enricher" in names


def test_enrich_lead_missing_params(client):
    resp = client.post("/api/enrich/lead", json={})
    assert resp.status_code == 400


def test_enrich_lead(client):
    resp = client.post("/api/enrich/lead", json={
        "business_name": "Test Plumbing Co",
        "trade": "plumbing",
        "location": "Austin, TX",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "business_name" in data
    assert "confidence" in data


def test_enrich_batch(client):
    resp = client.post("/api/enrich/batch", json={
        "leads": [
            {"business_name": "Plumber One", "trade": "plumbing", "location": "Austin, TX"},
            {"business_name": "Electrician One", "trade": "electrical", "location": "Austin, TX"},
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "results" in data
    assert "total" in data
    assert len(data["results"]) == 2
    for item in data["results"]:
        assert "business_name" in item


def test_enrich_from_lead_not_found(client):
    resp = client.get("/api/enrich/from-lead/nonexistent_123")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data or "detail" in data


def test_vault_page_served(client):
    resp = client.get("/vault")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_enrich_routing_info(client):
    resp = client.get("/api/enrich/routing")
    assert resp.status_code == 200
    data = resp.json()
    assert "routing_mode" in data
    assert "router" in data
    assert "providers" in data
    assert data["routing_mode"] == "parallel"


def test_enrich_lead_smart_routing(client):
    resp = client.post("/api/enrich/lead?routing_mode=smart", json={
        "business_name": "Test Plumbing Co",
        "trade": "plumbing",
        "location": "Austin, TX",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "business_name" in data
    assert "confidence" in data


def test_enrich_batch_smart_routing(client):
    resp = client.post("/api/enrich/batch?routing_mode=smart", json={
        "leads": [
            {"business_name": "Plumber One", "trade": "plumbing", "location": "Austin, TX"},
            {"business_name": "Electrician One", "trade": "electrical", "location": "Austin, TX"},
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert len(data["results"]) == 2


def test_chat_collaborate_fallback_responses(client):
    # 1. ROI/simulate trigger
    resp = client.post("/api/chat/collaborate", json={"message": "Please run a simulate and ROI check"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "simulate a specific trade" in data["response"]

    # 2. Search/find trigger
    resp = client.post("/api/chat/collaborate", json={"message": "Can you search for leads?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "Search Page" in data["response"]

    # 3. Vertical/industry trigger
    resp = client.post("/api/chat/collaborate", json={"message": "Show me the industry configuration"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "Verticals Page" in data["response"]

    # 4. Vault/key trigger
    resp = client.post("/api/chat/collaborate", json={"message": "Where are keys stored?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "Key Vault" in data["response"]

    # 5. Default greeting trigger
    resp = client.post("/api/chat/collaborate", json={"message": "Hello there"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "LeadForge AI Copilot" in data["response"]

    # 6. Missing message validation
    resp = client.post("/api/chat/collaborate", json={})
    assert resp.status_code == 400


def test_chat_collaborate_perplexity_mocked(client):
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "This is a mocked response from Perplexity AI."
                }
            }
        ]
    }

    async def mock_post(*args, **kwargs):
        return mock_resp

    with patch("engine.key_vault.KeyVault.get", return_value="mock-perplexity-key"), \
         patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_http_post:
        
        resp = client.post("/api/chat/collaborate", json={"message": "How is the weather?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["response"] == "This is a mocked response from Perplexity AI."
        
        # Verify KeyVault lookup was performed
        mock_http_post.assert_called_once()

