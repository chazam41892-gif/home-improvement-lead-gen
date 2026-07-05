"""Batch trade discovery across all 44 trades.

Usage:
    python scripts/seed_trades.py
    python scripts/seed_trades.py --location "Austin, TX"
    python scripts/seed_trades.py --trade plumbing
    python scripts/seed_trades.py --location "Austin, TX" --limit 5
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.trades import TRADE_REGISTRY, TradeLeadDiscovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_trades")


def _summarize(results: dict[str, list], trade_ids: list[str]) -> dict:
    summary: dict[str, int] = {}
    for tid in trade_ids:
        leads = results.get(tid, [])
        if leads:
            summary[tid] = len(leads)
    return summary


def _save_results(results: dict[str, list], location: str) -> str:
    os.makedirs("data", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_loc = location.replace(" ", "_").replace(",", "").lower() if location else "default"
    path = f"data/trade_discovery_{safe_loc}_{ts}.json"

    serializable = {}
    for trade_id, leads in results.items():
        serializable[trade_id] = [lead.to_dict() for lead in leads]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, default=str)

    return path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed trade discovery across trades")
    parser.add_argument("--location", default="New York, NY", help="Search location")
    parser.add_argument("--trade", help="Single trade to discover (discover all if omitted)")
    parser.add_argument("--limit", type=int, default=10, help="Max leads per trade per platform")
    args = parser.parse_args()

    has_exa = bool(os.environ.get("EXA_API_KEY"))
    if not has_exa:
        print("No Exa key configured — run with keys for real data")
        print()

    discovery = TradeLeadDiscovery()

    if args.trade:
        trade_ids = [args.trade]
        if args.trade not in TRADE_REGISTRY:
            print(f"Unknown trade: {args.trade}")
            sys.exit(1)
    else:
        trade_ids = list(TRADE_REGISTRY.keys())

    print(f"Discovering leads for {len(trade_ids)} trade(s) in {args.location} ...")
    print()

    results: dict[str, list] = {}
    errors: list[str] = []

    for trade_id in trade_ids:
        name = TRADE_REGISTRY[trade_id]["name"]
        try:
            leads = await discovery.discover(
                trade=trade_id,
                location=args.location,
                max_per_platform=args.limit,
            )
            results[trade_id] = leads
            status = f"{len(leads)} leads" if leads else "no results"
            print(f"  [OK] {name:30s} {status}")
        except Exception as e:
            errors.append(trade_id)
            results[trade_id] = []
            print(f"  [ERR] {name:30s} error: {e}")

    print()

    total_leads = sum(len(v) for v in results.values())

    path = _save_results(results, args.location)
    print(f"Results saved → {path}")
    print(f"Total: {total_leads} lead(s) across {len(results)} trade(s)")

    if errors:
        print(f"Errors ({len(errors)}): {', '.join(errors)}")

    if not has_exa:
        print()
        print("Hint: set EXA_API_KEY in .env for real search results")
        print("      Run `python scripts/key_wizard.py` to set up all keys")


if __name__ == "__main__":
    asyncio.run(main())
