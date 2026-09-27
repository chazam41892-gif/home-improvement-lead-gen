"""Tests for engine/utils/scoring.py — the 5-dimension lead scoring math (audit 2026-09-27).

This is pure arithmetic with no I/O, so every expected number here is
hand-computed from the implementation and asserted with `==` (or `pytest.approx`),
never a range check. A scoring function that returns a plausible-but-wrong number
silently mis-ranks every lead in the product, so the exact values are the point.

Weights (score_lead): contact .25, business .15, industry .30, location .20,
enrichment .10 — they sum to 1.0, so a fully-maxed lead scores exactly 100.
"""
import sys

import pytest

from engine.utils.scoring import (
    INDUSTRY_KEYWORDS,
    INDUSTRY_WEIGHTS,
    LeadScore,
    score_business_presence,
    score_contact_completeness,
    score_enrichment_potential,
    score_industry_relevance,
    score_lead,
    score_location_match,
)


# ── score_contact_completeness: 25 title + 15 snippet + 25 phone + 20 email + 15 domain
# (capped at 100)
def test_contact_scores_zero_for_empty_input():
    assert score_contact_completeness("", "", "") == 0.0


def test_contact_title_under_six_chars_scores_nothing():
    """The title bonus is `len(title) > 5`, not >= 5, and never scales with length."""
    assert score_contact_completeness("Roofs", "", "") == 0.0
    assert score_contact_completeness("Roofin", "", "") == 25.0


def test_contact_snippet_under_21_chars_scores_nothing():
    assert score_contact_completeness("", "x" * 20, "") == 0.0
    assert score_contact_completeness("", "x" * 21, "") == 15.0


def test_contact_phone_patterns_award_25_each_pattern_at_most_once():
    """Both regexes match a bare 10-digit run, but the loop `break`s — 25, never 50."""
    assert score_contact_completeness("Abcdef", "Call (512) 555-1234", "") == 50.0  # 25 title + 25 phone
    assert score_contact_completeness(
        "Abcdef", "512-555-1234 and (512) 555-1234", ""
    ) == 65.0  # 25 + 15 snippet + 25 phone (counted once)


def test_contact_email_awards_20():
    # 19-char snippet: no snippet bonus, so 25 title + 20 email.
    assert score_contact_completeness("Abcdef", "reach us at a@b.co", "") == 45.0


def test_contact_email_regex_accepts_plus_and_dotted_local_part():
    assert score_contact_completeness(
        "Abcdef", "first.last+tag@sub.example.co.uk", ""
    ) == 60.0  # 25 title + 15 snippet + 20 email


def test_contact_domain_bonus_covers_the_six_listed_tlds():
    for tld in (".com", ".net", ".org", ".io", ".us", ".co"):
        # 25 title + 15 snippet + 15 domain; the rest of the URL is ignored.
        assert score_contact_completeness("Abcdef", "x" * 21, f"https://x{tld}") == 55.0, tld


def test_contact_unlisted_tld_earns_no_domain_bonus():
    assert score_contact_completeness("Abcdef", "x" * 21, "https://x.museum") == 40.0


def test_contact_full_hardware_scores_exactly_100_not_more():
    """25 + 15 + 25 + 20 + 15 = 100 exactly; the cap must not manufacture a bonus."""
    assert score_contact_completeness(
        "Abcdef", "reach a@b.co call 512-555-1234", "https://x.com"
    ) == 100.0


# ── score_business_presence: years-in-business tiers + 13 trust signals x8 + 7 presence x5
def test_business_scores_zero_when_nothing_matches():
    assert score_business_presence("", "") == 0.0
    assert score_business_presence("x", "yr") == 0.0  # needs a digit before "yr"


def test_business_years_tiers_are_20_at_5_and_40_at_10():
    assert score_business_presence("x", "3 years experience") == 0.0
    assert score_business_presence("x", "5 years experience") == 20.0
    assert score_business_presence("x", "9 years experience") == 20.0
    assert score_business_presence("x", "10 years experience") == 40.0
    assert score_business_presence("x", "20 years experience") == 40.0


def test_business_all_seven_presence_signals_award_35():
    signals = ("free estimate free quote call now contact us service area "
               "satisfaction guaranteed warranty")
    assert score_business_presence("x", signals) == 35.0


def test_business_trust_signals_are_capped_at_100():
    """13 trust signals x 8 = 104, so the cap has to bite here."""
    signals = ("bbb accredited licensed insured bonded award top rated best of "
               "5-star recommended family owned locally owned since")
    assert score_business_presence("x", signals) == 100.0


def test_business_years_and_signals_accumulate():
    # 20 years -> 40, plus "licensed" (8) and "free estimate" (5).
    assert score_business_presence("x", "20 years, licensed, free estimate") == 53.0


def test_business_matching_is_case_insensitive():
    assert score_business_presence("x", "LICENSED") == 8.0


def test_business_swallows_overlong_year_number_instead_of_raising():
    """`int()` raises ValueError above the interpreter's digit cap; the except swallows
    it, so an absurd year count scores 0 instead of crashing the whole lead batch."""
    original = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)  # 640 is the lowest value CPython accepts
    try:
        assert score_business_presence("x", "9" * 700 + " years in business") == 0.0
        assert score_business_presence("x", "7 years in business") == 20.0
    finally:
        sys.set_int_max_str_digits(original)


# ── score_industry_relevance: 20 per matched keyword, then x industry weight
def test_industry_scores_zero_when_no_target_and_no_keyword_hits():
    assert score_industry_relevance("Welding Shop", "we weld things") == 0.0
    assert score_industry_relevance("t", "s") == 0.0


def test_industry_with_target_but_no_keyword_hit_returns_the_10_floor():
    assert score_industry_relevance("Plumber Co", "we fix pipes", "roofing") == 10.0


def test_industry_unknown_target_falls_back_to_the_target_word_itself():
    """An unregistered target searches for the literal word, then weights 0.7."""
    assert score_industry_relevance("Welding Shop", "we weld things", "welding") == 14.0


def test_industry_single_keyword_hit_is_20_times_the_weight():
    assert score_industry_relevance("Roof Co", "just roof", "roofing") == 20.0  # 20 x 1.00
    assert score_industry_relevance("Movers Inc", "mover company", "moving") == 12.0  # 20 x 0.60
    assert score_industry_relevance("x", "solar panel installation", "solar") == 38.0  # 40 x 0.95


def test_industry_counts_every_matching_keyword():
    # "kitchen" + "remodel" + "cabinet" = 3 hits -> 60, x 0.90.
    assert score_industry_relevance(
        "Kitchen Remodel", "full bath and cabinet", "kitchen_bath"
    ) == 54.0


def test_industry_five_keyword_hits_cap_at_100_before_the_weight():
    # 5 roofing keywords -> min(100, 100) x 1.00 = 100.
    assert score_industry_relevance("x", "roof roofing shingle gutter roofer", "roofing") == 100.0


def test_industry_without_target_takes_the_best_scoring_industry_not_the_first():
    """'remodel' appears in both construction and kitchen_bath; the winner is the
    higher-weight one (kitchen_bath 0.9 beats construction 0.85)."""
    assert score_industry_relevance("x", "general contractor", "construction") == 34.0  # 40 x 0.85
    assert score_industry_relevance("x", "a full kitchen remodel", None) == 36.0  # 40 x 0.90


def test_industry_without_target_caps_at_100_for_a_dense_listing():
    assert score_industry_relevance("x", "hvac heating cooling air conditioning furnace ac repair") == 100.0
    assert score_industry_relevance("x", "plumb pipe drain sewer water heater faucet") == 100.0


def test_industry_keyword_and_weight_tables_are_internally_consistent():
    """A keyword list with no weight entry silently falls back to 0.5 — every
    configured industry must have a real weight, or the score is wrong by design."""
    missing = [k for k in INDUSTRY_KEYWORDS if k not in INDUSTRY_WEIGHTS]
    assert missing == [], f"industries with no weight (silently scored x0.5): {missing}"
    assert all(0 < w <= 1.0 for w in INDUSTRY_WEIGHTS.values()), INDUSTRY_WEIGHTS


# ── score_location_match: city 40 + state 30 + zip 30, default 50, cap 100
def test_location_with_no_targets_is_the_neutral_50():
    assert score_location_match("serving anywhere", None, None, None) == 50.0
    assert score_location_match("serving anywhere") == 50.0


def test_location_zero_when_targets_are_given_and_none_appear():
    assert score_location_match("serving Houston", "Austin", "TX", "78701") == 0.0


def test_location_city_alone_is_40_and_city_plus_state_is_70():
    assert score_location_match("serving austin tx", "Austin") == 40.0
    assert score_location_match("Austin TX", "austin", "tx") == 70.0


def test_location_all_three_targets_cap_at_100():
    assert score_location_match("serving austin tx 78701", "Austin", "TX", "78701") == 100.0


def test_location_zip_match_is_case_sensitive_but_city_state_are_not():
    # The zip branch is a raw `in` on the lowercased snippet, so an uppercase zip
    # in the snippet cannot match. This asymmetry is real, so it is pinned.
    assert score_location_match("serving austin tx 78701", None, None, "78701") == 30.0
    assert score_location_match("serving austin tx 78701", None, None, "787010") == 0.0


# ── score_enrichment_potential: 30 for http + per-domain points, cap 100
def test_enrichment_zero_for_empty_or_scheme_less_url():
    assert score_enrichment_potential("") == 0.0
    # No http prefix -> no 30, but the facebook domain is still worth 15.
    assert score_enrichment_potential("www.facebook.com/x") == 15.0


def test_enrichment_linkedin_is_55():
    assert score_enrichment_potential("https://www.linkedin.com/in/x") == 55.0


def test_enrichment_domain_match_is_case_insensitive():
    assert score_enrichment_potential("HTTPS://WWW.BBB.ORG/x") == 20.0


def test_enrichment_stacks_every_domain_then_caps_at_100():
    # 30 http + 25+15+10+10+10+15+20+15+15 = 165 -> capped to 100.
    every = ("https://linkedin.com facebook.com instagram.com twitter.com "
             "youtube.com yelp.com bbb.org angi.com homeadvisor.com")
    assert score_enrichment_potential(every) == 100.0


# ── LeadScore
def test_lead_score_defaults_to_all_zeros_with_fresh_details():
    s = LeadScore()
    assert s.total == 0.0
    assert s.as_dict()["breakdown"] == {}
    # The two dataclasses must not share one mutable default.
    assert LeadScore().details is not s.details


def test_lead_score_as_dict_rounds_to_one_decimal():
    d = LeadScore(total=63.456, contact_completeness=100.0).as_dict()
    assert d["total"] == 63.5
    assert d["contact_completeness"] == 100.0
    assert set(d) == {
        "total", "contact_completeness", "business_presence",
        "industry_relevance", "location_match", "enrichment_potential", "breakdown",
    }


# ── score_lead: the weighted combination
REAL_TITLE = "Acme Roofing Co"
REAL_SNIPPET = ("Licensed and insured, free estimate in Austin TX 78701. "
                "Call 512-555-1234, email jane@acme.com")
REAL_URL = "https://www.linkedin.com/company/acme"


def test_score_lead_total_is_the_hand_computed_weighted_sum():
    # 100*.25 + 21*.15 + 40*.30 + 100*.20 + 55*.10
    expected = 100 * 0.25 + 21 * 0.15 + 40 * 0.30 + 100 * 0.20 + 55 * 0.10
    assert expected == 65.65
    s = score_lead(REAL_TITLE, REAL_SNIPPET, REAL_URL, "roofing", "Austin", "TX", "78701")
    assert s.total == pytest.approx(65.65)
    assert s.as_dict()["total"] == 65.7  # only as_dict() rounds


def test_score_lead_components_match_the_individual_scorers():
    s = score_lead(REAL_TITLE, REAL_SNIPPET, REAL_URL, "roofing", "Austin", "TX", "78701")
    assert s.contact_completeness == score_contact_completeness(REAL_TITLE, REAL_SNIPPET, REAL_URL)
    assert s.business_presence == score_business_presence(REAL_TITLE, REAL_SNIPPET)
    assert s.industry_relevance == score_industry_relevance(REAL_TITLE, REAL_SNIPPET, "roofing")
    assert s.location_match == score_location_match(REAL_SNIPPET, "Austin", "TX", "78701")
    assert s.enrichment_potential == score_enrichment_potential(REAL_URL)


def test_score_lead_of_an_empty_lead_is_10_not_zero():
    """The 50-point default location score is worth 10.0 weighted — a lead with
    nothing at all still scores 10, which is why the router's min_score filter
    must not assume zero is the floor."""
    s = score_lead("", "", "")
    assert s.total == pytest.approx(10.0)
    assert s.contact_completeness == 0.0
    assert s.location_match == 50.0


def test_score_lead_perfect_lead_is_exactly_100():
    """The weights sum to 1.0, so a lead maxed on all five dimensions is exactly 100 —
    a round number only holds if no weight is wrong."""
    s = score_lead(
        "Acme Roofing and Shingle Gutter Roofer",  # >5 chars -> 25
        "Free estimate in Austin TX 78701. Roof, roofing, shingle, gutter and roofer work. "
        "BBB accredited, licensed, insured, bonded, award winning, top rated, best of the "
        "best, 5-star, recommended, family owned, locally owned, since 1999. Warranty. "
        "Call 512-555-1234 or email jane@acme.com today.",  # every signal present
        "https://www.linkedin.com facebook.com instagram.com twitter.com youtube.com "
        "yelp.com bbb.org angi.com homeadvisor.com",
        "roofing",   # all 5 roofing keywords -> 100
        "austin", "tx", "78701",  # 40 + 30 + 30 -> 100
    )
    assert s.contact_completeness == 100.0
    assert s.business_presence == 100.0
    assert s.industry_relevance == 100.0
    assert s.location_match == 100.0
    assert s.enrichment_potential == 100.0
    assert s.total == 100.0


def test_score_lead_details_record_the_weights_and_measured_inputs():
    s = score_lead(REAL_TITLE, REAL_SNIPPET, REAL_URL)
    d = s.details
    assert d["weights"] == {
        "contact": 0.25, "business": 0.15, "industry": 0.30,
        "location": 0.20, "enrichment": 0.10,
    }
    assert sum(d["weights"].values()) == pytest.approx(1.0)
    assert d["title_length"] == len(REAL_TITLE)
    assert d["snippet_length"] == len(REAL_SNIPPET)
    assert d["has_domain"] is True


def test_score_lead_has_domain_only_checks_three_tlds():
    """has_domain is a diagnostic, not a score input: it omits .io/.us/.co which
    score_contact_completeness does count. Pinned so the divergence stays visible."""
    assert score_lead("a", "b", "https://x.io").details["has_domain"] is False
    assert score_lead("a", "b", "https://x.com").details["has_domain"] is True


def test_score_lead_is_deterministic_for_the_same_input():
    a = score_lead(REAL_TITLE, REAL_SNIPPET, REAL_URL, "roofing", "Austin", "TX", "78701")
    b = score_lead(REAL_TITLE, REAL_SNIPPET, REAL_URL, "roofing", "Austin", "TX", "78701")
    assert a.as_dict() == b.as_dict()


def test_score_lead_output_is_json_serialisable():
    import json

    s = score_lead(REAL_TITLE, REAL_SNIPPET, REAL_URL, "roofing", "Austin", "TX", "78701")
    assert json.loads(json.dumps(s.as_dict()))["total"] == 65.7
