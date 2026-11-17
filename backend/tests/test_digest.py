from datetime import datetime
import asyncio
from types import SimpleNamespace

from agent.memory.fts5 import FTS5Memory
from agent.scheduler import digest


def test_build_digest_prompt_lists_facts():
    prompt = digest.build_digest_prompt(["Q: NBA\nA: User likes NBA", "Q: Books\nA: User reads books"])

    assert "A: User likes NBA" in prompt
    assert "A: User reads books" in prompt
    assert "Summary:" in prompt


def test_run_digest_returns_none_without_facts(tmp_path):
    memory = FTS5Memory(tmp_path / "fts5.db")

    result = asyncio.run(digest.run_digest(memory=memory, now=datetime(2026, 5, 5)))

    assert result is None


def test_run_digest_returns_summary_without_writing_notes(monkeypatch, tmp_path):
    memory = FTS5Memory(tmp_path / "fts5.db")
    memory.add_qa_pair(
        query="What about F1 standings?",
        answer="User is interested in F1 standings.",
        thread_id="sports",
        source_paths=[],
    )
    captured = {}

    async def fake_openrouter_chat(**kwargs):
        captured.update(kwargs)
        return "## Insights\n- F1 interest"

    monkeypatch.setattr(digest, "openrouter_chat", fake_openrouter_chat)

    monkeypatch.chdir(tmp_path)

    summary = asyncio.run(digest.run_digest(memory=memory, now=datetime(2026, 5, 5)))

    assert summary == "## Insights\n- F1 interest"
    assert not (tmp_path / "Vault").exists()
    assert captured["model_override"]
    assert captured["session_id"] == "digest-2026-05-05"


def test_start_scheduler_seeds_builtins_and_registers_jobs(monkeypatch, tmp_path):
    from agent.automations import api as automations_api
    from agent.automations.store import AutomationStore

    store = AutomationStore(tmp_path / "automations")
    automations_api.set_store(store)

    class FakeScheduler:
        def __init__(self):
            self.jobs = []
            self.started = False

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((func, trigger, kwargs))

        def start(self):
            self.started = True

    scheduler = FakeScheduler()
    monkeypatch.setattr(
        digest,
        "get_settings",
        lambda: SimpleNamespace(enable_nightly_digest=True),
    )

    async def dreaming_job():
        return True

    result = digest.start_scheduler(scheduler=scheduler, dreaming_job=dreaming_job)

    assert result is scheduler
    assert scheduler.started is True
    jobs = {job[2]["id"]: job for job in scheduler.jobs}
    assert "memory_dreaming" in jobs  # legacy dreaming_job param
    assert jobs["memory_dreaming"][2]["hour"] == 2
    records = {r["builtin_key"]: r for r in store.list()}
    assert set(records) == {
        "youtube_browser_history",
        "youtube_creator_tracking",
        "memory_dreaming",
        "memory_provider_sync",
        "memory_retention",
        "nightly_digest",
        "youtube_intelligence_projection",
        "discord_intelligence_sync",
        "skill_curator_tick",
    }
    assert all(r["builtin"] for r in records.values())
    assert records["youtube_browser_history"]["state"] == "paused"
    assert records["youtube_browser_history"]["schedule"]["seconds"] == 900
    assert records["youtube_creator_tracking"]["state"] == "paused"
    assert records["youtube_creator_tracking"]["schedule"]["seconds"] == 900
    assert all(r["state"] == "active" for key, r in records.items()
               if key not in {"youtube_browser_history", "youtube_creator_tracking"})
    assert records["nightly_digest"]["schedule"]["expression"] == "15 2 * * *"
    assert records["youtube_intelligence_projection"]["schedule"]["expression"] == "30 2 * * *"
    assert records["discord_intelligence_sync"]["schedule"]["seconds"] == 60
    assert records["memory_dreaming"]["schedule"]["expression"] == "0 2 * * *"
    assert records["skill_curator_tick"]["schedule"]["seconds"] == 3600
    for record in records.values():
        if record["state"] != "active":
            assert f"automation-{record['id']}" not in jobs
            continue
        assert f"automation-{record['id']}" in jobs
        assert jobs[f"automation-{record['id']}"][2]["max_instances"] == 1


def test_start_scheduler_pauses_disabled_builtins(monkeypatch, tmp_path):
    from agent.automations import api as automations_api
    from agent.automations.store import AutomationStore

    store = AutomationStore(tmp_path / "automations")
    automations_api.set_store(store)

    class FakeScheduler:
        def __init__(self):
            self.jobs = []
            self.started = False

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((func, trigger, kwargs))

        def start(self):
            self.started = True

    scheduler = FakeScheduler()
    monkeypatch.setattr(
        digest,
        "get_settings",
        lambda: SimpleNamespace(enable_nightly_digest=False),
    )

    digest.start_scheduler(scheduler=scheduler)

    records = {r["builtin_key"]: r for r in store.list()}
    assert records["nightly_digest"]["state"] == "paused"
    assert records["memory_dreaming"]["state"] == "active"
    job_ids = {job[2]["id"] for job in scheduler.jobs}
    assert f"automation-{records['memory_dreaming']['id']}" in job_ids
    assert f"automation-{records['nightly_digest']['id']}" not in job_ids


def test_seed_builtins_removes_retired_vault_retention(tmp_path):
    from agent.automations.builtins import seed_builtins
    from agent.automations.schedules import parse_schedule
    from agent.automations.store import AutomationStore

    store = AutomationStore(tmp_path / "automations")
    store.create(
        name="Vault retention",
        instructions="Run vault retention.",
        schedule=parse_schedule("0 3 * * *").to_dict(),
        destination={"kind": "new_chat"},
        permission={"full_access": True},
        builtin=True,
        builtin_key="vault_retention",
    )

    seed_builtins(store)

    assert "vault_retention" not in {record.get("builtin_key") for record in store.list()}
