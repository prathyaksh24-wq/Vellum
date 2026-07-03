"""Compatibility facade for Vellum's canonical skill package registry."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from agent.skills import SkillRegistry


SKILLS_PATH = Path(__file__).resolve().parents[3] / ".skills"


class SkillStore:
    def __init__(self, root: str | Path = SKILLS_PATH):
        self.root = Path(root)
        self.registry = SkillRegistry(local_root=self.root / "packages")

    def load_active_skills(self) -> list[dict[str, Any]]:
        canonical: dict[str, dict[str, Any]] = {}
        for entry in self.registry.list_skills():
            package = self.registry.view(entry.name)
            vellum = package.metadata.metadata.vellum
            canonical[entry.name] = {
                "id": entry.name,
                "name": package.metadata.description,
                "trigger": list(vellum.trigger),
                "negative_trigger": list(vellum.negative_trigger),
                "confidence_threshold": vellum.confidence_threshold,
                "route_to_agent": vellum.route_to_agent,
                "routing_critical": vellum.routing_critical,
                "instructions": package.body,
                "skill_package": str(package.root),
            }
        legacy = self._load_legacy_skills()
        for skill in legacy:
            canonical.setdefault(str(skill.get("id") or ""), skill)
        return [canonical[name] for name in sorted(canonical)]

    def matching_skills(self, query: str) -> list[dict[str, Any]]:
        query_terms = set(_terms(query))
        if not query_terms:
            return []
        matches = []
        for skill in self.load_active_skills():
            if _has_term_subset(query_terms, skill.get("negative_trigger", [])):
                continue
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

    def _load_legacy_skills(self) -> list[dict[str, Any]]:
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


def _terms(text: str) -> list[str]:
    return [term.casefold() for term in re.findall(r"[A-Za-z0-9]+", text) if len(term) > 2]


def _has_term_subset(query_terms: set[str], phrases: list[str]) -> bool:
    for phrase in phrases:
        phrase_terms = set(_terms(phrase))
        if phrase_terms and phrase_terms <= query_terms:
            return True
    return False
