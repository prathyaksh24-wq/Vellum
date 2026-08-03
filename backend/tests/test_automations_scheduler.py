"""Scheduler wiring tests: registration, triggers, gates, and run recording.

No network, no LLM, no real scheduler — a FakeScheduler captures add_job /
remove_job calls and the store lives in a tmp dir (pattern of test_digest.py).
"""

import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.automations.scheduler import (
    JOB_PREFIX,
    MISFIRE_GRACE_SECONDS,
    AutomationScheduler,
    install_automation_jobs,
)
from agent.automations.store import AutomationStore


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.removed: list[str] = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def remove_job(self, job_id: str) -> None:
        self.removed.append(job_id)
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]

    def get_jobs(self):
        return list(self.jobs)


def _create(store: AutomationStore, **overrides) -> dict:
    schedule = overrides.pop(
        "schedule",
        {"kind": "interval", "expression": "every 2h", "value": 2, "unit": "hours", "seconds": 7200},
    )
    state = overrides.pop("state", "active")
    record = store.create(
        name=overrides.pop("name", "Brief"),
        instructions="Summarize what changed.",
        schedule=schedule,
        destination={"kind": "new_chat"},
        permission=overrides.pop("permission", {"full_access": True}),
        **overrides,
    )
    if state != "active":
        store.update(record["id"], state=state)
        record = store.get(record["id"])
    return record


def test_install_all_registers_only_active_automations(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _create(store, name="cron-one", schedule={"kind": "cron", "expression": "0 9 * * *"})
    _create(store, name="interval-one")
    _create(store, name="paused-one", state="paused")

    scheduler = FakeScheduler()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)
    registered = automation_scheduler.install_all()

    assert len(registered) == 2
    assert len(scheduler.jobs) == 2
    job = scheduler.jobs[0]
    assert job["id"].startswith(JOB_PREFIX)
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    assert job["misfire_grace_time"] == MISFIRE_GRACE_SECONDS


def test_triggers_match_schedule_kinds(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    cron = _create(store, name="cron", schedule={"kind": "cron", "expression": "0 9 * * *"})
    interval = _create(store, name="interval")
    iso_future = _create(
        store,
        name="iso",
        schedule={
            "kind": "iso",
            "expression": "2026-08-03T09:00:00Z",
            "run_at": (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(),
        },
    )

    scheduler = FakeScheduler()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)
    automation_scheduler.install_all()

    by_id = {job["id"]: job for job in scheduler.jobs}
    assert isinstance(by_id[f"{JOB_PREFIX}{cron['id']}"]["trigger"], CronTrigger)
    interval_trigger = by_id[f"{JOB_PREFIX}{interval['id']}"]["trigger"]
    assert isinstance(interval_trigger, IntervalTrigger)
    assert interval_trigger.interval.total_seconds() == 7200
    assert isinstance(by_id[f"{JOB_PREFIX}{iso_future['id']}"]["trigger"], DateTrigger)


def test_expired_one_shot_is_not_registered(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    _create(
        store,
        name="expired",
        schedule={
            "kind": "iso",
            "expression": "2020-01-01T09:00:00Z",
            "run_at": "2020-01-01T09:00:00+00:00",
        },
    )

    scheduler = FakeScheduler()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)
    registered = automation_scheduler.install_all()

    assert registered == []
    assert scheduler.jobs == []


def test_relative_one_shot_gets_future_date_trigger(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    relative = _create(
        store,
        name="relative",
        schedule={"kind": "relative", "expression": "30m", "value": 30, "unit": "minutes", "seconds": 1800},
    )

    scheduler = FakeScheduler()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)
    automation_scheduler.install_all()

    trigger = scheduler.jobs[0]["trigger"]
    assert isinstance(trigger, DateTrigger)
    assert trigger.run_date > datetime.now(timezone.utc)
    assert scheduler.jobs[0]["id"] == f"{JOB_PREFIX}{relative['id']}"


def test_uninstall_and_sync_remove_stale_jobs(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    first = _create(store, name="first")
    second = _create(store, name="second")

    scheduler = FakeScheduler()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)
    automation_scheduler.install_all()
    assert len(scheduler.jobs) == 2

    automation_scheduler.uninstall(first["id"])
    assert scheduler.removed == [f"{JOB_PREFIX}{first['id']}"]
    assert len(scheduler.jobs) == 1

    automation_scheduler.sync([second["id"]])
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0]["id"] == f"{JOB_PREFIX}{second['id']}"


def test_sync_one_handles_create_pause_and_delete(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation = _create(store, name="sync-me")
    scheduler = FakeScheduler()
    automation_scheduler = AutomationScheduler(store, scheduler=scheduler)

    automation_scheduler.sync_one(automation["id"])
    assert len(scheduler.jobs) == 1

    store.update(automation["id"], state="paused")
    automation_scheduler.sync_one(automation["id"])
    assert scheduler.jobs == []
    assert scheduler.removed == [f"{JOB_PREFIX}{automation['id']}"]

    automation_scheduler.sync_one("automation-ghost")
    assert scheduler.removed == [
        f"{JOB_PREFIX}{automation['id']}",
        f"{JOB_PREFIX}automation-ghost",
    ]


def test_fire_skips_paused_automation(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation = _create(store, name="paused", state="paused")
    calls = []

    async def fake_executor(record, _store):
        calls.append(record["id"])

    automation_scheduler = AutomationScheduler(store, scheduler=FakeScheduler(), executor=fake_executor)

    asyncio.run(automation_scheduler._fire(automation["id"]))

    assert calls == []
    assert store.runs(automation["id"]) == []


def test_fire_requires_full_access_opt_in(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation = _create(store, name="no-access", permission={"full_access": False})
    calls = []

    async def fake_executor(record, _store):
        calls.append(record["id"])

    automation_scheduler = AutomationScheduler(store, scheduler=FakeScheduler(), executor=fake_executor)

    asyncio.run(automation_scheduler._fire(automation["id"]))

    assert calls == []
    runs = store.runs(automation["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "full-access" in runs[0]["error"]


def test_fire_executes_full_access_automation(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation = _create(store, name="allowed")
    calls = []

    async def fake_executor(record, _store):
        calls.append(record["id"])
        return {"status": "complete"}

    automation_scheduler = AutomationScheduler(store, scheduler=FakeScheduler(), executor=fake_executor)

    asyncio.run(automation_scheduler._fire(automation["id"]))

    assert calls == [automation["id"]]


def test_fire_skips_when_run_already_in_flight(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation = _create(store, name="busy")
    store.record_run(automation["id"], "run-in-flight")
    calls = []

    async def fake_executor(record, _store):
        calls.append(record["id"])
        return {"status": "complete"}

    automation_scheduler = AutomationScheduler(store, scheduler=FakeScheduler(), executor=fake_executor)

    asyncio.run(automation_scheduler._fire(automation["id"]))

    assert calls == []
    runs = store.runs(automation["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "running"


def test_fire_records_executor_crash(tmp_path) -> None:
    store = AutomationStore(tmp_path)
    automation = _create(store, name="crashy")

    async def failing_executor(record, _store):
        raise RuntimeError("provider timeout")

    automation_scheduler = AutomationScheduler(store, scheduler=FakeScheduler(), executor=failing_executor)

    asyncio.run(automation_scheduler._fire(automation["id"]))

    runs = store.runs(automation["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "provider timeout" in runs[0]["error"]


def test_install_automation_jobs_wires_mutation_hook(tmp_path) -> None:
    from agent.automations import api as automations_api

    store = AutomationStore(tmp_path)
    _create(store, name="hooked")
    scheduler = FakeScheduler()

    automations_api.set_store(store)
    try:
        automation_scheduler = install_automation_jobs(scheduler)
        builtin_ids = {r["id"] for r in store.list() if r.get("builtin")}
        assert len(scheduler.jobs) == 1 + len(builtin_ids)
        assert automations_api._MUTATION_HOOK is not None
        created = _create(store, name="after-hook")
        automations_api._notify_mutation(created["id"])
        assert len(scheduler.jobs) == 2 + len(builtin_ids)
        assert automations_api._MUTATION_HOOK == automation_scheduler.sync_one
        automations_api._notify_mutation("automation-ghost")
    finally:
        automations_api.set_store(None)
