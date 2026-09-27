"""Tests for main.py's auth, rate limiting, and endpoint surface (audit 2026-09-27).

main.py is 1,098 statements at 39% coverage. The security-critical paths --
API key verification, the token bucket, and the health contract -- are what this
file pins down. These assert real behaviour, not import smoke.
"""
import time

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app)


# ── token bucket ───────────────────────────────────────────────────────────
def test_bucket_starts_full():
    b = main.TokenBucket(rate=10.0, burst=5)
    assert b.tokens == 5.0


def test_bucket_allows_burst_then_refuses():
    b = main.TokenBucket(rate=0.0001, burst=3)  # effectively frozen
    assert [b.consume() for _ in range(3)] == [True, True, True]
    assert b.consume() is False, "the 4th call must be refused"


def test_bucket_refills_over_time():
    b = main.TokenBucket(rate=100.0, burst=2)
    b.consume(); b.consume()
    assert b.consume() is False
    time.sleep(0.05)          # 100/s * 0.05s = 5 tokens
    assert b.consume() is True, "must refill with elapsed time"


def test_bucket_never_exceeds_burst():
    b = main.TokenBucket(rate=1000.0, burst=3)
    time.sleep(0.1)           # would refill 100 tokens if uncapped
    assert b.tokens <= 3.0, b.tokens


def test_bucket_honours_fractional_cost():
    b = main.TokenBucket(rate=0.0001, burst=10)
    assert b.consume(3.0) is True
    assert b.tokens == pytest.approx(7.0)


# ── api key verification ───────────────────────────────────────────────────
class _FakeRequest:
    def __init__(self, headers=None, host="1.2.3.4"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()
        self.state = type("S", (), {})()


def test_verify_api_key_rejects_when_server_has_no_key(monkeypatch):
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "", raising=False)
    with pytest.raises(Exception) as exc:
        main.verify_api_key(_FakeRequest())
    assert "not configured" in str(exc.value)


def test_verify_api_key_accepts_the_static_key(monkeypatch):
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "secret", raising=False)
    assert main.verify_api_key(
        _FakeRequest({"Authorization": "Bearer secret"})) is True


def test_verify_api_key_rejects_a_wrong_key(monkeypatch):
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "secret", raising=False)
    with pytest.raises(Exception) as exc:
        main.verify_api_key(_FakeRequest({"Authorization": "Bearer wrong"}))
    assert "invalid" in str(exc.value).lower()


def test_verify_api_key_rejects_a_missing_header(monkeypatch):
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "secret", raising=False)
    with pytest.raises(Exception):
        main.verify_api_key(_FakeRequest({}))


def test_verify_api_key_rejects_malformed_scheme(monkeypatch):
    """'Basic ...' or a bare token must not be treated as a Bearer credential."""
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "secret", raising=False)
    for header in ("Basic secret", "secret", "Bearer", "bearer secret"):
        with pytest.raises(Exception):
            main.verify_api_key(_FakeRequest({"Authorization": header}))


# ── rate limiting endpoint behaviour ───────────────────────────────────────
def _hammer(fn, req, limit=400):
    """Call until it refuses. Returns the exception message. Burst is 20, so
    early calls legitimately succeed -- the test must tolerate that."""
    for _ in range(limit):
        try:
            fn(req)
        except Exception as exc:  # HTTPException carries the 429
            return str(exc)
    raise AssertionError("never rate limited -- the limiter is not engaging")


def test_rate_limiter_raises_429_when_exhausted():
    """The limiter must actually throttle, not just exist."""
    main._buckets.clear()
    msg = _hammer(main.rate_limit, _FakeRequest({"Authorization": "Bearer spammer"}))
    assert "Rate limit" in msg, msg


def test_rate_limit_buckets_are_isolated_per_caller():
    main._buckets.clear()
    spammer = _FakeRequest({"Authorization": "Bearer a"}, host="1.1.1.1")
    bystander = _FakeRequest({"Authorization": "Bearer b"}, host="2.2.2.2")

    assert "Rate limit" in _hammer(main.rate_limit, spammer)

    # A different caller must still have their full, untouched budget of 20.
    # (Calling it more than the burst is not isolation failing -- that is the
    # limiter working. So stay inside the burst.)
    for _ in range(15):
        main.rate_limit(bystander)   # must never raise here


# ── health & public surface ────────────────────────────────────────────────
def test_health_is_reachable(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    assert "status" in r.json(), r.json()


def test_openapi_schema_builds(client):
    """A schema that will not build is a broken deploy, not a test artifact."""
    r = client.get("/openapi.json")
    assert r.status_code == 200, r.text
    paths = r.json()["paths"]
    assert len(paths) > 20, f"only {len(paths)} routes registered"
    assert "/api/search" in paths, "the core search route is missing"


def test_core_routes_are_registered(client):
    paths = client.get("/openapi.json").json()["paths"]
    for expected in ("/api/leads", "/api/settings", "/api/routing/config"):
        assert expected in paths, f"{expected} not registered"
