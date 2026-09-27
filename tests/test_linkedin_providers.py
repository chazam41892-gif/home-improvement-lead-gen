"""Tests for LinkedInAPIClient (audit 2026-09-27).

Ported from SIOS with 0% coverage. Rather than mock aiohttp, these run a REAL
local HTTP server (stdlib http.server on an ephemeral port) and point the
client's base_url at it, exercising actual request-building, status handling,
JSON parsing and error paths end to end.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from engine.linkedin.linkedin_signals.providers import LinkedInAPIClient, ProviderError


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def log_message(self, *a):
        pass

    def _respond(self, code, payload, extra_headers=None):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _Handler.seen.append(("GET", self.path))
        status, payload, hdrs = _Handler.routes.get(
            self.path, (404, {"error": "no route"}, {}))
        self._respond(status, payload, hdrs)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        _Handler.seen.append(("POST", self.path, json.loads(raw or b"{}")))
        status, payload, hdrs = _Handler.routes.get(
            self.path, (404, {"error": "no route"}, {}))
        self._respond(status, payload, hdrs)


@pytest.fixture
def api():
    _Handler.routes = {}
    _Handler.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def run(coro):
    return asyncio.run(coro)


def client(base, **kw):
    c = LinkedInAPIClient("tok-123", **kw)
    c.base_url = base
    return c


# ── headers ────────────────────────────────────────────────────────────────
def test_headers_carry_bearer_token_and_version():
    h = LinkedInAPIClient("secret-token").headers
    assert h["Authorization"].startswith("Bearer "), h
    assert "secret-token" in h["Authorization"]
    assert h["X-Restli-Protocol-Version"], h


def test_post_author_must_be_a_urn(api):
    with pytest.raises(ValueError, match="URN"):
        run(client(api).create_text_post("not-a-urn", "hello"))


def test_post_commentary_is_required(api):
    with pytest.raises(ValueError, match="commentary"):
        run(client(api).create_text_post("urn:li:person:1", "   "))


# ── GET ────────────────────────────────────────────────────────────────────
def test_get_parses_json(api):
    _Handler.routes["/v2/thing"] = (200, {"ok": True, "n": 7}, {})
    assert run(client(api)._get("/v2/thing")) == {"ok": True, "n": 7}
    assert ("GET", "/v2/thing") in _Handler.seen


def test_get_raises_on_4xx(api):
    _Handler.routes["/v2/bad"] = (403, {"message": "nope"}, {})
    with pytest.raises(ProviderError) as exc:
        run(client(api)._get("/v2/bad"))
    assert "403" in str(exc.value)


def test_get_raises_on_5xx(api):
    _Handler.routes["/v2/boom"] = (503, {"message": "down"}, {})
    with pytest.raises(ProviderError, match="503"):
        run(client(api)._get("/v2/boom"))


def test_get_on_empty_body_returns_empty_dict(api):
    _Handler.routes["/v2/empty"] = (200, {}, {})
    assert run(client(api)._get("/v2/empty")) == {}


# ── POST ───────────────────────────────────────────────────────────────────
def test_post_sends_json_and_captures_restli_id(api):
    _Handler.routes["/v2/posts"] = (201, {"ok": True},
                                    {"x-restli-id": "urn:li:share:999"})
    out = run(client(api)._post("/v2/posts", {"commentary": "hi"}))
    assert out["id"] == "urn:li:share:999", out
    method, path, body = _Handler.seen[-1]
    assert method == "POST" and path == "/v2/posts"
    assert body == {"commentary": "hi"}, body


def test_post_raises_on_error_status(api):
    _Handler.routes["/v2/posts"] = (422, {"message": "invalid"}, {})
    with pytest.raises(ProviderError, match="422"):
        run(client(api)._post("/v2/posts", {}))


def test_post_without_restli_header_has_no_synthesised_id(api):
    """A missing x-restli-id must not be faked into a plausible-looking id."""
    _Handler.routes["/v2/posts"] = (201, {"ok": True}, {})
    out = run(client(api)._post("/v2/posts", {}))
    assert "id" not in out, out
