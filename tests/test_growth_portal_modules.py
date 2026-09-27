"""Tests for the Growth portal module registry (audit 2026-09-27).

`modules.py` is the extension point AGENTS.md tells agents to edit, and the
plan gate behind every paywall in the portal, so the guarantees pinned here
are the ones a paid customer would notice breaking:

  * the plan ladder is ordered and index-based, and an unknown plan string
    degrades to `free` (deny) rather than crashing or granting access;
  * access is `>=`, so a higher plan always includes a lower-tier module;
  * a custom `access_check` fully replaces the plan comparison;
  * re-registering a module id raises instead of silently shadowing the
    existing module;
  * `list_modules()` is a fresh dict per call.

Read from the implementation: `_PLAN_ORDER` is a plain list and `_plan_index`
returns 0 on `ValueError`, which is exactly why a typo'd plan string is
handled as "lowest tier" rather than rejected.
"""
import pytest

from engine.growth_portal.modules import (
    MODULE_REGISTRY,
    Module,
    _plan_index,
    can_access_module,
    get_module,
    list_modules,
    plans,
    register_module,
)

EXPECTED_PLANS = ["free", "starter", "growth", "pro", "enterprise"]


@pytest.fixture
def registry():
    """Snapshot the global registry so registry-mutating tests cannot leak."""
    before = dict(MODULE_REGISTRY)
    leadgen = MODULE_REGISTRY["leadgen"]
    leadgen_before = (leadgen.min_plan, leadgen.access_check, list(leadgen.tags))
    yield MODULE_REGISTRY
    MODULE_REGISTRY.clear()
    MODULE_REGISTRY.update(before)
    leadgen.min_plan, leadgen.access_check, tags = leadgen_before
    leadgen.tags[:] = tags


# ── the plan ladder ────────────────────────────────────────────────────────
def test_plans_are_ordered_least_to_most_privileged():
    assert plans() == EXPECTED_PLANS


def test_plans_returns_a_copy_so_a_caller_cannot_corrupt_the_ladder():
    got = plans()
    got.append("ultra")
    assert plans() == EXPECTED_PLANS, "plans() must not hand out _PLAN_ORDER itself"


@pytest.mark.parametrize("plan,index", [(p, i) for i, p in enumerate(EXPECTED_PLANS)])
def test_plan_index_matches_position_in_the_ladder(plan, index):
    assert _plan_index(plan) == index


def test_plan_index_is_case_insensitive():
    assert _plan_index("PRO") == _plan_index("pro")
    assert _plan_index("Enterprise") == _plan_index("enterprise")


@pytest.mark.parametrize("plan", ["", "platinum", "enterprise ", "fre", "pro+"])
def test_unrecognised_plan_degrades_to_the_lowest_tier(plan):
    """An unknown plan must map to index 0 so it can never unlock anything."""
    assert _plan_index(plan) == 0


# ── get_module ─────────────────────────────────────────────────────────────
def test_get_module_returns_the_registered_dataclass():
    m = get_module("leadgen")
    assert m is MODULE_REGISTRY["leadgen"]
    assert m.id == "leadgen"
    assert m.slug == "leadgen"


def test_get_module_returns_none_for_an_unknown_id():
    assert get_module("no-such-module") is None


# ── list_modules ───────────────────────────────────────────────────────────
def test_list_modules_exposes_exactly_the_public_catalog_fields():
    """`access_check` is a callable and must not leak into the catalog JSON."""
    entry = list_modules()[0]
    assert sorted(entry) == ["description", "icon", "id", "min_plan", "name",
                             "route_path", "slug", "tags"]
    assert "access_check" not in entry
    assert "required_plans" not in entry


def test_list_modules_contains_the_shipped_leadgen_module():
    entries = {e["id"]: e for e in list_modules()}
    assert "leadgen" in entries
    leadgen = entries["leadgen"]
    assert leadgen["name"] == "Lead Gen Pro"
    assert leadgen["min_plan"] == "starter"
    assert leadgen["route_path"] == "/module/leadgen"
    assert leadgen["tags"] == ["B2B", "Lead Gen", "Real Estate", "Sales"]


def test_list_modules_preserves_registry_insertion_order():
    register_module(Module(id="zzz", name="Z", slug="zzz", description="d"))
    assert [e["id"] for e in list_modules()] == ["leadgen", "zzz"]


# ── the paywall ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("plan,expected", [
    ("free", False),      # index 0 < starter(1) — locked
    ("starter", True),    # index 1 >= 1     — exact match opens
    ("growth", True),
    ("pro", True),
    ("enterprise", True),
])
def test_access_is_a_greater_than_or_equal_plan_comparison(plan, expected):
    assert can_access_module("leadgen", plan) is expected


def test_an_unknown_module_is_never_accessible_on_any_plan():
    assert can_access_module("ghost", "enterprise") is False


def test_a_module_gated_on_a_higher_plan_stays_locked_for_a_lower_plan(registry):
    registry["leadgen"].min_plan = "enterprise"
    assert can_access_module("leadgen", "pro") is False
    assert can_access_module("leadgen", "enterprise") is True


def test_a_custom_access_check_replaces_the_plan_comparison(registry):
    """A bespoke check is authoritative — min_plan is not also consulted."""
    seen = {}

    def only_enterprise(module, org_plan):
        seen["module"] = module
        seen["plan"] = org_plan
        return org_plan == "enterprise"

    registry["leadgen"].access_check = only_enterprise
    assert can_access_module("leadgen", "pro") is False
    assert seen["module"] is registry["leadgen"]
    assert seen["plan"] == "pro"
    assert can_access_module("leadgen", "enterprise") is True


def test_a_custom_access_check_receives_the_module_not_its_id(registry):
    got = []
    registry["leadgen"].access_check = lambda module, plan: got.append(module) or True
    can_access_module("leadgen", "free")
    assert got == [registry["leadgen"]]


def test_a_custom_access_check_can_deny_a_plan_that_otherwise_qualifies(registry):
    registry["leadgen"].access_check = lambda module, plan: False
    assert can_access_module("leadgen", "enterprise") is False


# ── registration ───────────────────────────────────────────────────────────
def test_register_module_adds_the_module_and_returns_none():
    m = Module(id="newbie", name="New", slug="newbie", description="d")
    assert register_module(m) is None
    try:
        assert MODULE_REGISTRY["newbie"] is m
        assert get_module("newbie") is m
    finally:
        MODULE_REGISTRY.pop("newbie")


def test_registering_a_duplicate_id_raises_instead_of_silently_shadowing():
    """Silently replacing a live module would un-price it for existing orgs."""
    with pytest.raises(ValueError, match="Module leadgen already registered"):
        register_module(Module(id="leadgen", name="Impostor", slug="x",
                               description="d"))
    assert MODULE_REGISTRY["leadgen"].name == "Lead Gen Pro", "registry unchanged"


def test_a_duplicate_registration_leaves_the_original_untouched():
    before = MODULE_REGISTRY["leadgen"]
    with pytest.raises(ValueError):
        register_module(Module(id="leadgen", name="Impostor", slug="x",
                               description="d"))
    assert MODULE_REGISTRY["leadgen"] is before


# ── dataclass defaults ─────────────────────────────────────────────────────
def test_module_defaults_are_the_permissive_ones():
    m = Module(id="x", name="X", slug="x", description="d")
    assert m.min_plan == "free", "a module with no stated tier must not gate anyone out"
    assert m.icon == "box"
    assert m.tags == []
    assert m.route_path == ""
    assert m.required_plans == []
    assert m.access_check is None


def test_module_default_tags_are_not_shared_between_instances():
    """A mutable default_factory must not alias one instance's list to another."""
    a = Module(id="a", name="A", slug="a", description="d")
    b = Module(id="b", name="B", slug="b", description="d")
    a.tags.append("only-a")
    assert b.tags == []
