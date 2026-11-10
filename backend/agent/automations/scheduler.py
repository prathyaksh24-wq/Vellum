"""AutomationScheduler — turns store automations into APScheduler jobs.

Each active automation with unattended access registers one job (``max_instances=1``, ``coalesce``,
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
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.automations.runner import run_automation_now
from agent.automations.schedules import cron_trigger
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
        if not (automation.get("permission") or {}).get("full_access"):
            self.uninstall(automation["id"])
            return False
        try:
            trigger = self._trigger(automation)
        except (ValueError, KeyError, OverflowError) as exc:
            logger.warning("[AUTOMATIONS] Invalid saved schedule %s: %s", automation["id"], exc)
            trigger = None
        if trigger is None:
            self.uninstall(automation["id"])
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

    def next_run_at(self, automation_id: str) -> datetime | None:
        job = self.scheduler.get_job(self._job_id(automation_id))
        return getattr(job, "next_run_time", None)

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
            zone = ZoneInfo(schedule["time_zone"]) if schedule.get("time_zone") else timezone.utc
            return cron_trigger(str(schedule.get("expression")), zone=zone, end_at=_date(schedule.get("end_at")))
        if kind == "interval":
            seconds = int(schedule.get("seconds") or 0)
            if seconds <= 0:
                return None
            if seconds == 86400 and schedule.get("at_time"):
                hour, minute = map(int, schedule["at_time"].split(":"))
                return CronTrigger(hour=hour, minute=minute, timezone=timezone.utc)
            return IntervalTrigger(
                seconds=seconds,
                start_date=_interval_start_date(automation),
                timezone=timezone.utc,
            )
        if kind in ("relative", "iso"):
            run_at = one_shot_run_at(automation)
            if run_at is None or run_at <= datetime.now(timezone.utc):
                return None
            return DateTrigger(run_date=run_at, timezone=timezone.utc)
        return None


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _interval_start_date(automation: dict[str, Any]) -> datetime:
    schedule = automation["schedule"]
    anchor = _date(schedule.get("anchor_at") or automation.get("created_at")) or datetime.now(timezone.utc)
    at_time = schedule.get("at_time")
    if not at_time:
        return anchor + timedelta(seconds=schedule["seconds"])
    hour, minute = (int(part) for part in str(at_time).split(":"))
    candidate = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= anchor:
        candidate += timedelta(days=1)
    return candidate


def one_shot_run_at(automation: dict[str, Any]) -> datetime | None:
    schedule = automation.get("schedule") or {}
    kind = schedule.get("kind")
    if kind == "relative":
        seconds = int(schedule.get("seconds") or 0)
        anchor = _date(schedule.get("anchor_at") or automation.get("created_at"))
        return anchor + timedelta(seconds=seconds) if anchor and seconds > 0 else None
    if kind == "iso":
        return _date(schedule.get("run_at"))
    return None


def install_automation_jobs(
    scheduler: Any,
    store: AutomationStore | None = None,
    *,
    builtins_enabled: dict[str, bool] | None = None,
) -> AutomationScheduler:
    """Seed built-in jobs, register every active automation, hook mutations."""
    from agent.automations.api import get_store, set_mutation_hook
    from agent.automations.builtins import seed_builtins

    store = store if store is not None else get_store()
    seed_builtins(store, enabled=builtins_enabled)
    _startup_curator_tick()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)
    automation_scheduler.install_all()
    set_mutation_hook(automation_scheduler.sync_one, next_run_lookup=automation_scheduler.next_run_at)
    return automation_scheduler


def _startup_curator_tick() -> None:
    """Preserve the legacy behavior of running one curator tick at startup."""
    try:
        from agent.skills.curator_runtime import get_curator_runtime

        get_curator_runtime().tick()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUTOMATIONS] startup curator tick failed: %s", exc)
