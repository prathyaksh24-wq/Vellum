from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from agent.profiles import AgentCatalog, AgentProfile, profile_policy
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


class FakeBooksExecutor:
    name = "BooksAgent"

    def can_handle(self, query: str) -> bool:
        _ = query
        return False

    def answer(self, query: str):
        raise AssertionError("catalog resolution must not execute the agent")


def test_agent_catalog_resolves_complete_profile_and_executor(tmp_path: Path) -> None:
    executor = FakeBooksExecutor()
    profile = AgentProfile(
        id="BooksAgent",
        instructions={"files": ["books/SOUL.md"]},
        tools={"allow": ["knowledge.books.search"]},
        skills={"allow": ["book-to-skill", "naval-almanack"]},
        memory={
            "read_scopes": ["user_profile", "shared", "agent:BooksAgent"],
            "write_scope": "agent:BooksAgent",
            "shared_writes": "propose_only",
        },
        response_schema="books-agent-result-v1",
    )
    catalog = AgentCatalog(
        profile_dir=tmp_path,
        builtins={"BooksAgent": profile},
        executors={"BooksAgent": executor},
    )

    binding = catalog.resolve("BooksAgent")

    assert binding.profile.id == "BooksAgent"
    assert binding.profile.skills.allow == ["book-to-skill", "naval-almanack"]
    assert binding.profile.memory.shared_writes == "propose_only"
    assert binding.profile.response_schema == "books-agent-result-v1"
    assert binding.executor is executor


def test_builtin_profiles_preserve_deterministic_specialists(tmp_path: Path) -> None:
    registry = AgentCatalog(profile_dir=tmp_path)

    sports = registry.get("SportsAgent")

    assert sports.executor == "deterministic"
    assert sports.memory.write_scope == "agent:SportsAgent"
    assert sports.memory.read_scopes == ["user_profile", "shared", "agent:SportsAgent"]
    assert sports.memory.cache_first is True
    assert sports.delegation.can_delegate is False


def test_yaml_profile_overrides_builtin_without_losing_defaults(tmp_path: Path) -> None:
    (tmp_path / "SportsAgent.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "id": "SportsAgent",
                "executor": "llm",
                "description": "Focused sports analyst",
                "model": "openrouter/auto",
                "tools": {"allow": []},
                "cache": {"default_ttl_seconds": 900},
            }
        ),
        encoding="utf-8",
    )

    profile = AgentCatalog(profile_dir=tmp_path).get("SportsAgent")

    assert profile.version == 2
    assert profile.executor == "llm"
    assert profile.model == "openrouter/auto"
    assert profile.cache.default_ttl_seconds == 900
    assert profile.cache.live_ttl_seconds == 120


def test_invalid_yaml_falls_back_to_builtin_and_records_diagnostic(tmp_path: Path) -> None:
    (tmp_path / "SportsAgent.yaml").write_text(
        "version: 1\nid: SportsAgent\nexecutor: shell\n",
        encoding="utf-8",
    )
    registry = AgentCatalog(profile_dir=tmp_path)

    profile = registry.get("SportsAgent")

    assert profile.executor == "deterministic"
    assert registry.diagnostics()[0]["profile_id"] == "SportsAgent"
    assert registry.diagnostics()[0]["status"] == "fallback"


def test_profile_instruction_path_must_stay_inside_profile_directory(tmp_path: Path) -> None:
    profile = AgentProfile(id="ResearchAgent", executor="llm", instructions={"files": ["../secret.txt"]})
    registry = AgentCatalog(profile_dir=tmp_path, builtins={"ResearchAgent": profile})

    assert registry.instructions_for(profile) == ""
    assert registry.diagnostics()[0]["status"] == "blocked_instruction_path"


def test_llm_profile_rejects_tools_until_allowlisted_tool_loop_exists() -> None:
    with pytest.raises(ValidationError, match="LLM profile tools are not supported"):
        AgentProfile(id="ResearchAgent", executor="llm", tools={"allow": ["web.search"]})


def test_memory_agent_cannot_widen_its_private_write_scope() -> None:
    with pytest.raises(ValidationError, match="write_scope must be agent:MemoryAgent"):
        AgentProfile(id="MemoryAgent", memory={"write_scope": "shared"})


def test_active_profile_can_narrow_shared_tool_registry() -> None:
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent"}),
            stream_label="Searching sports",
            adapter=lambda payload: {"query": payload["query"]},
        )
    )

    with profile_policy(profile_id="SportsAgent", allowed_tools=frozenset()):
        with pytest.raises(ToolPermissionError, match="profile policy"):
            registry.invoke("sports.search", {"query": "NBA"}, agent_name="SportsAgent")


def test_active_profile_can_require_confirmation_for_read_tool() -> None:
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent"}),
            stream_label="Searching sports",
            adapter=lambda payload: {"query": payload["query"]},
        )
    )

    with profile_policy(
        profile_id="SportsAgent",
        allowed_tools=frozenset({"sports.search"}),
        require_confirmation=frozenset({"sports.search"}),
    ):
        with pytest.raises(ToolPermissionError, match="explicit confirmation"):
            registry.invoke("sports.search", {"query": "NBA"}, agent_name="SportsAgent")


def test_no_active_profile_preserves_legacy_tool_permissions() -> None:
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent"}),
            stream_label="Searching sports",
            adapter=lambda payload: {"ok": True},
        )
    )

    assert registry.invoke("sports.search", {}, agent_name="SportsAgent") == {"ok": True}


def test_memory_profile_bypasses_mutating_memory_instructions(tmp_path: Path) -> None:
    profile = AgentCatalog(profile_dir=tmp_path).get("MemoryAgent")

    assert {"remember", "memorize", "note", "forget", "delete"} <= set(profile.cache.bypass_terms)


def test_youtube_profile_bypasses_generic_response_cache(tmp_path: Path) -> None:
    profile = AgentCatalog(profile_dir=tmp_path).get("YoutubeAgent")

    assert profile.memory.cache_first is False


def test_registry_discovers_new_llm_profile_from_yaml(tmp_path: Path) -> None:
    (tmp_path / "ResearchAgent.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "id": "ResearchAgent",
                "description": "Independent research specialist",
                "executor": "llm",
                "model": "openrouter/auto",
                "tools": {"allow": []},
                "memory": {
                    "read_scopes": ["user_profile", "shared", "agent:ResearchAgent"],
                    "write_scope": "agent:ResearchAgent",
                },
            }
        ),
        encoding="utf-8",
    )

    registry = AgentCatalog(profile_dir=tmp_path)

    assert registry.try_get("ResearchAgent").executor == "llm"
    assert "ResearchAgent" in [profile.id for profile in registry.list()]


def test_profile_v2_declares_instructions_skills_and_delegation_policy() -> None:
    profile = AgentProfile(
        id="ResearchAgent",
        executor="llm",
        instructions={"inline": "Investigate claims and preserve provenance."},
        tools={"allow": []},
        skills={"allow": ["research"]},
        memory={
            "read_scopes": ["user_profile", "shared", "agent:ResearchAgent"],
            "write_scope": "agent:ResearchAgent",
            "shared_writes": "propose_only",
        },
        delegation={"can_receive": True, "can_delegate": False, "max_depth": 1},
        response_schema="research-result-v1",
    )

    assert profile.version == 2
    assert profile.instructions.inline.startswith("Investigate claims")
    assert profile.tools.allow == []
    assert profile.skills.allow == ["research"]
    assert profile.memory.write_scope == "agent:ResearchAgent"
    assert profile.delegation.can_receive is True
    assert profile.delegation.can_delegate is False
    assert profile.delegation.max_depth == 1


def test_default_agent_catalog_shares_tools_and_owns_builtin_profiles(tmp_path: Path) -> None:
    catalog = AgentCatalog.default(vault_root=tmp_path)

    x_binding = catalog.resolve("XAgent")
    youtube_binding = catalog.resolve("YoutubeAgent")
    discord_binding = catalog.resolve("DiscordAgent")
    memory_binding = catalog.resolve("MemoryAgent")

    assert x_binding.profile.version == 2
    assert x_binding.profile.instructions.inline
    assert x_binding.executor.tool_registry is youtube_binding.executor.tool_registry
    assert x_binding.executor.tool_registry is memory_binding.executor.tool_registry
    assert x_binding.executor.tool_registry is discord_binding.executor.tool_registry
    assert "youtube.search_videos" in x_binding.executor.tool_registry.names()
    assert "discord.messages" in x_binding.executor.tool_registry.names()


def test_builtin_books_profile_uses_knowledge_core_and_explicit_delegation(tmp_path: Path) -> None:
    profile = AgentCatalog(profile_dir=tmp_path).get("BooksAgent")

    assert profile.response_schema == "books-agent-response-v1"
    assert profile.tools.allow == [
        "books.knowledge_query", "books.skill_lookup", "books.discover", "books.verify_candidate",
    ]
    assert profile.tools.require_confirmation == ["books.discover", "books.verify_candidate"]
    assert profile.book_discovery_network is False
    assert profile.skills.allow == ["book-to-skill"]
    assert profile.memory.write_scope == "agent:BooksAgent"
    assert profile.memory.shared_writes == "propose_only"


def test_agent_catalog_does_not_auto_route_explicit_only_books_profile(tmp_path: Path) -> None:
    executor = FakeBooksExecutor()
    profile = AgentCatalog(profile_dir=tmp_path).get("BooksAgent")
    catalog = AgentCatalog(
        profile_dir=tmp_path,
        builtins={"BooksAgent": profile},
        executors={"BooksAgent": executor},
    )

    assert catalog.match("Tell me about this book") is None
