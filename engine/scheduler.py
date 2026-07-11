from __future__ import annotations

import asyncio
import logging
import time
import uuid
import os
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from engine.database import Database

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
        self._load_from_db()

    def _load_from_db(self):
        try:
            with Database.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM schedules")
                for r in cursor.fetchall():
                    s = ScanSchedule(
                        id=r["id"],
                        name=r["name"],
                        query=r["query"],
                        provider=r["provider"],
                        industry=r["industry"],
                        location=r["location"],
                        num_results=r["num_results"],
                        min_score=r["min_score"],
                        interval_minutes=r["interval_minutes"],
                        enabled=bool(r["enabled"]),
                        created_at=r["created_at"],
                        last_run=r["last_run"],
                        last_result_count=r["last_result_count"],
                        total_runs=r["total_runs"],
                    )
                    self._schedules[s.id] = s
                    # Load results
                    self._results[s.id] = self._load_results(s.id)
        except Exception as e:
            logger.error("Failed to load schedules from database: %s", e)

    def _save_schedule_to_db(self, s: ScanSchedule):
        try:
            with Database.get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO schedules (
                        id, name, query, provider, industry, location, num_results, min_score, interval_minutes, enabled, created_at, last_run, last_result_count, total_runs
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s.id, s.name, s.query, s.provider, s.industry, s.location, s.num_results, s.min_score, s.interval_minutes,
                    1 if s.enabled else 0, s.created_at, s.last_run, s.last_result_count, s.total_runs
                ))
                conn.commit()
        except Exception as e:
            logger.error("Failed to save schedule to database: %s", e)

    def _save_results(self, schedule_id: str, leads: List[Dict[str, Any]]):
        os.makedirs("data/schedules", exist_ok=True)
        path = f"data/schedules/{schedule_id}_results.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(leads, f, default=str)
        except Exception as e:
            logger.error("Failed to save schedule results to file: %s", e)

    def _load_results(self, schedule_id: str) -> List[Dict[str, Any]]:
        path = f"data/schedules/{schedule_id}_results.json"
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load schedule results from file: %s", e)
            return []

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
        self._save_schedule_to_db(schedule)
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
        self._save_schedule_to_db(sched)
        return sched

    def delete_schedule(self, schedule_id: str) -> bool:
        self._results.pop(schedule_id, None)
        ok = self._schedules.pop(schedule_id, None) is not None
        if ok:
            try:
                with Database.get_connection() as conn:
                    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
                    conn.commit()
                path = f"data/schedules/{schedule_id}_results.json"
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                logger.error("Failed to delete schedule from database: %s", e)
        return ok

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
            self._save_schedule_to_db(sched)

            if leads:
                existing = self._results.get(sched.id, [])
                existing_ids = {l.get("id") for l in existing}
                new_leads = [l for l in leads if l.get("id") not in existing_ids]
                existing.extend(new_leads)
                self._results[sched.id] = existing
                self._save_results(sched.id, existing)
                logger.info(f"Schedule '{sched.name}': found {len(new_leads)} new leads")

        except Exception as e:
            logger.error(f"Schedule '{sched.name}' error: {e}")
