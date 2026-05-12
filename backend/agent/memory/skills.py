"""Local procedural skill loader."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

SKILLS_PATH = Path(".skills")


class SkillStore:
    def __init__(self, root: str | Path = SKILLS_PATH):
        self.root = Path(root)

    def load_active_skills(self) -> list[dict[str, Any]]:
        active = self.root / "active"
        if not active.exists():
            return []
        skills: list[dict[str, Any]] = []
        for path in sorted(active.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("instructions"):
                skills.append(data)
        return skills

    def matching_skills(self, query: str) -> list[dict[str, Any]]:
        query_terms = set(_terms(query))
        if not query_terms:
            return []
        matches = []
        for skill in self.load_active_skills():
            trigger_terms = set(_terms(" ".join(skill.get("trigger", []))))
            if not trigger_terms:
                continue
            score = len(query_terms & trigger_terms) / len(trigger_terms)
            if score >= float(skill.get("confidence_threshold", 0.75)):
                matches.append(skill)
        return matches

    def build_prompt_block(self, query: str) -> str:
        matches = self.matching_skills(query)
        if not matches:
            return ""
        sections = ["## Active Skills"]
        for skill in matches:
            sections.append(f"### {skill.get('name', skill.get('id', 'Skill'))}\n{skill['instructions']}")
        return "\n\n".join(sections)


def _terms(text: str) -> list[str]:
    return [term.casefold() for term in re.findall(r"[A-Za-z0-9]+", text) if len(term) > 2]
