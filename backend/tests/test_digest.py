from datetime import datetime
import asyncio
from types import SimpleNamespace

from agent.memory.fts5 import FTS5Memory
from agent.obsidian.vault import ObsidianVault
from agent.scheduler import digest


def test_build_digest_prompt_lists_facts():
    prompt = digest.build_digest_prompt(["Q: NBA\nA: User likes NBA", "Q: Books\nA: User reads books"])

    assert "A: User likes NBA" in prompt
    assert "A: User reads books" in prompt
    assert "Summary:" in prompt


def test_run_digest_returns_none_without_facts(tmp_path):
    memory = FTS5Memory(tmp_path / "fts5.db")
    vault = ObsidianVault(tmp_path / "Vault")

    result = asyncio.run(digest.run_digest(memory=memory, vault=vault, now=datetime(2026, 5, 5)))

    assert result is None
    assert not (tmp_path / "Vault" / "Agent").exists()


def test_run_digest_writes_summary_note(monkeypatch, tmp_path):
    memory = FTS5Memory(tmp_path / "fts5.db")
    memory.add_qa_pair(
        query="What about F1 standings?",
        answer="User is interested in F1 standings.",
        thread_id="sports",
        source_paths=[],
    )
    vault = ObsidianVault(tmp_path / "Vault")
    captured = {}

    async def fake_openrouter_chat(**kwargs):
        captured.update(kwargs)
        return "## Insights\n- F1 interest"

    monkeypatch.setattr(digest, "openrouter_chat", fake_openrouter_chat)

    note_path = asyncio.run(digest.run_digest(memory=memory, vault=vault, now=datetime(2026, 5, 5)))

    assert note_path is not None
    note = (tmp_path / "Vault" / "Agent" / "Digests" / "Digest 2026-05-05.md")
    assert note.exists()
    assert "F1 interest" in note.read_text(encoding="utf-8")
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
        lambda: SimpleNamespace(enable_nightly_digest=True, enable_vault_retention=True),
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
        "memory_dreaming",
        "nightly_digest",
        "vault_retention",
        "youtube_intelligence_projection",
        "skill_curator_tick",
    }
    assert all(r["builtin"] for r in records.values())
    assert all(r["state"] == "active" for r in records.values())
    assert records["nightly_digest"]["schedule"]["expression"] == "15 2 * * *"
    assert records["youtube_intelligence_projection"]["schedule"]["expression"] == "30 2 * * *"
    assert records["vault_retention"]["schedule"]["expression"] == "0 3 * * *"
    assert records["memory_dreaming"]["schedule"]["expression"] == "0 2 * * *"
    assert records["skill_curator_tick"]["schedule"]["seconds"] == 3600
    for record in records.values():
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
        lambda: SimpleNamespace(enable_nightly_digest=False, enable_vault_retention=True),
    )

    digest.start_scheduler(scheduler=scheduler)

    records = {r["builtin_key"]: r for r in store.list()}
    assert records["nightly_digest"]["state"] == "paused"
    assert records["vault_retention"]["state"] == "active"
    job_ids = {job[2]["id"] for job in scheduler.jobs}
    assert f"automation-{records['vault_retention']['id']}" in job_ids
    assert f"automation-{records['nightly_digest']['id']}" not in job_ids
