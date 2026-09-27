"""Regression test: /api/search/multi must honour min_score (audit 2026-09-27).

`search_multi` read `min_score` from the request body and then passed a
hardcoded 0 into every engine.search_natural call, so the caller's threshold
was silently discarded and the endpoint returned every lead regardless of the
requested score.

(Note: the single-source endpoint at /api/search/natural forwards min_score
correctly. This file covers the multi-source path, which is the one that
dropped it.)
"""
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c


def test_min_score_is_forwarded_to_the_engine_not_hardcoded_zero(monkeypatch, client):
    seen = []

    async def fake_search_natural(natural_query, num_results, min_score, provider):
        seen.append({"query": natural_query, "min_score": min_score,
                     "provider": provider})
        return {"ok": True, "leads": []}

    monkeypatch.setattr(main.engine, "search_natural", fake_search_natural)

    r = client.post("/api/search/multi",
                    json={"query": "roofers in Austin", "min_score": 42.5,
                          "providers": ["exa"]})
    assert r.status_code == 200, r.text
    assert seen, "engine.search_natural was never called"
    for call in seen:
        assert call["min_score"] == 42.5, (
            f"min_score was not forwarded; engine saw {call['min_score']!r}. "
            "A hardcoded 0 here silently disables the caller's score filter."
        )
    assert seen[0]["query"] == "roofers in Austin"


def test_min_score_defaults_to_thirty_when_omitted(monkeypatch, client):
    seen = []

    async def fake_search_natural(natural_query, num_results, min_score, provider):
        seen.append(min_score)
        return {"ok": True, "leads": []}

    monkeypatch.setattr(main.engine, "search_natural", fake_search_natural)

    r = client.post("/api/search/multi",
                    json={"query": "roofers", "providers": ["exa"]})
    assert r.status_code == 200, r.text
    assert seen == [30.0], f"expected the documented 30.0 default, got {seen}"


def test_a_low_threshold_still_admits_every_provider(monkeypatch, client):
    """min_score is forwarded identically to every provider in the list."""
    seen = []

    async def fake_search_natural(natural_query, num_results, min_score, provider):
        seen.append((provider, min_score))
        return {"ok": True, "leads": []}

    monkeypatch.setattr(main.engine, "search_natural", fake_search_natural)

    r = client.post("/api/search/multi",
                    json={"query": "roofers", "min_score": 10,
                          "providers": ["exa", "perplexity"]})
    assert r.status_code == 200, r.text
    assert seen == [("exa", 10), ("perplexity", 10)], seen
