"""Shared fixtures for the engine/enrichment and engine/search test suites.

Import this module from any test_enrichment_*.py / test_search_*.py module to
get the autouse no-real-network guard. It is a plain fixture re-export rather
than a conftest plugin so it cannot leak into unrelated tests (the repo's root
tests/conftest.py boots the whole FastAPI app, which must keep working).
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from tests.support_nonet import no_real_network as no_real_network  # noqa: E402,F401

import pytest  # noqa: E402


@pytest.fixture
def vault_free(monkeypatch):
    """Blank every API-key env var the providers read, so a developer's real
    EXA_API_KEY / APOLLO_API_KEY cannot leak into a test."""
    for var in ("EXA_API_KEY", "PERPLEXITY_API_KEY", "APOLLO_API_KEY",
                "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
