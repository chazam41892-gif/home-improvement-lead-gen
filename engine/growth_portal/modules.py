"""Growth portal module registry.

Each module represents a B2B product or capability available through
growth.leviathansi.xyz. AI agents can add new modules here by following
AGENTS.md in the project root.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class Module:
    id: str
    name: str
    slug: str
    description: str
    icon: str = "box"
    min_plan: str = "free"
    tags: List[str] = field(default_factory=list)
    route_path: str = ""
    required_plans: List[str] = field(default_factory=list)
    # Function(module_id, org_plan) -> bool
    access_check: Optional[Callable[[str, str], bool]] = None


# Plan hierarchy (lower index = more access)
_PLAN_ORDER = ["free", "starter", "growth", "pro", "enterprise"]


def _plan_index(plan: str) -> int:
    try:
        return _PLAN_ORDER.index(plan.lower())
    except ValueError:
        return 0


def _default_access_check(module: Module, org_plan: str) -> bool:
    return _plan_index(org_plan) >= _plan_index(module.min_plan)


MODULE_REGISTRY: Dict[str, Module] = {
    "leadgen": Module(
        id="leadgen",
        name="Lead Gen Pro",
        slug="leadgen",
        description="Multi-platform lead discovery, scoring, enrichment, and conversion for home improvement and real estate developers.",
        icon="target",
        min_plan="starter",
        tags=["B2B", "Lead Gen", "Real Estate", "Sales"],
        route_path="/module/leadgen",
    ),
}


def list_modules() -> List[Dict[str, any]]:
    return [
        {
            "id": m.id,
            "name": m.name,
            "slug": m.slug,
            "description": m.description,
            "icon": m.icon,
            "min_plan": m.min_plan,
            "tags": m.tags,
            "route_path": m.route_path,
        }
        for m in MODULE_REGISTRY.values()
    ]


def get_module(module_id: str) -> Optional[Module]:
    return MODULE_REGISTRY.get(module_id)


def can_access_module(module_id: str, org_plan: str) -> bool:
    module = get_module(module_id)
    if not module:
        return False
    if module.access_check:
        return module.access_check(module, org_plan)
    return _default_access_check(module, org_plan)


def register_module(module: Module) -> None:
    if module.id in MODULE_REGISTRY:
        raise ValueError(f"Module {module.id} already registered")
    MODULE_REGISTRY[module.id] = module


def plans() -> List[str]:
    return list(_PLAN_ORDER)
