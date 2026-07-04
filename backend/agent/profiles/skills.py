from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ActivatedSkill:
    id: str
    description: str
    instructions: str
    priority: int
    source_hash: str


@dataclass(frozen=True)
class ActivatedSkills:
    skills: tuple[ActivatedSkill, ...]
    skill_hash: str
    diagnostics: tuple[str, ...] = ()


class AgentSkillLoader:
    def __init__(self, home: str | Path, *, max_chars: int = 12000) -> None:
        self.home = Path(home).resolve()
        self.max_chars = max_chars

    def activate(self, goal: str) -> ActivatedSkills:
        diagnostics: list[str] = []
        parsed: list[tuple[dict[str, Any], str, str]] = []
        ids: set[str] = set()
        skill_dir = self.home / "skills"
        for path in sorted(skill_dir.glob("*.md")) if skill_dir.exists() else []:
            try:
                metadata, body = _parse_skill(path.read_text(encoding="utf-8"))
                skill_id = str(metadata["id"])
                if skill_id in ids:
                    diagnostics.append(f"duplicate skill id: {skill_id}")
                    return ActivatedSkills((), "", tuple(diagnostics))
                ids.add(skill_id)
                parsed.append((metadata, body[: self.max_chars], hashlib.sha256(path.read_bytes()).hexdigest()))
            except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
                diagnostics.append(f"{path.name}: {exc}")
        lowered = goal.casefold()
        if any(any(str(term).casefold() in lowered for term in meta.get("negative_triggers", [])) for meta, _, _ in parsed):
            return ActivatedSkills((), "", tuple(diagnostics))
        active: list[ActivatedSkill] = []
        for meta, body, source_hash in parsed:
            triggers = [str(term).casefold() for term in meta.get("triggers", [])]
            if triggers and any(term in lowered for term in triggers):
                active.append(
                    ActivatedSkill(
                        id=str(meta["id"]),
                        description=str(meta.get("description") or ""),
                        instructions=body.strip(),
                        priority=int(meta.get("priority") or 0),
                        source_hash=source_hash,
                    )
                )
        active.sort(key=lambda item: (item.priority, item.id))
        digest = hashlib.sha256("\n".join(item.source_hash for item in active).encode()).hexdigest() if active else ""
        return ActivatedSkills(tuple(active), digest, tuple(diagnostics))


def _parse_skill(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    if not isinstance(metadata, dict) or not metadata.get("id"):
        raise ValueError("invalid skill metadata")
    return metadata, body
