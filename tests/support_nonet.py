"""Pytest fixtures shared by the enrichment/search test modules.

`no_real_network` is an autouse safety net: these suites point every client at a
local stdlib HTTP server, so ANY attempt to resolve a non-loopback hostname is a
test bug (it would make the suite hit the live internet and produce
non-deterministic results). Failing loudly is much better than silently
depending on acmeroofing.com being up.
"""
from __future__ import annotations

import ipaddress
import socket

import pytest

_ALLOWED_HOSTNAMES = {"localhost", "localhost.localdomain", "", None}
_real_getaddrinfo = socket.getaddrinfo
_real_create_connection = socket.create_connection
_real_gethostbyname = socket.gethostbyname


def _is_local(host) -> bool:
    if host in _ALLOWED_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(str(host).strip("[]")).is_loopback
    except ValueError:
        pass
    # "127.0.0.1:port" / "[::1]:port" style
    h = str(host)
    if h.startswith("["):
        h = h[1:].split("]")[0]
    elif h.count(":") == 1:
        h = h.split(":")[0]
    if h in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def guard_getaddrinfo(host, *a, **k):
        if not _is_local(host):
            raise AssertionError(
                f"BLOCKED real DNS lookup for {host!r}. These suites must only "
                f"talk to the local test server."
            )
        return _real_getaddrinfo(host, *a, **k)

    def guard_create_connection(address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            raise AssertionError(
                f"BLOCKED real TCP connection to {address!r}. These suites must "
                f"only talk to the local test server."
            )
        return _real_create_connection(address, *a, **k)

    def guard_gethostbyname(host):
        if not _is_local(host):
            raise AssertionError(
                f"BLOCKED real DNS lookup for {host!r}. These suites must only "
                f"talk to the local test server."
            )
        return _real_gethostbyname(host)

    monkeypatch.setattr(socket, "getaddrinfo", guard_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guard_create_connection)
    monkeypatch.setattr(socket, "gethostbyname", guard_gethostbyname)
    yield
