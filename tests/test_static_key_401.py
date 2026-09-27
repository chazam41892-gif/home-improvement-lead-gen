"""Static-API-key callers must get 401, never 500 (audit 2026-09-27).

A caller presenting the server's own static API_KEY passes verify_api_key, but
that path never sets request.state.user -- only the JWT and stored-key paths do.
Seven routes then called user.get(...) on None, which raised AttributeError and
surfaced to the client as HTTP 500 with a stack trace.

500 is the wrong answer: the request failed authentication, so it must be 401,
consistent with /api/auth/me. This locks that in.
"""
import pytest
from fastapi.testclient import TestClient

import main

# Routes that read request.state.user after verify_api_key.
PROTECTED = [
    ("GET", "/api/auth/api-keys"),
    ("GET", "/api/auth/verticals"),
]


@pytest.fixture
def client():
    with TestClient(main.app, raise_server_exceptions=False) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c


def test_static_key_caller_does_not_get_500(client, monkeypatch):
    """A 500 means the route crashed. 401 is the correct rejection."""
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "test-api-key-for-ci-only", raising=False)

    for method, path in PROTECTED:
        r = client.request(method, path)
        assert r.status_code != 500, (
            f"{method} {path} returned 500 for a static-key caller: {r.text[:200]}. "
            "An unauthenticated request must be 401, not a server error."
        )
        assert r.status_code in (200, 401, 403), (
            f"{method} {path} -> unexpected {r.status_code}: {r.text[:200]}"
        )


def test_static_key_caller_is_rejected_on_every_user_scoped_route(client, monkeypatch):
    """Sweep every route that reads request.state.user and prove none 500s.

    A 500 means the route crashed on None. 401/403 is a correct rejection.
    """
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "test-api-key-for-ci-only", raising=False)

    checked = 0
    for route in main.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "user" not in path and not any(
            p in path for p in ("/api/auth/", "/api/verticals")
        ):
            continue
        if "GET" not in methods:
            continue
        r = client.get(path)
        checked += 1
        assert r.status_code != 500, (
            f"GET {path} returned 500 for a static-key caller: {r.text[:200]}"
        )
    assert checked, "no user-scoped GET routes were exercised -- the sweep is vacuous"


def test_api_key_cannot_reach_user_scoped_data(client, monkeypatch):
    """The static key authenticates the app but must not impersonate a user."""
    monkeypatch.setattr(main, "_AUTH_EXPLICITLY_DISABLED", False, raising=False)
    monkeypatch.setattr(main, "_API_KEY", "test-api-key-for-ci-only", raising=False)

    r = client.get("/api/auth/me")
    assert r.status_code == 401, f"expected 401 for a non-user token, got {r.status_code}"
