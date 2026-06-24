from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.provider_extensions import MemoryProviderExtensionManager, build_default_memory_provider_extensions
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def test_default_memory_provider_extensions_are_optional_until_configured(monkeypatch):
    monkeypatch.delenv("MEMORY_EXTENSION_PROVIDERS", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_KEY", raising=False)
    monkeypatch.delenv("SUPERMEMORY_API_KEY", raising=False)
    monkeypatch.delenv("HOLOGRAPHIC_MEMORY_ENABLED", raising=False)

    manager = build_default_memory_provider_extensions()

    statuses = {item["id"]: item for item in manager.statuses()}
    assert {"hindsight", "supermemory", "holographic"} <= set(statuses)
    assert statuses["hindsight"]["status"] == "disabled"
    assert statuses["supermemory"]["status"] == "disabled"
    assert statuses["holographic"]["status"] == "disabled"
    assert statuses["hindsight"]["optional"] is True


def test_memory_provider_extension_manager_reports_active_extensions():
    class FakeProvider:
        id = "fake"
        name = "Fake Provider"
        provider_type = "test"
        optional = True
        capabilities = ["memory.prefetch"]

        def is_enabled(self):
            return True

        def is_configured(self):
            return True

        def setup_notes(self):
            return ""

    manager = MemoryProviderExtensionManager([FakeProvider()])

    assert manager.active_provider_ids() == ["fake"]
    assert manager.statuses()[0]["status"] == "ready"


def test_memory_packet_includes_external_provider_prefetch_context(tmp_path):
    class FakeProvider:
        id = "fake"
        name = "Fake Provider"
        provider_type = "test"
        optional = True
        capabilities = ["memory.prefetch"]

        def is_enabled(self):
            return True

        def is_configured(self):
            return True

        def setup_notes(self):
            return ""

        def prefetch(self, query, *, session_id=""):
            assert query == "What did I say about Giannis?"
            assert session_id == "new-chat"
            return "External memory says Giannis trade details were discussed."

    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
        provider_extensions=MemoryProviderExtensionManager([FakeProvider()]),
    )

    packet = orchestrator.build_memory_packet(thread_id="new-chat", query="What did I say about Giannis?")

    assert "External memory says Giannis" in packet["external_context"]


def test_record_turn_syncs_to_active_external_provider(tmp_path):
    calls = []

    class FakeProvider:
        id = "fake"
        name = "Fake Provider"
        provider_type = "test"
        optional = True
        capabilities = ["memory.sync_turn"]

        def is_enabled(self):
            return True

        def is_configured(self):
            return True

        def setup_notes(self):
            return ""

        def sync_turn(self, user_content, assistant_content, *, session_id="", metadata=None):
            calls.append((user_content, assistant_content, session_id, metadata))

    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=SQLiteMemoryStore(tmp_path / "memory.db"),
        memory_dir=tmp_path / "memory-files",
        provider_extensions=MemoryProviderExtensionManager([FakeProvider()]),
    )

    orchestrator.record_turn(thread_id="t1", query="hello", answer="hi", agent_name="VellumAgent")

    assert calls
    assert calls[0][0] == "hello"
    assert calls[0][1] == "hi"
    assert calls[0][2] == "t1"
    assert calls[0][3]["agent_name"] == "VellumAgent"
