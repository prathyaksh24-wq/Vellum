from pathlib import Path

from agent.agents.memory_agent import MemoryAgent
from agent.memory.fts5 import FTS5Memory
from agent.memory.orchestrator import MemoryOrchestrator, SQLiteMemoryStore
from agent.memory.resolved import ResolvedQuestionsCache
from agent.observability.activity import observe_activity
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def _agent(tmp_path: Path) -> tuple[MemoryAgent, SQLiteMemoryStore]:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    orchestrator = MemoryOrchestrator(
        fts5=FTS5Memory(tmp_path / "fts5.db"),
        resolved_cache=ResolvedQuestionsCache(tmp_path / "resolved.db"),
        memory_service=MemoryCapabilityService(sessions_db=tmp_path / "sessions.db"),
        store=store,
        memory_dir=tmp_path / "memory-files",
    )
    return MemoryAgent(memory_service=object(), orchestrator_provider=lambda: orchestrator), store


def test_remember_saves_exactly_one_stated_memory_and_reports_it_live(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path)
    events = []
    with observe_activity(events.append):
        response = agent.answer("Remember that I prefer tea over coffee")
        again = agent.answer("Remember that I prefer tea over coffee")
    saved = store.list_saved()
    assert len(saved) == 1
    assert saved[0]["origin"] == "stated" and saved[0]["scope"] == "user_profile"
    assert response.summary == "Saved to memory: I prefer tea over coffee."
    assert again.summary.startswith("I already remember that")
    assert [event["type"] for event in events] == ["memory_save"]
    assert events[0]["label"] == "Saved to memory · Prefer tea over coffee"


def test_forget_stops_using_a_memory_without_deleting_it(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path)
    agent.answer("Remember that my gym days are Monday and Thursday")
    response = agent.answer("Forget my gym days")
    item = store.list_saved()[0]
    assert item["suppressed"] == 1
    assert "stop using" in response.summary and "Memory page" in response.summary


def test_lookup_answers_from_the_real_store(tmp_path: Path) -> None:
    agent, store = _agent(tmp_path)
    store.save_memory(kind="preference", text="Prefers window seats on flights.", source_thread_id="t",
                      confidence=0.9, scope="user_profile")
    response = agent.answer("What do you remember about me?")
    assert response.status == "answered"
    assert "window seats" in response.summary
    assert response.sources and response.sources[0].path_or_url.startswith("memory:")


def test_without_an_orchestrator_the_old_proposal_path_is_unchanged() -> None:
    agent = MemoryAgent(memory_service=type("Svc", (), {
        "propose_card": lambda self, payload: {"proposal": {"scope": "memory", "claim": payload["claim"],
                                                            "evidence": payload["evidence"], "confidence": 0.8}},
        "review_proposals": lambda self, payload: {"accepted": payload["proposals"]},
    })())
    response = agent.answer("Remember that I like jazz")
    assert response.memory_proposals and "no durable memory was written" in response.analysis
