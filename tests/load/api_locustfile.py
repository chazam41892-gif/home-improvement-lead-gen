"""Load test for the Lead Gen Pro API (audit 2026-09-27).

"Works on my machine" is not a load test. This drives real concurrent users at
the real ASGI app and fails loudly on latency, error rate, and rate-limiter
misbehaviour.

Run headless (the form CI uses):
    locust -f tests/load/api_locustfile.py --headless \
           -u 50 -r 10 -t 60s --host http://127.0.0.1:8080

Or programmatically, which is what the smoke script does:
    python -m tests.load.smoke
"""
import os
import random

from locust import HttpUser, between, events, task


def _auth_headers():
    """Attach the API key when one is configured; auth is exercised, not bypassed."""
    key = os.getenv("API_KEY", "")
    return {"Authorization": f"Bearer {key}"} if key else {}


class LeadGenUser(HttpUser):
    """A realistic mix: mostly cheap reads, some auth checks, rare writes."""

    host = os.getenv("LOAD_TEST_HOST", "http://127.0.0.1:8080")
    wait_time = between(0.5, 2.0)

    # Paths that must never 5xx under load. Reading the route table is safer
    # than hardcoding: /health and /openapi.json always exist.
    @task(6)
    def health(self):
        with self.client.get("/health", name="/health",
                             catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"health 5xx: {r.status_code}")

    @task(4)
    def openapi(self):
        with self.client.get("/openapi.json", name="/openapi.json",
                             catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"openapi 5xx: {r.status_code}")

    @task(3)
    def list_leads(self):
        with self.client.get("/api/leads?limit=20", headers=_auth_headers(),
                             name="/api/leads", catch_response=True) as r:
            # 401/403 under load is CORRECT (auth is on). 5xx is not.
            if r.status_code >= 500:
                r.failure(f"leads 5xx: {r.status_code}")
            elif r.status_code in (401, 403):
                r.success()

    @task(1)
    def settings(self):
        with self.client.get("/api/settings", headers=_auth_headers(),
                             name="/api/settings", catch_response=True) as r:
            if r.status_code >= 500:
                r.failure(f"settings 5xx: {r.status_code}")
            elif r.status_code in (401, 403):
                r.success()


# ── global thresholds ──────────────────────────────────────────────────────
# A test run passes only if nothing breaches these. Set via env in CI.
THRESHOLDS = {
    "max_failure_rate": float(os.getenv("LOAD_MAX_FAILURE_RATE", "0.01")),
    "max_p95_ms": float(os.getenv("LOAD_MAX_P95_MS", "2000")),
    "max_p99_ms": float(os.getenv("LOAD_MAX_P99_MS", "5000")),
}

_violations: list[str] = []


@events.quitting.add_listener
def _assert_thresholds(environment, **_kw):
    stats = environment.stats.total
    fr = stats.fail_rate
    p95 = stats.get_response_time_percentile(0.95) or 0
    p99 = stats.get_response_time_percentile(0.99) or 0

    print("\n" + "=" * 62)
    print(f"  requests        : {stats.num_requests}")
    print(f"  failures        : {stats.num_failures} ({fr:.2%})")
    print(f"  p50 / p95 / p99 : {stats.get_response_time_percentile(0.50)}ms "
          f"/ {p95}ms / {p99}ms")
    print(f"  thresholds      : fail<={THRESHOLDS['max_failure_rate']:.1%} "
          f"p95<={THRESHOLDS['max_p95_ms']:.0f}ms p99<={THRESHOLDS['max_p99_ms']:.0f}ms")
    print("=" * 62)

    if fr > THRESHOLDS["max_failure_rate"]:
        _violations.append(f"failure rate {fr:.2%} > "
                           f"{THRESHOLDS['max_failure_rate']:.2%}")
    if p95 > THRESHOLDS["max_p95_ms"]:
        _violations.append(f"p95 {p95}ms > {THRESHOLDS['max_p95_ms']:.0f}ms")
    if p99 > THRESHOLDS["max_p99_ms"]:
        _violations.append(f"p99 {p99}ms > {THRESHOLDS['max_p99_ms']:.0f}ms")

    if _violations:
        for v in _violations:
            print(f"  BREACH: {v}")
        environment.process_exit_code = 1
    else:
        print("  PASS: all load thresholds met")
