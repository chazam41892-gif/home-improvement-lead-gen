"""Smoke test — verifies all production-grade features work end-to-end."""
import os
os.environ["API_KEY"] = "test-key-123"
os.environ["EXA_API_KEY"] = ""
os.environ["PERPLEXITY_API_KEY"] = ""
os.environ["JWT_SECRET"] = "ci-test-secret-do-not-use-in-production"

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
passed = 0
failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}: {detail}")

# 1. Health
r = client.get("/health")
check("Health endpoint", r.status_code == 200 and r.json()["status"] == "ok")

# 2. Trades count
r = client.get("/api/trades")
check("45 trades returned", len(r.json()["trades"]) == 45)

# 3. Auth blocks unauthenticated
r = client.get("/api/leads")
check("Auth blocks no-key", r.status_code == 401)

# 4. Auth accepts valid key
r = client.get("/api/leads", headers={"Authorization": "Bearer test-key-123"})
check("Auth accepts valid key", r.status_code == 200)

# 5. Auth rejects wrong key
r = client.get("/api/leads", headers={"Authorization": "Bearer wrong-key"})
check("Auth rejects wrong key", r.status_code == 401)

# 6. Pagination
r = client.get("/api/leads?limit=10&offset=0", headers={"Authorization": "Bearer test-key-123"})
data = r.json()
check("Pagination has total", "total" in data)
check("Pagination has offset", data["offset"] == 0)
check("Pagination has limit", data["limit"] == 10)

# 7. Settings (requires auth)
r = client.get("/api/settings", headers={"Authorization": "Bearer test-key-123"})
s = r.json()
check("Settings endpoint", r.status_code == 200)
check("Exa not configured", s["exa_key_configured"] is False)

# 8. Trade detail
r = client.get("/api/trades/plumbing")
check("Trade detail Plumbing", r.json()["config"]["name"] == "Plumbing")

# 9. Search without keys fails gracefully
r = client.post(
    "/api/search/natural",
    json={"query": "plumber in Austin"},
    headers={"Authorization": "Bearer test-key-123"},
)
check("Search fails gracefully with useful message", r.status_code == 400 or ("error" in r.json() and "not configured" in r.json().get("error", r.json().get("detail", ""))))

# 10. Lead capture (public)
r = client.post("/api/capture/lead", json={"name": "Test User", "address": "97401", "service": "plumbing"})
check("Lead capture succeeds", r.status_code == 200 and r.json().get("ok"))

# 11. Revenue
r = client.get("/api/trades/revenue")
check("Revenue stats", r.status_code == 200 and "stats" in r.json())

# 12. Discover trade (with auth)
r = client.post(
    "/api/trades/discover",
    json={"trade": "plumbing", "location": "Eugene, OR"},
    headers={"Authorization": "Bearer test-key-123"},
)
check("Trade discover endpoint reachable", r.status_code in (200, 400))  # 400 if no Exa key

# 13. Convert lead
r = client.post(
    "/api/trades/convert",
    json={"trade": "plumbing", "business_name": "Test Plumbing Co"},
    headers={"Authorization": "Bearer test-key-123"},
)
check("Lead conversion pipeline", r.status_code == 200 and r.json().get("ok"))

# 14. All trades in every trade endpoint
r = client.get("/api/trades", headers={"Authorization": "Bearer test-key-123"})
check("Trades endpoint returns all 45", len(r.json()["trades"]) == 45)

print(f"\n{'='*40}")
print(f"RESULTS: {passed} passed, {failed} failed out of {passed+failed}")
if failed == 0:
    print("ALL PRODUCTION-GRADE FEATURES VERIFIED")
else:
    print(f"{failed} checks FAILED — review above")
print(f"{'='*40}")
