from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from agent.profiles.models import AgentProfile, builtin_profiles


class ProfileRegistry:
    def __init__(
        self,
        profile_dir: Path | str = Path("data/agent_profiles"),
        builtins: Mapping[str, AgentProfile] | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self._builtins = dict(builtins or builtin_profiles())
        self._diagnostics: list[dict[str, str]] = []

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
            loaded = _migrate_profile_dict(profile_id, loaded)
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

    def instructions_for(self, profile: AgentProfile) -> str:
        if not profile.instructions:
            return ""
        root = self.profile_dir.resolve()
        path = (self.profile_dir / profile.instructions).resolve()
        if not path.is_relative_to(root):
            self._record(profile.id, "blocked_instruction_path", "instruction path leaves profile directory")
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            self._record(profile.id, "instruction_unavailable", str(exc))
            return ""

    def diagnostics(self) -> list[dict[str, str]]:
        return list(self._diagnostics)

    def public_summaries(self) -> list[dict[str, Any]]:
        summaries = []
        for profile in self.list():
            summaries.append(
                {
                    "id": profile.id,
                    "version": profile.version,
                    "description": profile.description,
                    "executor": profile.executor,
                    "model": profile.model,
                    "tools": profile.tools.model_dump(mode="json"),
                    "memory": profile.memory.model_dump(mode="json"),
                    "cache": profile.cache.model_dump(mode="json"),
                    "delegation": profile.delegation.model_dump(mode="json"),
                }
            )
        return summaries

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


def _migrate_profile_dict(profile_id: str, data: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(data)
    if int(migrated.get("version") or 1) < 2:
        migrated["version"] = 2
    migrated.setdefault(
        "department",
        {"SportsAgent": "sports", "XAgent": "social", "YoutubeAgent": "social", "MemoryAgent": "memory"}.get(
            profile_id, "general"
        ),
    )
    migrated.setdefault("isolation", {"backend": "subprocess", "allow_fallback": False})
    return migrated
