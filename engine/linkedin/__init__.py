"""
LinkedIn acquisition + signals — ported from sios.leadgen (audit 2026-09-27,
parity gap C).

WHY THIS EXISTS
---------------
The standalone module could not touch LinkedIn at all: no post-signal scoring, no
compliance gating, no prospect workspace, no suppression list. Those ~2,000 LOC
lived only inside SIOS. They are now available to the standalone product too, so
both products can run the same LinkedIn play.

DEPENDENCIES
------------
pydantic (2.x) and aiohttp are required by these modules. Both are already
dependencies of the standalone. aiohttp is soft-imported inside providers.py.

Deliberate difference from the SIOS original: intra-package imports are
engine.linkedin.*, not sios.leadgen.*. No sios.* import may remain — assert in
tests.
"""

__all__ = ["linkedin_acquisition", "linkedin_signals"]


def __getattr__(name):
    if name in __all__:
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
