from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

import yaml

from agent.profiles.models import AgentProfile, builtin_profiles


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentBinding:
    profile: AgentProfile
    executor: Any | None


class AgentCatalog:
    """Canonical owner of agent profiles and their runtime executors."""

    def __init__(
        self,
        profile_dir: Path | str = Path("data/agent_profiles"),
        builtins: Mapping[str, AgentProfile] | None = None,
        executors: Mapping[str, Any] | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self._builtins = dict(builtins or builtin_profiles())
        self._executors = dict(executors or {})
        self._diagnostics: list[dict[str, str]] = []

    @classmethod
    def default(
        cls,
        vault_root: Path,
        profile_dir: Path | str = Path("data/agent_profiles"),
    ) -> "AgentCatalog":
        from agent.agents.books import BooksAgent
        from agent.agents.memory_agent import MemoryAgent
        from agent.agents.sports import SportsAgent
        from agent.agents.x_agent import XAgent
        from agent.agents.youtube import YoutubeAgent
        from agent.tools.capabilities.registry import build_shared_tool_registry

        root = Path(vault_root)
        tools = build_shared_tool_registry(vault_root=root)
        agents = [
            XAgent(vault_root=root, tool_registry=tools),
            YoutubeAgent(vault_root=root, tool_registry=tools),
            MemoryAgent(vault_root=root, tool_registry=tools),
            SportsAgent(vault_root=root, tool_registry=tools),
            BooksAgent(tool_registry=tools),
        ]
        return cls(profile_dir=profile_dir, executors={agent.name: agent for agent in agents})

    def get(self, profile_id: str) -> AgentProfile:
        builtin = self._builtins.get(profile_id)
        path = self.profile_dir / f"{profile_id}.yaml"
        if not path.exists():
            if builtin is None:
                raise KeyError(profile_id)
            return builtin.model_copy(deep=True)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("profile YAML must contain an object")
            merged = _deep_merge(builtin.model_dump(mode="python") if builtin is not None else {}, loaded)
            profile = AgentProfile.model_validate(merged)
            if profile.id != profile_id:
                raise ValueError(f"profile id must remain {profile_id}")
            return profile
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._record(profile_id, "fallback", str(exc))
            if builtin is None:
                raise KeyError(profile_id) from exc
            return builtin.model_copy(deep=True)

    def try_get(self, profile_id: str) -> AgentProfile | None:
        if profile_id not in self._builtins and not (self.profile_dir / f"{profile_id}.yaml").exists():
            return None
        try:
            return self.get(profile_id)
        except KeyError:
            return None

    def list(self) -> list[AgentProfile]:
        discovered = {path.stem for path in self.profile_dir.glob("*.yaml")} if self.profile_dir.exists() else set()
        profiles = []
        for profile_id in sorted(set(self._builtins) | discovered):
            profile = self.try_get(profile_id)
            if profile is not None:
                profiles.append(profile)
        return profiles

    def resolve(self, profile_id: str) -> AgentBinding:
        return AgentBinding(profile=self.get(profile_id), executor=self._executors.get(profile_id))

    def try_resolve(self, profile_id: str) -> AgentBinding | None:
        profile = self.try_get(profile_id)
        return None if profile is None else AgentBinding(profile=profile, executor=self._executors.get(profile_id))

    def match(self, query: str) -> AgentBinding | None:
        for profile_id, executor in self._executors.items():
            try:
                if executor.can_handle(query):
                    return AgentBinding(profile=self.get(profile_id), executor=executor)
            except Exception:
                logger.exception("Agent matcher failed for %s.", profile_id)
                continue
        return None

    def names(self) -> list[str]:
        return sorted(profile.id for profile in self.list())

    def executor(self, profile_id: str) -> Any | None:
        return self._executors.get(profile_id)

    def register_executor(self, profile_id: str, executor: Any) -> None:
        self._executors[profile_id] = executor

    def instructions_for(self, profile: AgentProfile) -> str:
        sections = [profile.instructions.inline.strip()] if profile.instructions.inline.strip() else []
        root = self.profile_dir.resolve()
        for instruction_file in profile.instructions.files:
            path = (self.profile_dir / instruction_file).resolve()
            if not path.is_relative_to(root):
                self._record(profile.id, "blocked_instruction_path", "instruction path leaves profile directory")
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                self._record(profile.id, "instruction_unavailable", str(exc))
                continue
            if content:
                sections.append(content)
        return "\n\n".join(sections)

    def diagnostics(self) -> list[dict[str, str]]:
        return list(self._diagnostics)

    def public_diagnostics(self) -> list[dict[str, str]]:
        return [
            {
                "profile_id": item["profile_id"],
                "status": item["status"],
                "detail": "Profile configuration unavailable.",
            }
            for item in self._diagnostics
        ]

    def public_summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "id": profile.id,
                "version": profile.version,
                "description": profile.description,
                "executor": profile.executor,
                "model": profile.model,
                "tools": profile.tools.model_dump(mode="json"),
                "skills": profile.skills.model_dump(mode="json"),
                "memory": profile.memory.model_dump(mode="json"),
                "cache": profile.cache.model_dump(mode="json"),
                "delegation": profile.delegation.model_dump(mode="json"),
                "response_schema": profile.response_schema,
            }
            for profile in self.list()
        ]

    def _record(self, profile_id: str, status: str, detail: str) -> None:
        self._diagnostics.append({"profile_id": profile_id, "status": status, "detail": detail[:300]})


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
