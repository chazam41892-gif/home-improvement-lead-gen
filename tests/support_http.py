"""Shared stdlib-HTTP test server for engine/enrichment + engine/search tests.

Same philosophy as tests/test_linkedin_providers.py: no mocking of httpx or
urllib. We stand up a REAL local HTTP server on an ephemeral port, record every
request (method, path, query, headers, JSON body) and let the real clients talk
to it. That exercises request-building, status handling, JSON parsing and the
error paths for real.

ThreadingHTTPServer (not HTTPServer) because browser_agent/enrichers crawl
concurrently — a single-threaded server would serialise (and potentially stall)
the concurrent fetch tests.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest


class Recorder:
    """Route table + request log shared with the handler class."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple] = {}
        self.requests: list[dict] = []
        self.default = (404, {"error": "no route"}, None, {}, 0.0)

    def add(self, method, path, payload=None, *, status=200, raw=None,
            headers=None, delay=0.0):
        """Register a route.

        payload -> JSON-encoded body.  raw -> verbatim body text/bytes (used for
        malformed-JSON and HTML cases); wins over payload when both absent.
        """
        self.routes[(method.upper(), path)] = (
            int(status), payload, raw, dict(headers or {}), float(delay),
        )

    def html(self, method, path, body: str, *, status=200, headers=None, delay=0.0):
        h = {"Content-Type": "text/html; charset=utf-8"}
        h.update(headers or {})
        self.add(method, path, raw=body, status=status, headers=h, delay=delay)

    # ── request inspection ────────────────────────────────────────────────
    def query_of(self, path: str, method: str = "GET") -> dict:
        for r in self.requests:
            if r["method"] == method.upper() and r["path"] == path:
                return r["query"]
        return {}

    def bodies(self, method: str, path: str) -> list:
        return [r["json"] for r in self.requests
                if r["method"] == method.upper() and r["path"] == path]

    def last_body(self, method: str, path: str):
        b = self.bodies(method, path)
        return b[-1] if b else None

    def paths(self, method: str | None = None) -> list:
        return [r["path"] for r in self.requests
                if method is None or r["method"] == method.upper()]

    def count(self, method: str | None = None) -> int:
        return len([r for r in self.requests
                    if method is None or r["method"] == method.upper()])


def _handler_class(rec: Recorder):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # silence
            pass

        def _record(self, method: str):
            split = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else None
            except (ValueError, UnicodeDecodeError):
                body = None
            rec.requests.append({
                "method": method,
                "path": split.path,
                "raw_path": self.path,
                "query": parse_qs(split.query),
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": raw,
                "json": body,
            })
            return split.path

        def _dispatch(self, method: str):
            path = self._record(method)
            status, payload, raw, hdrs, delay = rec.routes.get(
                (method, path), rec.default)
            if delay:
                time.sleep(delay)
            if raw is not None:
                body = raw.encode("utf-8") if isinstance(raw, str) else raw
                ctype = hdrs.get("Content-Type", "text/plain; charset=utf-8")
            else:
                body = json.dumps(payload).encode("utf-8")
                ctype = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in hdrs.items():
                if k.lower() != "content-type":
                    self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

    return Handler


class LocalServer:
    """Context manager yielding (base_url, Recorder)."""

    def __init__(self) -> None:
        self.rec = Recorder()
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base(self) -> str:
        assert self._srv is not None
        return f"http://127.0.0.1:{self._srv.server_port}"

    def url(self, path: str) -> str:
        return self.base + path

    def start(self) -> "LocalServer":
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler_class(self.rec))
        self._srv.daemon_threads = True
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def __enter__(self) -> "LocalServer":
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


@pytest.fixture
def closed_port():
    """base_url on a port with nothing listening -> instant ECONNREFUSED.

    Port 9 is a blackhole (packets are dropped), which makes the client hang
    until its timeout. Binding then closing a socket gives a port that refuses
    immediately, so transport-failure tests are fast and deterministic.
    """
    import socket as _s
    with _s.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def dead_url() -> str:
    """A port nothing is listening on -> guaranteed connect failure."""
    return "http://127.0.0.1:9"
