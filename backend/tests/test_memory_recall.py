from pathlib import Path

from agent.memory import recall
from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def _memories(n: int) -> list[dict]:
    return [
        {"id": i, "title": f"Memory {i}", "description": f"detail {i}", "text": f"detail {i}", "updated_at": "x"}
        for i in range(1, n + 1)
    ]


def setup_function() -> None:
    recall.clear_cache()


def test_small_sets_are_all_used_without_a_model_call() -> None:
    def never(system, query):  # pragma: no cover - must not run
        raise AssertionError("selector called")

    chosen, method = recall.select_relevant_memories("anything", _memories(3), limit=5, selector=never)
    assert method == "all" and [m["id"] for m in chosen] == [1, 2, 3]


def test_model_picks_by_id_and_ignores_unknown_ids() -> None:
    seen = {}

    def selector(system, query):
        seen["system"] = system
        return {"ids": [7, 999, "3", 7]}

    chosen, method = recall.select_relevant_memories("coffee?", _memories(12), limit=5, selector=selector)
    assert method == "model" and [m["id"] for m in chosen] == [7, 3]
    assert "7: Memory 7 - detail 7" in seen["system"]  # manifest carries title and description only


def test_selector_failure_falls_back_to_keywords_and_results_are_cached() -> None:
    memories = _memories(10)
    memories[4]["title"] = "Prefers dark roast coffee"
    calls = []

    def broken(system, query):
        calls.append(1)
        raise TimeoutError("ollama down")

    chosen, method = recall.select_relevant_memories("what coffee should I buy", memories, selector=broken)
    assert method == "keyword" and [m["id"] for m in chosen] == [5]
    again, method = recall.select_relevant_memories("what coffee should I buy", memories, selector=broken)
    assert method == "cached-keyword" and len(calls) == 1


def test_suppressed_and_rejected_memories_are_never_offered() -> None:
    memories = _memories(3)
    memories[0]["suppressed"] = 1
    memories[1]["feedback_score"] = -3
    chosen, _ = recall.select_relevant_memories("detail", memories)
    assert [m["id"] for m in chosen] == [3]


def _orchestrator(tmp_path: Path) -> tuple[MemoryOrchestrator, SQLiteMemoryStore]:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    return MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    ), store


def test_prompt_packet_always_carries_standing_rules_and_counts_use(tmp_path: Path, monkeypatch) -> None:
    orchestrator, store = _orchestrator(tmp_path)
    rule = store.save_memory(kind="correction", text="Check that a tool succeeded before saying it is done.",
                             source_thread_id="t", confidence=0.9, scope="user_profile")
    hidden = store.save_memory(kind="preference", text="Prefers answers in Spanish.",
                               source_thread_id="t", confidence=0.9, scope="user_profile")
    store.set_suppressed(hidden)
    facts = [store.save_memory(kind="fact", text=f"Owns a vintage camera model number {i}.",
                               source_thread_id="t", confidence=0.9) for i in range(8)]
    monkeypatch.setattr(recall, "_model_select", lambda *a, **k: ([store.get_memory(facts[2])], "model"))

    packet = orchestrator.build_memory_packet(thread_id="t", query="camera advice", select_with_model=True,
                                              live_honcho=False, include_history=False)
    ids = [item["id"] for item in packet["saved_memories"]]
    assert rule in ids and facts[2] in ids and hidden not in ids
    assert packet["recall_method"] == "model"
    assert store.get_memory(facts[2])["use_count"] == 1
    assert store.get_memory(rule)["use_count"] == 0  # standing rules are not "recalled"


def test_archived_memories_stay_recallable_until_deleted(tmp_path: Path) -> None:
    orchestrator, store = _orchestrator(tmp_path)
    old = store.save_memory(kind="fact", text="Visited Lisbon for a conference in spring.",
                            source_thread_id="t", confidence=0.9)
    store.archive(old)
    packet = orchestrator.build_memory_packet(thread_id="t", query="Lisbon trip", select_with_model=True,
                                              live_honcho=False, include_history=False)
    assert old in [item["id"] for item in packet["saved_memories"]]
    store.update_settings({"use_archived_memories": False})
    recall.clear_cache()
    packet = orchestrator.build_memory_packet(thread_id="t", query="Lisbon trip", select_with_model=True,
                                              live_honcho=False, include_history=False)
    assert old not in [item["id"] for item in packet["saved_memories"]]


def test_stream_previews_only_what_the_learner_saves_immediately(monkeypatch, tmp_path: Path) -> None:
    from agent import api

    orchestrator, _store = _orchestrator(tmp_path)
    monkeypatch.setattr(api, "_memory_orchestrator", orchestrator)
    saves = api._memory_save_activities("You got that wrong again. Check the logs before guessing.")
    assert [item["label"] for item in saves] == ["Saved to memory · Check the logs before guessing"]
    assert api._memory_save_activities("What is the capital of France?") == []
    assert api._memory_save_activities("I prefer short answers.", "MusicAgent") == []
