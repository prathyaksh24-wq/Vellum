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
        builtin = self._builtins[profile_id]
        path = self.profile_dir / f"{profile_id}.yaml"
        if not path.exists():
            return builtin.model_copy(deep=True)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("profile YAML must contain an object")
            merged = _deep_merge(builtin.model_dump(mode="python"), loaded)
            profile = AgentProfile.model_validate(merged)
            if profile.id != profile_id:
                raise ValueError(f"profile id must remain {profile_id}")
            return profile
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._record(profile_id, "fallback", str(exc))
            return builtin.model_copy(deep=True)

    def try_get(self, profile_id: str) -> AgentProfile | None:
        if profile_id not in self._builtins:
            return None
        return self.get(profile_id)

    def list(self) -> list[AgentProfile]:
        return [self.get(profile_id) for profile_id in sorted(self._builtins)]

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
        return [profile.model_dump(mode="json") for profile in self.list()]

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
