from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from agent.profiles.models import AgentProfile


@dataclass(frozen=True)
class PromptSection:
    kind: str
    content: str
    source_hash: str


@dataclass(frozen=True)
class IdentityStack:
    sections: tuple[PromptSection, ...]
    identity_hash: str
    diagnostics: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n\n".join(section.content for section in self.sections if section.content)


class IdentityLoader:
    _UNSAFE = (
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
        re.compile(r"reveal\s+(?:the\s+)?system\s+prompt", re.I),
        re.compile(r"override\s+(?:safety|system|tool|capabilit)", re.I),
    )

    def __init__(self, home: str | Path) -> None:
        self.home = Path(home).resolve()

    def load(self, profile: AgentProfile, *, personality: str | None = None) -> IdentityStack:
        diagnostics: list[str] = []
        soul = self._read(profile.identity.soul, profile.identity.max_identity_chars, diagnostics)
        if not soul:
            soul = f"You are {profile.id}, a focused Vellum specialist."
        agents = self._read(profile.identity.agents, profile.identity.max_identity_chars, diagnostics)
        overlay_name = personality or profile.identity.default_personality
        overlay = self._read(f"personalities/{overlay_name}.md", profile.identity.max_identity_chars, diagnostics)
        sections = [self._section("soul", soul)]
        if agents:
            sections.append(self._section("agents", agents))
        if overlay:
            sections.append(self._section("personality", overlay))
        digest = hashlib.sha256("\n".join(section.source_hash for section in sections).encode()).hexdigest()
        return IdentityStack(tuple(sections), digest, tuple(diagnostics))

    def _read(self, relative: str, limit: int, diagnostics: list[str]) -> str:
        path = (self.home / relative).resolve()
        if not path.is_relative_to(self.home):
            diagnostics.append(f"blocked path: {relative}")
            return ""
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        if "\x00" in text or any(pattern.search(text) for pattern in self._UNSAFE):
            diagnostics.append(f"unsafe identity: {relative}")
            return ""
        if len(text) > limit:
            text = text[: max(0, limit - 14)].rstrip() + "\n[truncated]"
        return text

    @staticmethod
    def _section(kind: str, content: str) -> PromptSection:
        return PromptSection(kind, content, hashlib.sha256(content.encode()).hexdigest())
