"""Tests for the ported LinkedIn acquisition + signals package (parity gap C).

The standalone previously had NO LinkedIn capability at all. These tests exercise
real logic — URL canonicalization, viral scoring, dedup, and the compliance gate
that decides whether an outreach draft may be sent — rather than just importing.
"""
import pytest

from engine.linkedin.linkedin_signals.models import (
    Engagement, ViralScore, canonicalize_linkedin_url,
    score_post, deduplicate_engagements,
)
from engine.linkedin.linkedin_signals.workflow import ComplianceGate, PromptWorkflow
from engine.linkedin.linkedin_acquisition.catalog import get_catalog, CAPABILITY_CATALOG


# ── URL canonicalization ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("https://www.linkedin.com/in/jane/", "https://www.linkedin.com/in/jane"),
    ("https://linkedin.com/in/jane", "https://www.linkedin.com/in/jane"),
    ("linkedin.com/in/jane", "https://www.linkedin.com/in/jane"),
    ("http://WWW.LinkedIn.com/in/jane/", "https://www.linkedin.com/in/jane"),
    ("https://www.linkedin.com/in/jane?utm=x#frag", "https://www.linkedin.com/in/jane"),
])
def test_canonicalize_linkedin_url(raw, expected):
    assert canonicalize_linkedin_url(raw) == expected


def test_canonicalize_leaves_non_linkedin_alone():
    assert canonicalize_linkedin_url("https://example.com/in/jane") == \
        "https://example.com/in/jane"


def test_canonicalize_empty():
    assert canonicalize_linkedin_url("") == ""
    assert canonicalize_linkedin_url(None) == ""


# ── viral scoring ──────────────────────────────────────────────────────────
def test_score_post_weights_comments_and_reposts_higher():
    s = score_post(reactions=0, comments=10, reposts=0, age_hours=1)
    assert s.weighted_engagement == 30, "a comment must count 3x a reaction"

    s2 = score_post(reactions=0, comments=0, reposts=10, age_hours=1)
    assert s2.weighted_engagement == 40, "a repost must count 4x a reaction"


def test_score_post_flags_viral_by_weight():
    assert score_post(reactions=200, comments=0, reposts=0, age_hours=10).is_viral


def test_score_post_flags_viral_by_velocity():
    # age is floored at 1.0h (max(age,1.0)), so velocity == weighted for a 1h-old
    # post. Velocity therefore only bites at/above 50, which is also the weight
    # threshold's neighbourhood.
    s = score_post(reactions=50, comments=0, reposts=0, age_hours=1.0)
    assert s.velocity >= 50.0
    assert s.is_viral


def test_score_post_velocity_floors_age_at_one_hour():
    """A brand-new post is scored as if 1h old, so a burst cannot manufacture
    infinite velocity from age_hours < 1."""
    s = score_post(reactions=10, comments=0, reposts=0, age_hours=0.01)
    assert s.velocity == 10.0, s


def test_score_post_not_viral_when_small_and_slow():
    assert not score_post(reactions=1, comments=0, reposts=0, age_hours=48).is_viral


def test_score_post_handles_missing_age():
    s = score_post(reactions=10, comments=0, reposts=0, age_hours=None)
    assert s.velocity == 0.0
    assert isinstance(s, ViralScore)


def test_score_post_clamps_negatives():
    """Negative counts must not produce a negative score."""
    s = score_post(reactions=-5, comments=-5, reposts=-5, age_hours=1)
    assert s.weighted_engagement == 0


# ── engagement dedup ───────────────────────────────────────────────────────
def test_dedup_by_actor_urn():
    a = Engagement(post_urn="p1", actor_urn="urn:li:1", action="like")
    b = Engagement(post_urn="p1", actor_urn="urn:li:1", action="comment")
    out = deduplicate_engagements([a, b])
    assert len(out) == 1, "same actor engaging twice must collapse to one"


def test_dedup_merges_actions():
    a = Engagement(post_urn="p1", actor_urn="urn:li:1", action="like")
    b = Engagement(post_urn="p1", actor_urn="urn:li:1", action="share")
    out = deduplicate_engagements([a, b])
    assert len(out) == 1
    assert set(out[0].actions) >= {"LIKE", "SHARE"}, out[0].actions


def test_dedup_keeps_distinct_actors():
    a = Engagement(post_urn="p1", actor_urn="urn:li:1")
    b = Engagement(post_urn="p1", actor_urn="urn:li:2")
    assert len(deduplicate_engagements([a, b])) == 2


def test_dedup_drops_unidentifiable():
    a = Engagement(post_urn="p1", actor_urn="", profile_url="")
    assert deduplicate_engagements([a]) == []


def test_engagement_canonicalizes_profile_url():
    e = Engagement(post_urn="p", actor_urn="u",
                    profile_url="https://www.linkedin.com/in/jane/")
    assert e.profile_url == "https://www.linkedin.com/in/jane"


def test_engagement_action_is_uppercased():
    e = Engagement(post_urn="p", actor_urn="u", action="like")
    assert e.actions == ["LIKE"]


# ── compliance gate ────────────────────────────────────────────────────────
GOOD_POLICY = {
    "lawful_basis": "legitimate interest",
    "sender_name": "Chaz",
    "business_name": "Metanoia",
    "postal_address": "123 Main St",
    "opt_out_text": "Reply STOP to opt out",
}


def test_compliance_approves_a_clean_draft():
    gate = ComplianceGate()
    lead = {"verification_status": "verified"}
    draft = {"subject": "Quick question", "body_text": "Hi — Reply STOP to opt out."}
    r = gate.evaluate(lead, draft, GOOD_POLICY)
    assert r["approved"] is True, r


def test_compliance_blocks_unverified_email():
    """The single most important rule: never send to an unverified address."""
    gate = ComplianceGate()
    draft = {"subject": "Hi", "body_text": "Hello — Reply STOP to opt out"}
    r = gate.evaluate({"verification_status": "bounced"}, draft, GOOD_POLICY)
    assert r["approved"] is False
    assert "email_not_verified" in r["violations"]


def test_compliance_blocks_missing_opt_out():
    gate = ComplianceGate()
    lead = {"verification_status": "ok"}
    draft = {"subject": "Hi", "body_text": "Hello there"}  # no opt-out text
    r = gate.evaluate(lead, draft, GOOD_POLICY)
    assert r["approved"] is False
    assert "opt_out_missing_from_body" in r["violations"]


def test_compliance_blocks_incomplete_draft():
    gate = ComplianceGate()
    r = gate.evaluate({"verification_status": "ok"},
                      {"subject": "", "body_text": "x"}, GOOD_POLICY)
    assert "draft_incomplete" in r["violations"]


def test_compliance_reports_missing_policy_fields():
    gate = ComplianceGate()
    r = gate.evaluate({"verification_status": "ok"},
                      {"subject": "s", "body_text": "b"}, {"lawful_basis": "legit"})
    assert r["approved"] is False
    assert "postal_address" in r["missing"]


# ── catalog ────────────────────────────────────────────────────────────────
def test_catalog_is_non_empty_and_typed():
    """get_catalog() returns a SUMMARY DICT, not a list of capabilities."""
    cat = get_catalog()
    assert isinstance(cat, dict)
    assert cat["capability_count"] > 0
    assert cat["method_count"] >= cat["capability_count"]
    assert len(cat["capabilities"]) == cat["capability_count"]
    assert len(CAPABILITY_CATALOG) == cat["capability_count"]


def test_catalog_is_a_deep_copy():
    """Mutating the returned catalog must not corrupt the module-level tuple."""
    cat = get_catalog()
    cat["capabilities"][0]["name"] = "MUTATED"
    assert get_catalog()["capabilities"][0]["name"] != "MUTATED"


# ── no sios.* imports may survive the port ─────────────────────────────────
def test_no_sios_imports_remain_in_port():
    """The port must be self-contained; a leftover sios.* import would break the
    standalone the moment this package is imported."""
    import pathlib
    import engine.linkedin as pkg
    root = pathlib.Path(pkg.__file__).parent
    offenders = []
    for py in root.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("from sios", "import sios")):
                offenders.append(f"{py.name}:{i}: {stripped}")
    assert not offenders, "sios.* imports left in the port:\n" + "\n".join(offenders)
