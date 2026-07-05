import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from .trades import TRADE_REGISTRY, get_trade_config
from .base import TradeLead
from .platforms import PLATFORM_SEARCHERS, set_exa_provider

if TYPE_CHECKING:
    from ..search.exa import ExaSearchProvider

logger = logging.getLogger(__name__)


class TradeLeadDiscovery:
    def __init__(self, exa_provider: Optional["ExaSearchProvider"] = None):
        self._results: dict[str, list[TradeLead]] = {}
        self._lock = asyncio.Lock()
        if exa_provider is not None:
            set_exa_provider(exa_provider)

    async def discover(
        self,
        trade: str,
        location: str,
        platforms: Optional[list[str]] = None,
        max_per_platform: int = 15,
    ) -> list[TradeLead]:
        config = get_trade_config(trade)
        if not config:
            logger.warning("Unknown trade: %s", trade)
            return []

        target_platforms = platforms or config["platforms"]
        all_leads: list[TradeLead] = []
        seen_keys: set[str] = set()

        tasks = []
        for platform in target_platforms:
            searcher = PLATFORM_SEARCHERS.get(platform)
            if searcher:
                tasks.append(searcher(trade, location, max_per_platform))
            else:
                logger.warning("No searcher for platform: %s", platform)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("Platform search failed: %s", result)
                continue
            for lead in result:
                key = lead.website or lead.business_name
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    all_leads.append(lead)

        async with self._lock:
            self._results.setdefault(f"{trade}:{location}", [])
            self._results[f"{trade}:{location}"].extend(all_leads)

        logger.info("Discovered %d leads for %s in %s", len(all_leads), trade, location)
        return all_leads

    async def discover_all(
        self,
        trades: Optional[list[str]] = None,
        location: str = "",
        max_per_trade: int = 20,
    ) -> dict[str, list[TradeLead]]:
        target_trades = trades or list(TRADE_REGISTRY.keys())
        results: dict[str, list[TradeLead]] = {}

        for trade in target_trades:
            leads = await self.discover(trade, location, max_per_platform=max_per_trade)
            results[trade] = leads

        return results

    async def discover_best_platform(
        self,
        trade: str,
        location: str,
        max_results: int = 25,
    ) -> list[TradeLead]:
        config = get_trade_config(trade)
        if not config:
            return []
        return await self.discover(trade, location, platforms=[config["best_platform"]], max_per_platform=max_results)

    def get_results(self, key: str = "") -> dict[str, list[TradeLead]]:
        if key:
            return {key: self._results.get(key, [])}
        return self._results

    def get_leads_for_trade(self, trade: str, location: str = "") -> list[TradeLead]:
        combined = []
        for key, leads in self._results.items():
            if key.startswith(f"{trade}:"):
                if not location or location in key:
                    combined.extend(leads)
        return combined
