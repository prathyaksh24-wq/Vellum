from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re

from agent.plugins.registry import get_plugin_registry
from agent.skills.registry import SkillRegistry
from agent.skills.configuration import SkillConfigStore


from agent.config import REPO_ROOT

SKILLS_PATH = REPO_ROOT / ".skills"
CORE_TOOL_NAMES = {
    "append_to_note",
    "browser_action",
    "browser_back",
    "browser_cdp",
    "browser_click",
    "browser_close",
    "browser_console",
    "browser_dialog",
    "browser_get_images",
    "browser_hover",
    "browser_navigate",
    "browser_press",
    "browser_press_key",
    "browser_scroll",
    "browser_select_option",
    "browser_snapshot",
    "browser_tabs",
    "browser_type",
    "browser_vision",
    "browser_wait",
    "books_agent",
    "computer_use",
    "computer_use_route",
    "context_mode",
    "create_note",
    "escalate_to_cloud",
    "git_action",
    "github_read",
    "github_write",
    "library_docs",
    "list_files",
    "memory_orchestrator",
    "read_file",
    "repo_docs",
    "search_amazon",
    "search_my_notes",
    "skills_list",
    "skill_view",
    "web_extract",
    "web_extract_pages",
    "web_research",
    "web_search",
    "x_agent",
}
CORE_TOOLSETS = {"browser", "filesystem", "github", "memory", "skills", "terminal", "web"}
_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "this",
    "to",
    "use",
    "with",
    "can", "could", "would", "should", "do", "does", "did", "you", "your", "u",
    "i", "me", "my", "we", "our", "what", "which", "who", "how", "help", "please",
}


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    config = SkillConfigStore(SKILLS_PATH / "config.yaml")
    external_dirs = [Path(os.path.expandvars(os.path.expanduser(str(path)))) for path in config.get_option("external_dirs", []) or []]
    with get_plugin_registry().read_snapshot():
        plugin_skill_roots = get_plugin_registry().skill_roots()
    return SkillRegistry(
        local_root=SKILLS_PATH / "packages",
        external_dirs=external_dirs,
        owned_external_dirs=plugin_skill_roots,
        available_tools=set(CORE_TOOL_NAMES),
        available_toolsets=set(CORE_TOOLSETS),
    )


def build_skill_index_block(
    registry: SkillRegistry | None = None, *, category: str = "",
    excluded_skills: set[str] | frozenset[str] = frozenset(),
) -> str:
    active_registry = registry or get_skill_registry()
    entries = [entry for entry in active_registry.list_skills()
               if entry.name not in excluded_skills and (not category or entry.category == category)]
    if not entries:
        return ""
    lines = [
        "## Available Skills",
        "Use matching skill instructions for the current task; load the body or relative support files with skill_view on demand. Skills do not grant tools or permissions.",
    ]
    for entry in entries:
        description = " ".join(entry.description.split())
        lines.append(f"- {entry.name} [{entry.category}]: {description[:200]}")
    return "\n".join(lines)


def build_skill_activation_block(
    query: str,
    registry: SkillRegistry | None = None,
    *,
    excluded_skills: set[str] | frozenset[str] = frozenset(),
    max_skills: int = 3,
    max_chars: int = 12_000,
) -> str:
    normalized_query = " ".join(_WORD.findall(query.casefold()))
    query_tokens = set(normalized_query.split()) - _STOP_WORDS
    if not query_tokens:
        return ""

    active_registry = registry or get_skill_registry()
    ranked: list[tuple[int, str, str]] = []
    for package in active_registry.list_packages():
        if package.metadata.name in excluded_skills:
            continue
        vellum = package.metadata.metadata.vellum
        negative = [_normalize_phrase(value) for value in vellum.negative_trigger]
        if any(value and value in normalized_query for value in negative):
            continue

        positive = [
            _normalize_phrase(value)
            for value in [*vellum.trigger, *package.metadata.metadata.hermes.tags]
        ]
        explicit_matches = [value for value in positive if value and value in normalized_query]
        if explicit_matches:
            score = 100 + sum(len(value.split()) for value in explicit_matches)
        else:
            if vellum.trigger_only:
                continue
            skill_tokens = (
                set(_WORD.findall(package.metadata.name.casefold()))
                | set(_WORD.findall(package.metadata.description.casefold()))
            ) - _STOP_WORDS
            overlap = query_tokens & skill_tokens
            # One generic description word must not preload a whole skill.
            name_tokens = set(_WORD.findall(package.metadata.name.casefold())) - _STOP_WORDS
            if not (overlap & name_tokens):
                continue
            score = len(overlap)

        ranked.append((score, package.metadata.name, package.body.strip()))

    if not ranked:
        return ""

    sections = ["## Activated Vellum Skills"]
    for _, name, body in sorted(ranked, key=lambda item: (-item[0], item[1]))[:max_skills]:
        section = f"### {name}\n{body}"
        projected = "\n\n".join([*sections, section])
        if len(projected) > max_chars:
            continue
        sections.append(section)
        from agent.skills.usage_intelligence import record_current_activation
        record_current_activation(name, source="prompt_activation")
    return "\n\n".join(sections) if len(sections) > 1 else ""


def _normalize_phrase(value: str) -> str:
    return " ".join(_WORD.findall(str(value).casefold()))


def reset_skill_registry() -> None:
    get_skill_registry.cache_clear()
