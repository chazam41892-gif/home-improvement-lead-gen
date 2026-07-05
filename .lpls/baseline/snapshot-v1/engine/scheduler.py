from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ScanScheduler")


@dataclass
class ScanSchedule:
    id: str
    name: str
    query: str
    provider: str
    industry: str
    location: str
    num_results: int
    min_score: float
    interval_minutes: int
    enabled: bool
    created_at: str
    last_run: Optional[str] = None
    last_result_count: int = 0
    total_runs: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "query": self.query,
            "provider": self.provider,
            "industry": self.industry,
            "location": self.location,
            "num_results": self.num_results,
            "min_score": self.min_score,
            "interval_minutes": self.interval_minutes,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "last_result_count": self.last_result_count,
            "total_runs": self.total_runs,
        }


class ScanScheduler:
    def __init__(self):
        self._schedules: Dict[str, ScanSchedule] = {}
        self._results: Dict[str, List[Dict[str, Any]]] = {}
        self._search_fn: Optional[Callable] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def register_search_fn(self, fn: Callable):
        self._search_fn = fn

    def add_schedule(self, config: Dict[str, Any]) -> ScanSchedule:
        schedule = ScanSchedule(
            id=str(uuid.uuid4())[:12],
            name=config.get("name", "Untitled Scan"),
            query=config.get("query", ""),
            provider=config.get("provider", "exa"),
            industry=config.get("industry", ""),
            location=config.get("location", ""),
            num_results=config.get("num_results", 25),
            min_score=config.get("min_score", 30.0),
            interval_minutes=config.get("interval_minutes", 60),
            enabled=config.get("enabled", True),
            created_at=datetime.now().isoformat(),
        )
        self._schedules[schedule.id] = schedule
        logger.info(f"Added schedule '{schedule.name}' ({schedule.id}) every {schedule.interval_minutes}min")
        return schedule

    def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> Optional[ScanSchedule]:
        sched = self._schedules.get(schedule_id)
        if not sched:
            return None
        for key in ("name", "query", "provider", "industry", "location",
                     "num_results", "min_score", "interval_minutes", "enabled"):
            if key in updates:
                setattr(sched, key, updates[key])
        return sched

    def delete_schedule(self, schedule_id: str) -> bool:
        self._results.pop(schedule_id, None)
        return self._schedules.pop(schedule_id, None) is not None

    def get_schedule(self, schedule_id: str) -> Optional[ScanSchedule]:
        return self._schedules.get(schedule_id)

    def list_schedules(self) -> List[Dict[str, Any]]:
        return [s.as_dict() for s in sorted(
            self._schedules.values(), key=lambda s: s.created_at, reverse=True
        )]

    def get_results(self, schedule_id: str) -> List[Dict[str, Any]]:
        return self._results.get(schedule_id, [])

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._schedules)
        enabled = sum(1 for s in self._schedules.values() if s.enabled)
        total_runs = sum(s.total_runs for s in self._schedules.values())
        return {
            "total_schedules": total,
            "enabled": enabled,
            "total_runs": total_runs,
            "running": self._running,
        }

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Scan scheduler started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Scan scheduler stopped")

    async def _loop(self):
        while self._running:
            now = time.time()
            for sched in list(self._schedules.values()):
                if not sched.enabled:
                    continue
                interval_sec = sched.interval_minutes * 60
                if sched.last_run:
                    last = datetime.fromisoformat(sched.last_run).timestamp()
                    if (now - last) < interval_sec:
                        continue

                await self._execute(sched)

            await asyncio.sleep(30)

    async def _execute(self, sched: ScanSchedule):
        if not self._search_fn:
            logger.warning(f"Schedule '{sched.name}': no search function registered")
            return

        logger.info(f"Schedule '{sched.name}': executing scan")
        try:
            result = await self._search_fn(
                query=sched.query,
                num_results=sched.num_results,
                min_score=sched.min_score,
                provider=sched.provider,
            )
            leads = result.get("leads", []) if isinstance(result, dict) else []
            sched.last_run = datetime.now().isoformat()
            sched.last_result_count = len(leads)
            sched.total_runs += 1

            if leads:
                existing = self._results.get(sched.id, [])
                existing_ids = {l.get("id") for l in existing}
                new_leads = [l for l in leads if l.get("id") not in existing_ids]
                existing.extend(new_leads)
                self._results[sched.id] = existing
                logger.info(f"Schedule '{sched.name}': found {len(new_leads)} new leads")

        except Exception as e:
            logger.error(f"Schedule '{sched.name}' error: {e}")
