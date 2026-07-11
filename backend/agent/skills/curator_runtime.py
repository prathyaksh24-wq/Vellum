from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from agent.skills.curator import SkillCurator


class CuratorRuntime:
    def __init__(self, root: str | Path = ".skills", *, logs_root: str | Path = "data/logs/curator"):
        self.curator = SkillCurator(root, logs_root=logs_root)
        self._last_activity = datetime.now(timezone.utc)
        self._lock = RLock()

    def mark_activity(self, now: datetime | None = None) -> None:
        with self._lock:
            self._last_activity = now or datetime.now(timezone.utc)

    def idle_hours(self, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        with self._lock:
            return max(0.0, (current - self._last_activity).total_seconds() / 3600)

    def tick(self, now: datetime | None = None) -> dict:
        current = now or datetime.now(timezone.utc)
        return self.curator.run(now=current, idle_hours=self.idle_hours(current))


_RUNTIME: CuratorRuntime | None = None


def get_curator_runtime() -> CuratorRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = CuratorRuntime()
    return _RUNTIME


def install_curator_ticker(scheduler) -> CuratorRuntime:
    runtime = get_curator_runtime()
    runtime.tick()
    scheduler.add_job(runtime.tick, "interval", hours=1, id="skill_curator_tick", replace_existing=True)
    return runtime
