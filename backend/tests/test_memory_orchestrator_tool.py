import json

from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools import memory_orchestrator as memory_tool


def test_memory_orchestrator_tool_reports_status_and_runs_dreaming(monkeypatch, tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
    )
    store.add_pending(
        kind="preference",
        text="User prefers direct memory answers.",
        source_thread_id="t1",
        confidence=0.9,
        scope="global",
    )
    monkeypatch.setattr(memory_tool, "_default_orchestrator", lambda: orchestrator)

    status = json.loads(memory_tool.memory_orchestrator.func(action="status"))
    dream = json.loads(memory_tool.memory_orchestrator.func(action="run_dreaming"))

    assert status["settings"]["memory_enabled"] is True
    assert status["pending_count"] == 1
    assert dream["new_memories"][0]["text"] == "User prefers direct memory answers."
    assert store.list_pending() == []


def test_memory_orchestrator_tool_updates_settings(monkeypatch, tmp_path):
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
    )
    monkeypatch.setattr(memory_tool, "_default_orchestrator", lambda: orchestrator)

    updated = json.loads(memory_tool.memory_orchestrator.func(action="update_settings", dreaming_enabled=False))

    assert updated["settings"]["dreaming_enabled"] is False
