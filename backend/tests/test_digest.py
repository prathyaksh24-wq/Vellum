from datetime import datetime
import asyncio

from agent.memory.long_term import LongTermMemory
from agent.obsidian.vault import ObsidianVault
from agent.scheduler import digest


def test_build_digest_prompt_lists_facts():
    prompt = digest.build_digest_prompt(["User likes NBA", "User reads books"])

    assert "- User likes NBA" in prompt
    assert "- User reads books" in prompt
    assert "Summary:" in prompt


def test_run_digest_returns_none_without_facts(tmp_path):
    memory = LongTermMemory(tmp_path / "memory.db")
    vault = ObsidianVault(tmp_path / "Vault")

    result = asyncio.run(digest.run_digest(memory=memory, vault=vault, now=datetime(2026, 5, 5)))

    assert result is None
    assert not (tmp_path / "Vault" / "Agent").exists()


def test_run_digest_writes_summary_note(monkeypatch, tmp_path):
    memory = LongTermMemory(tmp_path / "memory.db")
    memory.store_fact("User is interested in F1 standings", category="sports")
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


def test_start_scheduler_registers_nightly_job(monkeypatch):
    class FakeScheduler:
        def __init__(self):
            self.jobs = []
            self.started = False

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((func, trigger, kwargs))

        def start(self):
            self.started = True

    scheduler = FakeScheduler()

    result = digest.start_scheduler(scheduler=scheduler)

    assert result is scheduler
    assert scheduler.started is True
    assert scheduler.jobs[0][1] == "cron"
    assert scheduler.jobs[0][2]["hour"] == 2
    assert scheduler.jobs[0][2]["minute"] == 0
