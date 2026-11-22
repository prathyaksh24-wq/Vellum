from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.provider_extensions import (
    HindsightProviderExtension,
    HolographicProviderExtension,
    MemoryProviderExtensionManager,
    SupermemoryProviderExtension,
    build_default_memory_provider_extensions,
)
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
        memory_service=MemoryCapabilityService(sessions_db=tmp_path / "sessions.db"),
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
        memory_service=MemoryCapabilityService(sessions_db=tmp_path / "sessions.db"),
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


def test_hindsight_provider_prefetch_and_sync_with_client(monkeypatch):
    calls = []

    class FakeClient:
        def recall(self, bank_id, query, *, budget):
            return {"memories": [{"content": f"remembered {query}", "score": 0.9}]}

        def retain(self, bank_id, content, *, metadata, **kwargs):
            calls.append((content, bank_id, metadata, kwargs))

    monkeypatch.setenv("MEMORY_EXTENSION_PROVIDERS", "hindsight")
    monkeypatch.setenv("HINDSIGHT_API_KEY", "test-key")
    provider = HindsightProviderExtension(client=FakeClient())

    assert "remembered Giannis" in provider.prefetch("Giannis", session_id="t1")
    doc_id = provider.sync_turn("user", "assistant", session_id="t1", metadata={"agent_name": "SportsAgent"})

    assert calls
    assert calls[0][1] == "vellum"
    assert calls[0][2]["session_id"] == "t1"
    assert calls[0][3]["document_id"] == doc_id and doc_id.startswith("vellum-turn-")
    assert calls[0][3]["retain_async"] is True


def test_local_hindsight_needs_no_key_but_must_answer_health(monkeypatch):
    for key in ("HINDSIGHT_API_KEY",):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MEMORY_EXTENSION_PROVIDERS", "hindsight")
    monkeypatch.setenv("HINDSIGHT_API_URL", "http://127.0.0.1:1")  # nothing listens here
    provider = HindsightProviderExtension()
    assert provider.is_configured()
    status = build_default_memory_provider_extensions().statuses()[0]
    assert status["status"] == "unreachable"
    assert "docker compose up -d hindsight" in status["notes"]
    assert provider.recall_items("anything") == []


def test_hindsight_uses_workspace_settings_without_process_environment(tmp_path, monkeypatch):
    from agent.config import Settings

    for key in ("MEMORY_EXTENSION_PROVIDERS", "HINDSIGHT_API_KEY", "HINDSIGHT_MEMORY_ENABLED", "HINDSIGHT_BANK_ID"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MEMORY_EXTENSION_PROVIDERS=hindsight\nHINDSIGHT_API_KEY=fixture-only\nHINDSIGHT_BANK_ID=fixture-bank\n", encoding="utf-8")
    settings = Settings(_env_file=env_file)
    manager = build_default_memory_provider_extensions(settings=settings)
    assert manager.active_provider_ids() == ["hindsight"]
    assert next(p for p in manager.providers if p.id == "hindsight").bank_id == "fixture-bank"
    assert "fixture-only" not in str(manager.statuses())


def test_supermemory_provider_prefetch_and_sync_with_client(monkeypatch):
    calls = []

    class FakeClient:
        def profile(self, query):
            return {"static": ["User builds Vellum."], "dynamic": [], "search_results": [{"memory": f"related {query}"}]}

        def ingest_turn(self, session_id, user_content, assistant_content, metadata):
            calls.append((session_id, user_content, assistant_content, metadata))

    monkeypatch.setenv("MEMORY_EXTENSION_PROVIDERS", "supermemory")
    monkeypatch.setenv("SUPERMEMORY_API_KEY", "test-key")
    provider = SupermemoryProviderExtension(client=FakeClient())

    assert "User builds Vellum" in provider.prefetch("memory", session_id="t1")
    provider.sync_turn("user", "assistant", session_id="t1", metadata={"agent_name": "VellumAgent"})

    assert calls[0][0] == "t1"


def test_holographic_provider_stores_and_prefetches_local_facts(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_EXTENSION_PROVIDERS", "holographic")
    monkeypatch.setenv("HOLOGRAPHIC_MEMORY_ENABLED", "true")
    provider = HolographicProviderExtension(db_path=tmp_path / "holographic.db")

    provider.sync_turn(
        "Remember that Vellum uses Hindsight for graph memory.",
        "Stored.",
        session_id="t1",
        metadata={"agent_name": "MemoryAgent"},
    )

    context = provider.prefetch("What graph memory does Vellum use?", session_id="t2")

    assert "Hindsight" in context


def test_forget_document_uses_the_clients_own_loop_runner(monkeypatch):
    """hindsight-client keeps _run_async in hindsight_client.hindsight_client, not the package root."""
    import hindsight_client.hindsight_client as client_module

    from agent.memory import provider_extensions as module

    calls = []

    class Documents:
        def delete_document(self, *, bank_id, document_id):
            calls.append((bank_id, document_id))
            return "coroutine"

    monkeypatch.setattr(client_module, "_run_async", lambda coro: calls.append(("ran", coro)))
    module._delete_hindsight_document(type("Client", (), {"documents": Documents()})(), "vellum", "vellum-memory-7")
    assert calls == [("vellum", "vellum-memory-7"), ("ran", "coroutine")]


def test_hindsight_uses_one_client_per_thread(monkeypatch):
    """A client's HTTP session belongs to one thread's event loop; sharing it broke memory sync."""
    import sys
    import threading
    import types

    made = []

    class FakeHindsight:
        def __init__(self, **kwargs):
            made.append(threading.get_ident())

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "hindsight_client", types.SimpleNamespace(Hindsight=FakeHindsight))
    monkeypatch.setenv("HINDSIGHT_API_URL", "http://127.0.0.1:8888")
    provider = HindsightProviderExtension()
    first = provider._client()
    assert provider._client() is first  # reused within a thread

    seen = []
    worker = threading.Thread(target=lambda: seen.append(provider._client()))
    worker.start()
    worker.join()
    assert seen[0] is not first and len(made) == 2
    provider.shutdown()
