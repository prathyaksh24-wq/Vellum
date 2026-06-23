from pathlib import Path

from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService


class FakeHoncho:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.refreshed: list[str] = []

    def get_or_create_session(self, session_id: str) -> str:
        return session_id

    def add_message(self, session_id: str, *, content: str, role: str) -> None:
        self.messages.append((session_id, role, content))

    def chat(self, *, session_id: str, query: str) -> str:
        self.refreshed.append(session_id)
        return "- User follows Vellum memory architecture closely."


def test_memory_packet_uses_saved_honcho_project_and_recent_context(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    fts = FTS5Memory(tmp_path / "fts5.db")
    resolved = ResolvedQuestionsCache(tmp_path / "resolved.db")
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")
    honcho = FakeHoncho()
    orchestrator = MemoryOrchestrator(
        fts5=fts,
        resolved_cache=resolved,
        memory_service=service,
        store=store,
        honcho=honcho,
    )
    store.update_global_summary("User is building Vellum and prefers direct engineering answers.")
    store.update_project_summary("Vellum", "Vellum is moving toward a ChatGPT-style memory and dreaming system.")
    store.save_memory(
        kind="preference",
        text="User prefers concise answers without evidence sections when sources are visible in UI.",
        source_thread_id="t1",
        confidence=0.9,
    )

    orchestrator.record_turn(
        thread_id="t1",
        query="Did Messi score a hat-trick against Algeria in the World Cup?",
        answer="Yes. Messi scored a hat-trick for Argentina in a 3-0 win over Algeria.",
        tools=[
            {
                "name": "serpapi.google_ai_mode",
                "output": {
                    "reconstructed_markdown": "Argentina 3-0 Algeria. Lionel Messi scored a hat-trick.",
                    "references": [{"title": "Guardian", "link": "https://www.theguardian.com/football"}],
                },
            }
        ],
        sources=["https://www.theguardian.com/football"],
        confidence=0.94,
        agent_name="SportsAgent",
    )

    packet = orchestrator.build_memory_packet(
        thread_id="t2",
        query="For Vellum memory, should I include evidence sections?",
        agent_name="VellumAgent",
        active_project="Vellum",
    )

    assert packet["global_summary"].startswith("User is building Vellum")
    assert "concise answers" in packet["saved_memories"][0]["text"]
    assert "Honcho" not in packet["honcho_context"]
    assert "Vellum is moving" in packet["project_context"]
    assert "Messi scored a hat-trick" in packet["recent_context"]


def test_memory_packet_respects_global_and_agent_scopes(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        honcho=FakeHoncho(),
    )
    store.save_memory(
        kind="preference",
        text="User prefers source details in the UI drawer instead of Evidence sections.",
        source_thread_id="t-global",
        confidence=0.9,
        scope="global",
    )
    store.save_memory(
        kind="profile",
        text="User is building Vellum for an enterprise demo.",
        source_thread_id="t-profile",
        confidence=0.9,
        scope="user_profile",
    )
    store.save_memory(
        kind="preference",
        text="For YouTube answers, include channel name and video link when available.",
        source_thread_id="t-youtube",
        confidence=0.86,
        scope="agent:YoutubeAgent",
    )
    store.save_memory(
        kind="preference",
        text="For sports answers, include standings when relevant.",
        source_thread_id="t-sports",
        confidence=0.86,
        scope="agent:SportsAgent",
    )

    packet = orchestrator.build_memory_packet(
        thread_id="t-new",
        query="How should I answer a YouTube upload question?",
        agent_name="YoutubeAgent",
    )
    texts = "\n".join(item["text"] for item in packet["saved_memories"])

    assert "source details in the UI drawer" in texts
    assert "enterprise demo" in texts
    assert "channel name and video link" in texts
    assert "standings" not in texts
    assert packet["scopes"] == ["global", "user_profile", "agent:YoutubeAgent"]


def test_memory_settings_can_disable_recent_context_without_disabling_saved_memory(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        honcho=FakeHoncho(),
    )
    store.save_memory(
        kind="preference",
        text="User prefers concise answers.",
        source_thread_id="t1",
        confidence=0.9,
        scope="global",
    )
    orchestrator.record_turn(
        thread_id="t1",
        query="What did Neymar do at PSG?",
        answer="Neymar played for PSG and won domestic titles.",
        confidence=0.4,
    )
    store.update_settings({"reference_history_enabled": False})

    packet = orchestrator.build_memory_packet(thread_id="t2", query="What do you remember?", agent_name="VellumAgent")

    assert packet["saved_memories"][0]["text"] == "User prefers concise answers."
    assert packet["recent_context"] == ""


def test_extractor_stores_pending_memories_before_dreaming_promotes(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        honcho=FakeHoncho(),
    )

    candidates = orchestrator.extract_memory_candidates(
        thread_id="t1",
        user_message="Remember that I do not want YouTube answers to include Evidence sections.",
        assistant_message="Got it. I will rely on the sources UI instead.",
        agent_name="VellumAgent",
    )

    assert len(candidates) == 1
    assert candidates[0]["status"] == "pending"
    assert store.list_saved() == []

    dream = orchestrator.run_dreaming()

    assert "Evidence sections" in dream["new_memories"][0]["text"]
    assert store.list_pending() == []
    assert store.list_saved()[0]["status"] == "saved"
    assert "Evidence sections" in dream["global_summary"]
    assert dream["audit_log"]


def test_dreaming_archives_stale_unpinned_memories_but_keeps_pinned(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    stale_id = store.save_memory(kind="project", text="Old unpinned memory", source_thread_id="t1", confidence=0.8)
    pinned_id = store.save_memory(kind="preference", text="Pinned memory", source_thread_id="t1", confidence=0.9)
    store.pin(pinned_id, True)
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db"),
        store=store,
        honcho=FakeHoncho(),
    )

    dream = orchestrator.run_dreaming(stale_days=0)

    assert stale_id in [item["id"] for item in dream["archived_memories"]]
    assert pinned_id not in [item["id"] for item in dream["archived_memories"]]
    assert store.get_memory(pinned_id)["status"] == "saved"
    assert store.get_memory(stale_id)["status"] == "archived"
