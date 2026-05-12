from agent.memory.fts5 import FTS5Memory, DB_PATH as FTS5_DB_PATH
from agent.memory.honcho_client import HonchoMemory
from agent.memory.resolved import ResolvedQuestionsCache, DB_PATH as RESOLVED_DB_PATH
from agent.memory.skills import SkillStore


def test_fts5_indexes_and_searches_qa_pairs(tmp_path):
    memory = FTS5Memory(tmp_path / "fts5.db")

    rowid = memory.add_qa_pair(
        query="What did I write about Marcus Aurelius?",
        answer="You connected discipline with attention.",
        thread_id="t1",
        source_paths=["Books/Meditations.md"],
    )

    assert rowid == 1
    results = memory.search("Marcus discipline")
    assert results[0]["thread_id"] == "t1"
    assert "discipline" in results[0]["content"]


def test_resolved_cache_round_trip_and_access_count(tmp_path):
    cache = ResolvedQuestionsCache(tmp_path / "resolved.db")
    cache.store(
        query="repeat question",
        answer_summary="cached answer",
        sources=["Agent/Responses/QA.md"],
        confidence=0.91,
        model="fast",
    )

    cached = cache.get("repeat question")

    assert cached is not None
    assert cached["answer_summary"] == "cached answer"
    assert cached["access_count"] == 1


def test_skill_store_loads_matching_active_skills(tmp_path):
    active = tmp_path / ".skills" / "active"
    active.mkdir(parents=True)
    (active / "skill-book-summary-v1.json").write_text(
        """{
  "id": "skill-book-summary-v1",
  "name": "Book summary",
  "trigger": ["summarize", "book"],
  "confidence_threshold": 0.1,
  "instructions": "Use concise footnotes.",
  "citation_style": "footnotes",
  "output_format": "prose",
  "created": "2026-05-12",
  "approved": "2026-05-12",
  "use_count": 0
}""",
        encoding="utf-8",
    )

    block = SkillStore(tmp_path / ".skills").build_prompt_block("summarize this book")

    assert "## Active Skills" in block
    assert "Use concise footnotes." in block


def test_honcho_memory_is_local_noop_when_sdk_missing(monkeypatch):
    monkeypatch.setattr("agent.memory.honcho_client.Honcho", None)
    memory = HonchoMemory(base_url="http://localhost:8001", app_id="vellum", user_id="default")

    assert memory.chat(session_id="t1", query="What do I care about?") == ""
    assert memory.add_message("t1", content="hello", role="user") is None


def test_default_memory_paths_match_new_architecture():
    assert FTS5_DB_PATH.as_posix() == "data/memory/fts5.db"
    assert RESOLVED_DB_PATH.as_posix() == "data/memory/resolved.db"
