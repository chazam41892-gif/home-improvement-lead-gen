"""Meta-test: prove the no-real-network guard actually fires.

A guard that silently does nothing would let these suites quietly depend on the
live internet. This test asserts the guard blocks a public host and still allows
loopback, so a future refactor cannot quietly disable it.
"""
import socket

import pytest

from tests.support_fixtures import no_real_network  # noqa: F401
from tests.support_nonet import _is_local


@pytest.mark.parametrize("host", ["acmeroofing.com", "api.exa.ai", "8.8.8.8",
                                  "example.com"])
def test_guard_blocks_public_hosts(host):
    with pytest.raises(AssertionError, match="BLOCKED"):
        socket.getaddrinfo(host, 443)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.1:8080"])
def test_guard_allows_loopback(host):
    port = 443 if host == "127.0.0.1" else 0
    if host == "127.0.0.1":
        # a resolve of 127.0.0.1 itself must be permitted
        assert socket.getaddrinfo("127.0.0.1", port)
    else:
        assert _is_local(host)


def test_guard_blocks_real_tcp_to_a_public_host():
    with pytest.raises(AssertionError, match="BLOCKED"):
        socket.create_connection(("api.exa.ai", 443))


def test_guard_allows_real_tcp_to_loopback():
    with pytest.raises(OSError):
        # nothing is listening on 127.0.0.1:9 -> OSError, NOT AssertionError,
        # which proves the guard let the call through to the real stack.
        socket.create_connection(("127.0.0.1", 9), timeout=1)


def test_is_local_classifier():
    assert _is_local("127.0.0.1")
    assert _is_local("localhost")
    assert _is_local("::1")
    assert _is_local("[::1]:8000")
    assert _is_local("127.0.0.1:9999")
    assert not _is_local("api.exa.ai")
    assert not _is_local("8.8.8.8")
