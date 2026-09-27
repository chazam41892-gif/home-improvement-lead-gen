"""Tests for engine/trades/scoring.py — the lead scoring rubric.

Each scoring branch is pinned with an exact expected value so a rebalanced
rubric shows up as a failing test, not a silent ranking change.
"""
import pytest

from engine.trades.base import TradeLead
from engine.trades.scoring import score_trade_lead, score_trade_leads


def make(**kw):
    """A TradeLead with every scoring input zeroed unless overridden."""
    kw.setdefault("business_name", "X")
    return TradeLead(**kw)


# ── unknown trade ──────────────────────────────────────────────────────────
def test_unknown_trade_returns_the_neutral_fifty():
    lead = make(phone="555", email="a@b.com", website="http://x", address="1 Main",
                rating=4.9, review_count=99, platforms_found=["a", "b", "c"])
    assert score_trade_lead(lead, "not_a_trade") == 50.0


def test_unknown_trade_ignores_all_bonus_signals():
    """The early return happens before any bonus is applied — pin that a
    maximally-rich lead is not rewarded for an unconfigured trade."""
    bare = make()
    rich = make(phone="555", email="a@b.com", website="http://x", address="1 Main",
                rating=4.9, review_count=99, platforms_found=["a", "b", "c"])
    assert score_trade_lead(rich, "not_a_trade") == score_trade_lead(bare, "not_a_trade")


@pytest.mark.parametrize("trade", ["plumbing", "hvac", "land_developer", "landscaping"])
def test_known_trades_all_score_a_bare_lead_at_fifty(trade):
    assert score_trade_lead(make(), trade) == 50.0


# ── contact bonuses ────────────────────────────────────────────────────────
def test_phone_adds_ten():
    assert score_trade_lead(make(phone="555-0100"), "plumbing") == 60.0


def test_email_adds_ten():
    assert score_trade_lead(make(email="a@b.com"), "plumbing") == 60.0


def test_phone_and_email_stack():
    assert score_trade_lead(make(phone="555", email="a@b.com"), "plumbing") == 70.0


def test_empty_string_contact_details_earn_nothing():
    """Falsy, not truthy-checked-as-string: '' must add 0, not 10."""
    assert score_trade_lead(make(phone="", email="", website="", address=""),
                            "plumbing") == 50.0


def test_website_adds_five():
    assert score_trade_lead(make(website="http://x"), "plumbing") == 55.0


def test_address_adds_five():
    assert score_trade_lead(make(address="1 Main St"), "plumbing") == 55.0


def test_all_four_contact_fields_stack():
    lead = make(phone="555", email="a@b.com", website="http://x", address="1 Main St")
    assert score_trade_lead(lead, "plumbing") == 80.0


# ── rating tiers ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("rating,expected", [
    (0.0, 50.0),    # falsy: neither branch
    (0.1, 52.0),    # > 0 but <= 4.0
    (3.9, 52.0),
    (4.0, 52.0),    # boundary: NOT > 4.0
    (4.01, 55.0),   # just over the boundary
    (4.5, 55.0),
    (5.0, 55.0),
])
def test_rating_tiers(rating, expected):
    assert score_trade_lead(make(rating=rating), "plumbing") == expected


def test_rating_tier_boundaries_are_strictly_greater_than():
    """4.0 is the exact boundary and belongs in the LOWER tier."""
    assert score_trade_lead(make(rating=4.0), "plumbing") < \
           score_trade_lead(make(rating=4.0001), "plumbing")


# ── review-count tiers ─────────────────────────────────────────────────────
@pytest.mark.parametrize("reviews,expected", [
    (0, 50.0),
    (1, 50.0),      # > 0 but <= 5
    (5, 50.0),      # boundary: NOT > 5
    (6, 52.0),
    (20, 52.0),     # boundary: NOT > 20
    (21, 55.0),
    (500, 55.0),
])
def test_review_count_tiers(reviews, expected):
    assert score_trade_lead(make(review_count=reviews), "plumbing") == expected


# ── platform-multiplicity bonus ────────────────────────────────────────────
def test_zero_platforms_adds_nothing():
    lead = make(source="yelp", platforms_found=[])
    lead.platforms_found = []
    assert score_trade_lead(lead, "plumbing") == 50.0


def test_platforms_found_is_discarded_when_source_is_empty():
    """base.py reads `platforms_found or [source] if source else []`, so a lead
    built without a source loses its explicit list entirely. Callers that rely
    on multi-platform scoring MUST set source. Pinned as a known trap."""
    lead = make(platforms_found=["a", "b", "c"])
    assert lead.source == ""
    assert lead.platforms_found == []
    assert score_trade_lead(lead, "plumbing") == 50.0


def test_one_platform_adds_nothing():
    lead = make(source="yelp")
    assert lead.platforms_found == ["yelp"]
    assert score_trade_lead(lead, "plumbing") == 50.0


def test_two_platforms_adds_five():
    lead = make(source="yelp", platforms_found=["yelp", "angi"])
    assert lead.platforms_found == ["yelp", "angi"]
    assert score_trade_lead(lead, "plumbing") == 55.0


def test_three_platforms_add_ten():
    lead = make(source="yelp", platforms_found=["yelp", "angi", "google_maps"])
    assert score_trade_lead(lead, "plumbing") == 60.0


def test_five_platforms_still_add_ten_not_more():
    lead = make(source="yelp", platforms_found=["a", "b", "c", "d", "e"])
    assert score_trade_lead(lead, "plumbing") == 60.0


# ── cap ────────────────────────────────────────────────────────────────────
def test_the_cap_is_defensive_and_unreachable_by_the_current_rubric():
    """The maximum the rubric can award is exactly 100 — 50 base + 10 phone +
    10 email + 5 website + 5 address + 5 rating + 5 reviews + 10 platforms — so
    `min(score, 100.0)` never actually truncates today. Worth knowing before
    anyone assumes the cap is doing work or that 100 means 'there was more'."""
    maximal = make(phone="555", email="a@b.com", website="http://x",
                   address="1 Main", rating=5.0, review_count=10**6,
                   source="yelp", platforms_found=list("abcdefgh"))
    assert score_trade_lead(maximal, "plumbing") == 100.0


def test_score_never_exceeds_cap_across_the_registry():
    from engine.trades.trades import TRADE_REGISTRY

    lead = make(phone="555", email="a@b.com", website="http://x", address="1 Main",
                rating=5.0, review_count=999, source="yelp",
                platforms_found=["a", "b", "c", "d", "e"])
    for trade in TRADE_REGISTRY:
        s = score_trade_lead(lead, trade)
        assert 0.0 <= s <= 100.0, (trade, s)


# ── score_trade_leads ──────────────────────────────────────────────────────
def test_score_trade_leads_returns_the_same_objects_mutated_in_place():
    a, b = make(phone="555"), make()
    out = score_trade_leads([a, b], "plumbing")
    assert out[0] is a and out[1] is b
    assert a.score == 60.0 and b.score == 50.0


def test_score_trade_leads_sorts_descending():
    poor = make()
    mid = make(website="http://x")
    rich = make(phone="555", email="a@b.com")
    out = score_trade_leads([poor, rich, mid], "plumbing")
    assert [x.score for x in out] == [70.0, 55.0, 50.0]


def test_score_trade_leads_sorts_a_partially_equal_batch_stably():
    """Equal scores must not be reshuffled; Python's sort is stable."""
    first, second, third = make(), make(), make()
    out = score_trade_leads([first, second, third], "plumbing")
    assert out == [first, second, third]


def test_score_trade_leads_of_empty_list():
    assert score_trade_leads([], "plumbing") == []


def test_score_trade_leads_of_empty_list_for_unknown_trade():
    assert score_trade_leads([], "not_a_trade") == []


def test_score_trade_leads_uses_the_given_trade_not_the_lead_trade():
    """A lead whose .trade is 'hvac' scored as 'plumbing' still resolves via the
    argument, so an unknown argument floors everything at 50."""
    lead = make(phone="555", email="a@b.com", source="yelp", trade="hvac")
    out = score_trade_leads([lead], "not_a_trade")
    assert out[0].score == 50.0


def test_score_trade_leads_assigns_every_lead_a_score():
    leads = [make(), make(phone="1"), make(email="a@b.com", website="http://x")]
    out = score_trade_leads(leads, "plumbing")
    assert {x.score for x in out} == {50.0, 60.0, 65.0}


def test_score_trade_leads_reordering_is_visible_in_the_return_value():
    leads = [make(), make(phone="555")]
    assert leads[0].score == 50.0
    out = score_trade_leads(leads, "plumbing")
    assert out[0].business_name == leads[0].business_name
    assert out[0].score == 60.0
    assert leads is not out or out[0] is leads[1]
