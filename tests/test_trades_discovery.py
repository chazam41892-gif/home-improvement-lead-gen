"""Tests for engine/trades/discovery.py (TradeLeadDiscovery).

Real fakes for the *transport* only: every PLATFORM_SEARCHERS entry is driven
by a scriptable stub that returns genuine TradeLead objects or raises, so the
concurrency, dedupe, scoring, error-isolation and results-bookkeeping logic
under test is the real code.
"""
import asyncio

import pytest

from engine.trades import discovery as D
from engine.trades import platforms as P
from engine.trades.base import TradeLead


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the searcher registry so a test can never leak into
    another (and never touches the module-level Exa provider)."""
    saved = dict(P.PLATFORM_SEARCHERS)
    yield
    P.PLATFORM_SEARCHERS.clear()
    P.PLATFORM_SEARCHERS.update(saved)


def stub_searcher(leads=(), raises=None, calls=None):
    async def _search(trade, location, max_results):
        if calls is not None:
            calls.append((trade, location, max_results))
        if raises is not None:
            raise raises
        return list(leads)

    return _search


def lead(name, website="", **kw):
    return TradeLead(business_name=name, website=website, **kw)


def register(**searchers):
    P.PLATFORM_SEARCHERS.update(searchers)


# ── unknown trade ──────────────────────────────────────────────────────────
async def test_unknown_trade_returns_empty_and_records_nothing():
    calls = []
    register(fake=stub_searcher(calls=calls))
    d = D.TradeLeadDiscovery()
    assert await d.discover("not_a_trade", "Austin") == []
    assert calls == [], "a searcher must not be called for an unknown trade"
    assert d.get_results() == {}


async def test_unknown_trade_logs_a_warning(caplog):
    d = D.TradeLeadDiscovery()
    with caplog.at_level("WARNING", logger="engine.trades.discovery"):
        await d.discover("not_a_trade", "Austin")
    assert any("Unknown trade" in r.message for r in caplog.records), caplog.records


# ── platform selection ─────────────────────────────────────────────────────
async def test_unknown_platform_is_skipped_but_known_ones_still_run():
    good = lead("Ace", "http://a")
    d = D.TradeLeadDiscovery()
    assert "bogus_platform" not in P.PLATFORM_SEARCHERS
    register(yelp=stub_searcher([good]))
    out = await d.discover("plumbing", "Austin", platforms=["bogus_platform", "yelp"])
    assert [x.business_name for x in out] == ["Ace"]


async def test_unknown_platform_is_logged(caplog):
    d = D.TradeLeadDiscovery()
    with caplog.at_level("WARNING", logger="engine.trades.discovery"):
        await d.discover("plumbing", "Austin", platforms=["bogus_platform"])
    assert any("No searcher for platform: bogus_platform" in r.message
               for r in caplog.records), caplog.records


async def test_default_platforms_come_from_the_trade_config():
    calls = []
    d = D.TradeLeadDiscovery()
    register(google_maps=stub_searcher(calls=calls), yelp=stub_searcher(calls=calls),
             homeadvisor=stub_searcher(calls=calls), angi=stub_searcher(calls=calls),
             nextdoor=stub_searcher(calls=calls))
    await d.discover("plumbing", "Austin")
    assert len(calls) == 5, calls
    assert all(c == ("plumbing", "Austin", 15) for c in calls), calls


async def test_explicit_platforms_override_the_config():
    calls = []
    d = D.TradeLeadDiscovery()
    register(google_maps=stub_searcher(calls=calls), yelp=stub_searcher(calls=calls),
             homeadvisor=stub_searcher(calls=calls), angi=stub_searcher(calls=calls),
             nextdoor=stub_searcher(calls=calls))
    await d.discover("plumbing", "Austin", platforms=["yelp"])
    assert len(calls) == 1


async def test_max_per_platform_is_passed_through():
    calls = []
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher(calls=calls))
    await d.discover("plumbing", "Austin", platforms=["yelp"], max_per_platform=7)
    assert calls[0][2] == 7


async def test_empty_platform_list_falls_back_to_config():
    """`platforms or config[...]` — an empty list is falsy, so the config wins."""
    calls = []
    d = D.TradeLeadDiscovery()
    register(google_maps=stub_searcher(calls=calls), yelp=stub_searcher(calls=calls),
             homeadvisor=stub_searcher(calls=calls), angi=stub_searcher(calls=calls),
             nextdoor=stub_searcher(calls=calls))
    await d.discover("plumbing", "Austin", platforms=[])
    assert len(calls) == 5


# ── error isolation ────────────────────────────────────────────────────────
async def test_one_failing_platform_does_not_sink_the_others():
    d = D.TradeLeadDiscovery()
    register(
        yelp=stub_searcher(raises=RuntimeError("yelp 500")),
        angi=stub_searcher([lead("Survivor", "http://survivor")]),
    )
    out = await d.discover("plumbing", "Austin", platforms=["yelp", "angi"])
    assert [x.business_name for x in out] == ["Survivor"]


async def test_all_platforms_failing_returns_empty_not_raise():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher(raises=RuntimeError("boom")),
             angi=stub_searcher(raises=ValueError("bang")))
    assert await d.discover("plumbing", "Austin", platforms=["yelp", "angi"]) == []


async def test_platform_failure_is_logged(caplog):
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher(raises=RuntimeError("yelp 500")))
    with caplog.at_level("WARNING", logger="engine.trades.discovery"):
        await d.discover("plumbing", "Austin", platforms=["yelp"])
    assert any("Platform search failed: yelp 500" in r.message
               for r in caplog.records), caplog.records


# ── dedupe ─────────────────────────────────────────────────────────────────
async def test_leads_sharing_a_website_are_deduped_across_platforms():
    d = D.TradeLeadDiscovery()
    register(
        yelp=stub_searcher([lead("Yelp Name", "http://same")]),
        angi=stub_searcher([lead("Angi Name", "http://same")]),
    )
    out = await d.discover("plumbing", "Austin", platforms=["yelp", "angi"])
    assert len(out) == 1


async def test_website_wins_over_business_name_for_dedupe():
    d = D.TradeLeadDiscovery()
    register(
        yelp=stub_searcher([lead("Same", "http://one")]),
        angi=stub_searcher([lead("Same", "http://two")]),
    )
    out = await d.discover("plumbing", "Austin", platforms=["yelp", "angi"])
    assert len(out) == 2, "different websites with the same name are distinct leads"


async def test_leads_without_website_fall_back_to_name_for_dedupe():
    d = D.TradeLeadDiscovery()
    register(
        yelp=stub_searcher([lead("Nameless Co", "")]),
        angi=stub_searcher([lead("Nameless Co", "")]),
    )
    out = await d.discover("plumbing", "Austin", platforms=["yelp", "angi"])
    assert len(out) == 1


async def test_lead_with_neither_website_nor_name_is_dropped():
    """`if key and key not in seen_keys` — a nameless, site-less lead is junk."""
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([TradeLead(business_name="", website="")]))
    assert await d.discover("plumbing", "Austin", platforms=["yelp"]) == []


async def test_dedupe_keeps_first_platforms_lead():
    d = D.TradeLeadDiscovery()
    register(
        yelp=stub_searcher([lead("From Yelp", "http://same")]),
        angi=stub_searcher([lead("From Angi", "http://same")]),
    )
    out = await d.discover("plumbing", "Austin", platforms=["yelp", "angi"])
    assert out[0].business_name == "From Yelp"


# ── scoring is applied ─────────────────────────────────────────────────────
async def test_discovered_leads_are_scored_and_sorted_high_first():
    rich = lead("Rich", "http://rich", phone="555", email="a@b.com",
                address="1 Main", rating=4.8, review_count=40,
                platforms_found=["yelp", "angi", "google_maps"])
    poor = lead("Poor", "http://poor")
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([poor, rich]))
    out = await d.discover("plumbing", "Austin", platforms=["yelp"])
    assert [x.business_name for x in out] == ["Rich", "Poor"]
    assert out[0].score > out[1].score
    # 50 base + 5 website; one platform is below the >=2 bonus threshold.
    assert out[1].score == 55.0, out[1].score


async def test_scoring_is_per_trade():
    """Same lead, two trades: land_developer has a different platform count, but
    score_trade_lead only varies via the config lookup, so pin that both work."""
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Same", "http://same", phone="555")]))
    plumbing = await d.discover("plumbing", "Austin", platforms=["yelp"])
    land = await d.discover("land_developer", "Austin", platforms=["yelp"])
    assert plumbing[0].score == land[0].score == 65.0, plumbing[0].score


# ── results bookkeeping ────────────────────────────────────────────────────
async def test_results_are_keyed_by_trade_and_location():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await d.discover("plumbing", "Austin")
    assert list(d.get_results()) == ["plumbing:Austin"]
    assert [x.business_name for x in d.get_results()["plumbing:Austin"]] == ["Ace"]


async def test_repeat_discoveries_accumulate_rather_than_replace():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await d.discover("plumbing", "Austin")
    await d.discover("plumbing", "Austin")
    assert len(d.get_results()["plumbing:Austin"]) == 2


async def test_get_results_with_unknown_key_returns_empty_list():
    d = D.TradeLeadDiscovery()
    assert d.get_results("plumbing:Nowhere") == {"plumbing:Nowhere": []}


async def test_get_results_with_key_filters_to_that_key():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await d.discover("plumbing", "Austin")
    assert set(d.get_results("plumbing:Austin")) == {"plumbing:Austin"}


async def test_different_locations_are_separate_buckets():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await d.discover("plumbing", "Austin")
    await d.discover("plumbing", "Denver")
    assert set(d.get_results()) == {"plumbing:Austin", "plumbing:Denver"}


async def test_get_leads_for_trade_filters_by_trade():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Plumb", "http://p")]),
             angi=stub_searcher([lead("Land", "http://l")]))
    await d.discover("plumbing", "Austin", platforms=["yelp"])
    await d.discover("land_developer", "Austin", platforms=["angi"])
    got = d.get_leads_for_trade("plumbing")
    assert [x.business_name for x in got] == ["Plumb"]


async def test_get_leads_for_trade_filters_by_location():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await d.discover("plumbing", "Austin")
    await d.discover("plumbing", "Denver")
    assert len(d.get_leads_for_trade("plumbing", "Austin")) == 1
    assert len(d.get_leads_for_trade("plumbing", "Denver")) == 1
    assert len(d.get_leads_for_trade("plumbing")) == 2


async def test_get_leads_for_trade_does_not_prefix_match():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await d.discover("plumbing", "Austin")
    assert d.get_leads_for_trade("plum") == [], "'plum' must not match 'plumbing:Austin'"


async def test_get_leads_for_unknown_trade_is_empty():
    d = D.TradeLeadDiscovery()
    assert d.get_leads_for_trade("nope") == []


# ── concurrency ────────────────────────────────────────────────────────────
async def test_all_platforms_run_concurrently_not_serially():
    """With 4 searchers each sleeping 200ms, a serial implementation would
    take >=800ms. Generous ceiling still fails loudly if gather is removed."""
    import time

    async def slow(trade, location, max_results):
        await asyncio.sleep(0.2)
        return []

    register(a=slow, b=slow, c=slow, d=slow)
    d = D.TradeLeadDiscovery()
    t0 = time.monotonic()
    await d.discover("plumbing", "Austin", platforms=["a", "b", "c", "d"])
    assert time.monotonic() - t0 < 0.6, "platform searches ran serially"


async def test_concurrent_discoveries_on_one_instance_do_not_lose_leads():
    """The `_results` dict is shared; the asyncio.Lock must not be bypassed."""
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    await asyncio.gather(*[
        d.discover("plumbing", loc) for loc in ("Austin", "Denver", "Miami", "Tulsa")
    ])
    assert set(d.get_results()) == {
        "plumbing:Austin", "plumbing:Denver", "plumbing:Miami", "plumbing:Tulsa",
    }
    assert all(len(v) == 1 for v in d.get_results().values())


# ── discover_all ───────────────────────────────────────────────────────────
async def test_discover_all_covers_requested_trades_only():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    out = await d.discover_all(["plumbing", "hvac"], "Austin")
    assert set(out) == {"plumbing", "hvac"}
    assert all(v for v in out.values())


async def test_discover_all_passes_max_per_trade_as_max_per_platform():
    calls = []
    register(yelp=stub_searcher(calls=calls))
    d = D.TradeLeadDiscovery()
    await d.discover_all(["plumbing"], "Austin", max_per_trade=3)
    assert calls and all(c[2] == 3 for c in calls), calls


async def test_discover_all_defaults_to_the_entire_registry():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([]))
    out = await d.discover_all(location="Austin")
    assert set(out) == set(D.TRADE_REGISTRY), f"covered {len(out)} of {len(D.TRADE_REGISTRY)}"
    assert len(out) == 45


async def test_discover_all_isolates_a_failing_trade():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher(raises=RuntimeError("nope")))
    out = await d.discover_all(["plumbing", "hvac"], "Austin")
    assert set(out) == {"plumbing", "hvac"}
    assert out["plumbing"] == [] and out["hvac"] == []


async def test_discover_all_isolates_an_unknown_trade():
    d = D.TradeLeadDiscovery()
    register(yelp=stub_searcher([]))
    out = await d.discover_all(["plumbing", "not_a_trade"], "Austin")
    assert out["not_a_trade"] == []
    assert set(out) == {"plumbing", "not_a_trade"}


async def test_discover_all_respects_the_concurrency_cap():
    """Semaphore(4): 8 slow trades must not run more than 4 at once."""
    peak = {"n": 0, "cur": 0}
    lock = asyncio.Lock()

    async def slow(trade, location, max_results):
        async with lock:
            peak["cur"] += 1
            peak["n"] = max(peak["n"], peak["cur"])
        await asyncio.sleep(0.05)
        async with lock:
            peak["cur"] -= 1
        return []

    register(yelp=slow)
    d = D.TradeLeadDiscovery()
    trades = list(D.TRADE_REGISTRY)[:8]
    await d.discover_all(trades, "Austin")
    assert peak["n"] <= 4, f"{peak['n']} trades ran concurrently, cap is 4"


async def test_discover_all_returns_a_key_for_every_trade():
    register(yelp=stub_searcher([]))
    d = D.TradeLeadDiscovery()
    out = await d.discover_all(["plumbing"], "Austin")
    assert list(out) == ["plumbing"]


async def test_discover_all_populates_the_shared_results_store():
    register(yelp=stub_searcher([lead("Ace", "http://a")]))
    d = D.TradeLeadDiscovery()
    await d.discover_all(["plumbing"], "Austin")
    assert len(d.get_results()["plumbing:Austin"]) == 1


# ── discover_best_platform ─────────────────────────────────────────────────
async def test_best_platform_search_uses_only_the_configured_platform():
    calls = []
    register(google_maps=stub_searcher(calls=calls), homeadvisor=stub_searcher(calls=calls),
             yelp=stub_searcher(calls=calls), angi=stub_searcher(calls=calls),
             nextdoor=stub_searcher(calls=calls))
    d = D.TradeLeadDiscovery()
    await d.discover_best_platform("plumbing", "Austin")
    assert len(calls) == 1, calls
    assert calls[0][0] == "plumbing" and calls[0][1] == "Austin"


async def test_best_platform_for_unknown_trade_returns_empty():
    d = D.TradeLeadDiscovery()
    assert await d.discover_best_platform("not_a_trade", "Austin") == []


async def test_best_platform_forwards_max_results():
    calls = []
    register(yelp=stub_searcher(calls=calls))
    d = D.TradeLeadDiscovery()
    await d.discover_best_platform("painting", "Austin", max_results=42)
    assert calls[0][2] == 42, calls


async def test_best_platform_uses_the_registry_value_not_a_hardcoded_one():
    """painting's best_platform is yelp — prove it follows the config."""
    from engine.trades.trades import get_trade_config

    calls = []
    register(google_maps=stub_searcher(calls=calls), yelp=stub_searcher(calls=calls),
             homeadvisor=stub_searcher(calls=calls), angi=stub_searcher(calls=calls),
             nextdoor=stub_searcher(calls=calls))
    d = D.TradeLeadDiscovery()
    await d.discover_best_platform("painting", "Austin")
    assert get_trade_config("painting")["best_platform"] == "yelp"
    assert len(calls) == 1


# ── constructor / provider wiring ──────────────────────────────────────────
def test_constructor_accepts_a_provider_and_installs_it():
    class MyProvider:
        pass

    p = MyProvider()
    D.TradeLeadDiscovery(exa_provider=p)
    assert P._get_provider() is p


def test_constructor_without_a_provider_leaves_the_module_default_alone():
    class MyProvider:
        pass

    saved = P._exa_provider
    try:
        P.set_exa_provider(None)
        D.TradeLeadDiscovery()
        assert P._exa_provider is None
    finally:
        P.set_exa_provider(saved)


def test_constructor_initialises_empty_state():
    d = D.TradeLeadDiscovery()
    assert d._results == {}
    assert isinstance(d._lock, asyncio.Lock)


def test_two_instances_have_independent_result_stores():
    a, b = D.TradeLeadDiscovery(), D.TradeLeadDiscovery()
    a._results["x:1"] = []
    assert b.get_results() == {}
