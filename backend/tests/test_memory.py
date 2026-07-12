import json
from pathlib import Path

from agent.memory.fts5 import FTS5Memory, DB_PATH as FTS5_DB_PATH
from agent.memory.honcho_client import HonchoMemory
from agent.memory.resolved import ResolvedQuestionsCache, DB_PATH as RESOLVED_DB_PATH
from agent.memory.skills import SkillStore


REPO_ROOT = Path(__file__).resolve().parents[2]


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
    package = tmp_path / ".skills" / "packages" / "writing" / "skill-book-summary-v1"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: skill-book-summary-v1
description: Book summary
metadata:
  vellum:
    trigger: [summarize, book]
    confidence_threshold: 0.1
---
# Book summary

## Procedure
Use concise footnotes.
""",
        encoding="utf-8",
    )

    block = SkillStore(tmp_path / ".skills").build_prompt_block("summarize this book")

    assert "## Active Skills" in block
    assert "Use concise footnotes." in block


def test_skill_store_skips_negative_triggers(tmp_path):
    package = tmp_path / ".skills" / "packages" / "engineering" / "skill-debugging-v1"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: skill-debugging-v1
description: Debugging
metadata:
  vellum:
    trigger: [debug, test failure, failing test]
    negative_trigger: [write test, write tests, add tests]
    confidence_threshold: 0.1
---
# Debugging

## Procedure
Investigate before fixing.
""",
        encoding="utf-8",
    )

    store = SkillStore(tmp_path / ".skills")

    assert store.matching_skills("debug this failing test")
    assert store.matching_skills("write test failure coverage for this module") == []


def test_skill_store_prefers_canonical_package_over_legacy_json(tmp_path):
    package = tmp_path / ".skills" / "packages" / "research" / "shared-skill"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: shared-skill
description: Canonical shared skill
metadata:
  vellum:
    trigger: [canonical, shared]
    confidence_threshold: 0.1
---
# Canonical

## Procedure
Use canonical instructions.
""",
        encoding="utf-8",
    )
    active = tmp_path / ".skills" / "active"
    active.mkdir()
    (active / "shared-skill.json").write_text(
        json.dumps(
            {
                "id": "shared-skill",
                "name": "Legacy shared skill",
                "trigger": ["legacy", "shared"],
                "confidence_threshold": 0.1,
                "instructions": "Use legacy instructions.",
            }
        ),
        encoding="utf-8",
    )

    store = SkillStore(tmp_path / ".skills")

    skills = {skill["id"]: skill for skill in store.load_active_skills()}
    assert skills["shared-skill"]["instructions"] == "# Canonical\n\n## Procedure\nUse canonical instructions."
    assert store.matching_skills("canonical shared")
    assert store.matching_skills("legacy request") == []


def test_skill_store_does_not_load_unmigrated_json(tmp_path):
    active = tmp_path / ".skills" / "active"
    active.mkdir(parents=True)
    (active / "legacy.json").write_text(
        json.dumps(
            {
                "id": "legacy",
                "name": "Legacy",
                "trigger": ["legacy", "request"],
                "confidence_threshold": 0.1,
                "instructions": "Legacy instructions.",
            }
        ),
        encoding="utf-8",
    )

    assert SkillStore(tmp_path / ".skills").matching_skills("legacy request") == []


def test_production_skill_store_includes_requested_capability_skills():
    skills = {skill["id"]: skill for skill in SkillStore(REPO_ROOT / ".skills").load_active_skills()}

    assert "skill-find-skills-v1" in skills
    assert "skill-systematic-debugging-v1" in skills
    assert "skill-skill-creator-v1" in skills


def test_requested_capability_skills_match_realistic_prompts():
    store = SkillStore(REPO_ROOT / ".skills")

    cases = [
        ("find a skill for playwright visual regression testing", "skill-find-skills-v1"),
        ("my pytest run is failing with an assertion error, please debug it", "skill-systematic-debugging-v1"),
        ("create a Vellum skill for writing changelog entries in my house style", "skill-skill-creator-v1"),
    ]

    for prompt, skill_id in cases:
        matches = {skill["id"] for skill in store.matching_skills(prompt)}
        assert skill_id in matches


def test_requested_capability_skills_avoid_near_miss_prompts():
    store = SkillStore(REPO_ROOT / ".skills")

    cases = [
        ("write pytest tests for the new checkout feature", "skill-systematic-debugging-v1"),
        ("use the existing browser automation skill to inspect this page", "skill-find-skills-v1"),
        ("use the current sports memory skill to answer this", "skill-skill-creator-v1"),
    ]

    for prompt, skill_id in cases:
        matches = {skill["id"] for skill in store.matching_skills(prompt)}
        assert skill_id not in matches


def test_honcho_memory_is_local_noop_when_sdk_missing(monkeypatch):
    monkeypatch.setattr("agent.memory.honcho_client.Honcho", None)
    memory = HonchoMemory(base_url="http://localhost:8001", app_id="vellum", user_id="default")

    assert memory.chat(session_id="t1", query="What do I care about?") == ""
    assert memory.add_message("t1", content="hello", role="user") is None


def test_default_memory_paths_match_new_architecture():
    assert FTS5_DB_PATH.as_posix() == "data/memory/fts5.db"
    assert RESOLVED_DB_PATH.as_posix() == "data/memory/resolved.db"


def test_memory_context_block_includes_orchestrator_packet(monkeypatch):
    from agent.memory import memory_context

    class FakeOrchestrator:
        def build_memory_packet(self, **kwargs):
            assert kwargs["thread_id"] == "thread-1"
            assert kwargs["query"] == "What do you know about my Vellum project?"
            return {
                "global_summary": "User is building Vellum.",
                "saved_memories": [{"text": "User prefers concise answers."}],
                "honcho_context": "User cares about reliable agents.",
                "project_context": "Vellum uses sub-agents.",
                "recent_context": "Recent chat discussed memory orchestration.",
            }

    monkeypatch.setattr(memory_context, "load_soul", lambda: "")
    monkeypatch.setattr(memory_context, "get_user_model", lambda thread_id: "")
    monkeypatch.setattr(memory_context, "_ORCHESTRATOR", FakeOrchestrator())

    block = memory_context.build_memory_block("thread-1", query="What do you know about my Vellum project?")

    assert "# Memory packet" in block
    assert "User is building Vellum." in block
    assert "User prefers concise answers." in block
    assert "Vellum uses sub-agents." in block


def test_memory_context_block_includes_hermes_style_context_files(monkeypatch, tmp_path):
    from agent.memory import memory_context

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "USER.md").write_text("# User Profile\n\n- User prefers direct answers.", encoding="utf-8")
    (memory_dir / "MEMORY.md").write_text("# Agent Memory\n\n- Vellum uses Memory Orchestrator.", encoding="utf-8")

    class EmptyOrchestrator:
        def build_memory_packet(self, **kwargs):
            return {}

    monkeypatch.setattr(memory_context, "load_soul", lambda: "")
    monkeypatch.setattr(memory_context, "get_user_model", lambda thread_id: "")
    monkeypatch.setattr(memory_context, "_ORCHESTRATOR", EmptyOrchestrator())
    monkeypatch.setattr(memory_context, "_MEMORY_FILES_DIR", memory_dir)

    block = memory_context.build_memory_block("thread-1", query="What do you know about me?")

    assert "Hermes-style persistent memory" in block
    assert "User prefers direct answers" in block
    assert "Vellum uses Memory Orchestrator" in block
