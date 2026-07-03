from pathlib import Path

import pytest
import yaml

from agent.profiles import AgentProfile, ProfileRegistry, profile_policy
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


def test_builtin_profiles_preserve_deterministic_specialists(tmp_path: Path) -> None:
    registry = ProfileRegistry(profile_dir=tmp_path)

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

    profile = ProfileRegistry(profile_dir=tmp_path).get("SportsAgent")

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
    registry = ProfileRegistry(profile_dir=tmp_path)

    profile = registry.get("SportsAgent")

    assert profile.executor == "deterministic"
    assert registry.diagnostics()[0]["profile_id"] == "SportsAgent"
    assert registry.diagnostics()[0]["status"] == "fallback"


def test_profile_instruction_path_must_stay_inside_profile_directory(tmp_path: Path) -> None:
    profile = AgentProfile(id="ResearchAgent", executor="llm", instructions="../secret.txt")
    registry = ProfileRegistry(profile_dir=tmp_path, builtins={"ResearchAgent": profile})

    assert registry.instructions_for(profile) == ""
    assert registry.diagnostics()[0]["status"] == "blocked_instruction_path"


def test_llm_profile_rejects_declared_tools() -> None:
    with pytest.raises(ValueError, match="reasoning-only"):
        AgentProfile(id="ResearchAgent", executor="llm", tools={"allow": ["web.search"]})


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
    profile = ProfileRegistry(profile_dir=tmp_path).get("MemoryAgent")

    assert {"remember", "memorize", "note", "forget", "delete"} <= set(profile.cache.bypass_terms)
