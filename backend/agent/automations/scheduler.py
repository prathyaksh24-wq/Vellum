"""AutomationScheduler — turns store automations into APScheduler jobs.

Each active automation registers one job (``max_instances=1``, ``coalesce``,
misfire grace matching the existing jobs). When a job fires, the run gates:
paused automations do nothing, non-full-access automations do not run
unattended (recorded as a failed run with a clear error), and a fire whose
automation already has a run in flight is skipped. One-shot schedules
(relative / ISO) whose moment has already passed are not registered again on
startup, so a restart cannot re-fire an expired one-shot.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.automations.runner import run_automation_now
from agent.automations.store import AutomationStore

logger = logging.getLogger(__name__)

JOB_PREFIX = "automation-"
MISFIRE_GRACE_SECONDS = 3600


class AutomationScheduler:
    def __init__(self, store: AutomationStore, scheduler: Any | None = None, executor=None) -> None:
        self.store = store
        self.scheduler = scheduler if scheduler is not None else AsyncIOScheduler()
        self.executor = executor or run_automation_now

    def install_all(self) -> list[str]:
        registered: list[str] = []
        for automation in self.store.list():
            if automation.get("state") == "active" and self.install(automation):
                registered.append(automation["id"])
        return registered

    def install(self, automation: dict[str, Any]) -> bool:
        job_id = self._job_id(automation["id"])
        trigger = self._trigger(automation)
        if trigger is None:
            return False
        self.scheduler.add_job(
            self._fire,
            trigger=trigger,
            args=[automation["id"]],
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )
        return True

    def uninstall(self, automation_id: str) -> None:
        try:
            self.scheduler.remove_job(self._job_id(automation_id))
        except Exception:  # noqa: BLE001 — JobLookupError on a missing job
            pass

    def sync(self, automation_ids: list[str]) -> None:
        known = set(automation_ids)
        for job in list(self.scheduler.get_jobs() or []):
            job_id = str(getattr(job, "id", "") or "")
            if not job_id.startswith(JOB_PREFIX):
                continue
            automation_id = job_id[len(JOB_PREFIX):]
            if automation_id not in known:
                self.uninstall(automation_id)

    def sync_one(self, automation_id: str) -> None:
        try:
            automation = self.store.get(automation_id)
        except ValueError:
            self.uninstall(automation_id)
            return
        if automation.get("state") == "active":
            self.install(automation)
        else:
            self.uninstall(automation_id)

    async def _fire(self, automation_id: str) -> None:
        try:
            automation = self.store.get(automation_id)
        except ValueError:
            return
        if automation.get("state") != "active":
            return
        permission = automation.get("permission") or {}
        if not permission.get("full_access"):
            self._record_skipped(self.store, automation_id, "unattended runs require the full-access opt-in")
            return
        if self._busy(automation):
            logger.info("[AUTOMATIONS] Skip fire for %s: a run is already in flight", automation_id)
            return
        try:
            await self.executor(automation, self.store)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AUTOMATIONS] Run %s failed: %s", automation_id, exc)
            self._record_skipped(self.store, automation_id, str(exc))

    @staticmethod
    def _record_skipped(store: AutomationStore, automation_id: str, reason: str) -> None:
        from uuid import uuid4

        run_id = f"run-{uuid4().hex[:16]}"
        store.record_run(automation_id, run_id)
        store.finish_run(automation_id, run_id, status="failed", error=reason)

    @staticmethod
    def _busy(automation: dict[str, Any]) -> bool:
        return any(run.get("status") == "running" for run in automation.get("run_history", []))

    @staticmethod
    def _job_id(automation_id: str) -> str:
        return f"{JOB_PREFIX}{automation_id}"

    @staticmethod
    def _trigger(automation: dict[str, Any]):
        schedule = automation.get("schedule") or {}
        kind = schedule.get("kind")
        if kind == "cron":
            return CronTrigger.from_crontab(str(schedule.get("expression")), timezone=timezone.utc)
        if kind == "interval":
            return IntervalTrigger(
                seconds=int(schedule.get("seconds") or 0),
                start_date=_interval_start_date(schedule),
                timezone=timezone.utc,
            )
        if kind in ("relative", "iso"):
            run_at = _one_shot_run_at(schedule)
            if run_at is None or run_at <= datetime.now(timezone.utc):
                return None
            return DateTrigger(run_date=run_at, timezone=timezone.utc)
        return None


def _interval_start_date(schedule: dict[str, Any]) -> datetime:
    now = datetime.now(timezone.utc)
    at_time = schedule.get("at_time")
    if not at_time:
        return now
    hour, minute = (int(part) for part in str(at_time).split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _one_shot_run_at(schedule: dict[str, Any]) -> datetime | None:
    kind = schedule.get("kind")
    if kind == "relative":
        seconds = int(schedule.get("seconds") or 0)
        return datetime.now(timezone.utc) + timedelta(seconds=seconds)
    if kind == "iso":
        try:
            return datetime.fromisoformat(str(schedule.get("run_at")).replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def install_automation_jobs(scheduler: Any, store: AutomationStore | None = None) -> AutomationScheduler:
    """Register every active store automation and hook future mutations."""
    from agent.automations.api import get_store, set_mutation_hook

    automation_scheduler = AutomationScheduler(store if store is not None else get_store(), scheduler=scheduler)
    automation_scheduler.install_all()
    set_mutation_hook(automation_scheduler.sync_one)
    return automation_scheduler
