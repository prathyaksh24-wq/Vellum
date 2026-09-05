"""Tests for built-in automation migration (ticket 06)."""

import asyncio

from agent.automations import api as automations_api
from agent.automations import builtins
from agent.automations.scheduler import AutomationScheduler
from agent.automations.store import AutomationStore


def _store(tmp_path) -> AutomationStore:
    store = AutomationStore(tmp_path / "automations")
    automations_api.set_store(store)
    return store


def test_seed_builtins_creates_records(tmp_path):
    store = _store(tmp_path)

    seeded = builtins.seed_builtins(store)

    assert len(seeded) == 5
    records = {r["builtin_key"]: r for r in store.list()}
    assert set(records) == {
        "memory_dreaming",
        "nightly_digest",
        "vault_retention",
        "youtube_intelligence_projection",
        "discord_intelligence_sync",
        "skill_curator_tick",
    }
    for record in records.values():
        assert record["builtin"] is True
        assert record["state"] == "active"
        assert record["permission"]["full_access"] is True
        assert record["destination"]["kind"] == "new_chat"
    assert records["nightly_digest"]["schedule"]["expression"] == "15 2 * * *"
    assert records["skill_curator_tick"]["schedule"]["seconds"] == 3600
    assert records["discord_intelligence_sync"]["schedule"]["seconds"] == 60


def test_seed_builtins_is_idempotent_and_preserves_user_edits(tmp_path):
    store = _store(tmp_path)
    builtins.seed_builtins(store)
    first = {r["builtin_key"]: r["id"] for r in store.list()}

    seeded_again = builtins.seed_builtins(store)

    assert seeded_again == []
    assert {r["builtin_key"]: r["id"] for r in store.list()} == first
    digest_id = first["nightly_digest"]
    store.update(digest_id, name="Renamed digest", schedule=builtins.parse_schedule("0 1 * * *").to_dict())
    builtins.seed_builtins(store)
    record = store.get(digest_id)
    assert record["name"] == "Renamed digest"
    assert record["schedule"]["expression"] == "0 1 * * *"


def test_seed_builtins_marks_disabled_builtins_paused(tmp_path):
    store = _store(tmp_path)

    builtins.seed_builtins(store, enabled={"nightly_digest": False})

    records = {r["builtin_key"]: r for r in store.list()}
    assert records["nightly_digest"]["state"] == "paused"
    assert records["vault_retention"]["state"] == "active"


def test_reset_builtin_restores_defaults(tmp_path):
    store = _store(tmp_path)
    builtins.seed_builtins(store)
    automation_id = next(r["id"] for r in store.list() if r["builtin_key"] == "skill_curator_tick")
    store.update(
        automation_id,
        name="Scratched",
        schedule=builtins.parse_schedule("0 9 * * *").to_dict(),
        destination={"kind": "existing_chat", "thread_id": "t1"},
        permission={"full_access": False},
        state="paused",
    )

    restored = builtins.reset_builtin(store, store.get(automation_id))

    assert restored["name"] == "Skill curator tick"
    assert restored["schedule"]["expression"] == "every 1h"
    assert restored["destination"]["kind"] == "new_chat"
    assert restored["permission"]["full_access"] is True
    assert restored["state"] == "active"
    assert restored["builtin"] is True


def test_reset_builtin_unknown_key_raises(tmp_path):
    store = _store(tmp_path)

    try:
        builtins.reset_builtin(store, {"id": "x", "builtin_key": "no_such_builtin"})
    except ValueError as exc:
        assert "no_such_builtin" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_delete_builtin_via_api_restores_instead_of_removing(tmp_path):
    from fastapi.testclient import TestClient

    from agent import api

    store = _store(tmp_path)
    builtins.seed_builtins(store)
    digest_id = next(r["id"] for r in store.list() if r["builtin_key"] == "nightly_digest")
    store.update(digest_id, state="paused")

    with TestClient(api.app) as client:
        response = client.delete(f"/api/automations/{digest_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["restored"] is True
    record = store.get(digest_id)
    assert record is not None
    assert record["schedule"]["expression"] == "15 2 * * *"
    assert record["state"] == "active"


def test_run_builtin_dispatches_to_handler(monkeypatch):
    calls = []

    async def fake_handler():
        calls.append("ticked")

    monkeypatch.setitem(builtins._HANDLERS, "skill_curator_tick", fake_handler)

    asyncio.run(builtins.run_builtin({"builtin_key": "skill_curator_tick"}))

    assert calls == ["ticked"]


def test_run_builtin_unknown_key_is_noop(monkeypatch):
    original = dict(builtins._HANDLERS)
    monkeypatch.setattr(builtins, "_HANDLERS", original)

    asyncio.run(builtins.run_builtin({"builtin_key": "not_real"}))


def test_fire_routes_builtin_to_run_builtin_not_reasoning(monkeypatch, tmp_path):
    store = _store(tmp_path)
    builtins.seed_builtins(store)
    automation_id = next(r["id"] for r in store.list() if r["builtin_key"] == "vault_retention")

    class FakeScheduler:
        def __init__(self):
            self.jobs = []
            self.calls = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append(kwargs.get("id"))

        def get_jobs(self):
            return []

    scheduler = AutomationScheduler(store, scheduler=FakeScheduler())
    executor_calls = []
    builtin_calls = []

    async def fake_executor(automation, store_):
        executor_calls.append(automation["id"])

    async def fake_run_builtin(record):
        builtin_calls.append(record["id"])

    scheduler.executor = fake_executor
    monkeypatch.setattr(builtins, "run_builtin", fake_run_builtin)

    asyncio.run(scheduler._fire(automation_id))

    assert executor_calls == []
    assert builtin_calls == [automation_id]


def test_builtin_runs_do_not_create_run_history(tmp_path, monkeypatch):
    store = _store(tmp_path)
    builtins.seed_builtins(store)
    automation_id = next(r["id"] for r in store.list() if r["builtin_key"] == "memory_dreaming")

    async def noop_handler():
        return None

    monkeypatch.setitem(builtins._HANDLERS, "memory_dreaming", noop_handler)

    scheduler = AutomationScheduler(store, scheduler=type("S", (), {"get_jobs": lambda self: [], "add_job": lambda *a, **k: None})())
    asyncio.run(scheduler._fire(automation_id))

    assert store.get(automation_id)["run_history"] == []


def test_sync_one_handles_builtin_schedule_edits(tmp_path):
    store = _store(tmp_path)
    builtins.seed_builtins(store)
    automation_id = next(r["id"] for r in store.list() if r["builtin_key"] == "skill_curator_tick")

    class FakeScheduler:
        def __init__(self):
            self.jobs = {}
            self.removed = []

        def add_job(self, func, trigger, **kwargs):
            self.jobs[kwargs["id"]] = trigger

        def remove_job(self, job_id):
            self.removed.append(job_id)
            self.jobs.pop(job_id, None)

        def get_jobs(self):
            return [type("J", (), {"id": job_id})() for job_id in self.jobs]

    scheduler = AutomationScheduler(store, scheduler=FakeScheduler())
    scheduler.install_all()

    store.update(automation_id, state="paused")
    scheduler.sync_one(automation_id)
    assert f"automation-{automation_id}" in scheduler.scheduler.removed

    store.update(automation_id, state="active")
    scheduler.sync_one(automation_id)
    assert f"automation-{automation_id}" in scheduler.scheduler.jobs
