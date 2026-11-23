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
        # DeepSeek Harness' catalog limit: long enough to carry when-to-use guidance.
        lines.append(f"- {entry.name} [{entry.category}]: {description[:500]}")
    return "\n".join(lines)


def build_skill_catalog_reminder(
    registry: SkillRegistry | None = None, *,
    excluded_skills: set[str] | frozenset[str] = frozenset(),
) -> str:
    """The session skill catalog as DeepSeek Harness publishes it: a user-role
    system reminder naming each skill with its when-to-use description, and the
    rule to load a matching skill before taking task actions."""
    active_registry = registry or get_skill_registry()
    entries = [entry for entry in active_registry.list_skills() if entry.name not in excluded_skills]
    if not entries:
        return ""
    lines = [
        "<system-reminder>",
        "A skill is a reusable set of task-specific instructions. The following skills are available in this session:",
        "",
        "<available_skills>",
        *(f"- `{entry.name}`: {' '.join(entry.description.split())[:500]}" for entry in entries),
        "</available_skills>",
        "",
        "If the user names a skill, or the task clearly matches a skill's description, call the `skill_view` tool with "
        "the exact skill name before taking task actions. Load all applicable skills, then follow their full "
        "instructions. This catalog contains summaries only; do not infer or follow a skill's instructions until it "
        "has been loaded.",
        "A user may also invoke a skill directly; its instructions then appear in this conversation. Follow them, and "
        "do not call the `skill_view` tool again for that skill.",
        "</system-reminder>",
    ]
    return "\n".join(lines)


def build_skill_activation_block(
    query: str,
    registry: SkillRegistry | None = None,
    *,
    excluded_skills: set[str] | frozenset[str] = frozenset(),
    selected_skills: dict[str, str] | None = None,
    max_skills: int = 3,
    max_chars: int = 12_000,
    match_query: bool = True,
) -> str:
    """Skill bodies to place in the prompt for this turn.

    With ``match_query=False`` only the skills the user selected are included;
    the model loads any other skill itself with ``skill_view`` (ADR 0009).
    """
    normalized_query = " ".join(_WORD.findall(query.casefold()))
    query_tokens = set(normalized_query.split()) - _STOP_WORDS
    if not query_tokens and not selected_skills:
        return ""

    active_registry = registry or get_skill_registry()
    ranked: list[tuple[int, str, str]] = []
    for package in active_registry.list_packages():
        name = package.metadata.name
        if name in excluded_skills:
            continue
        if selected_skills is not None and selected_skills.get(name) == (package.owner_plugin or ""):
            ranked.append((1000, name, package.body.strip()))
            continue
        if not match_query:
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


def skills_named_in(
    query: str,
    registry: SkillRegistry | None = None,
    *,
    excluded_skills: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Installed skills the user picked by name in their message.

    Naming a skill as a skill ("my naval-almanack skill", "the skill
    research", "/research", "`research`") is the user's own choice, like a slash
    invocation, so the skill is loaded for them. A bare word that happens to
    equal a skill name is not a choice; the model decides from the catalog.
    """
    text = str(query or "")
    if not text.strip():
        return {}
    chosen: dict[str, str] = {}
    for entry in (registry or get_skill_registry()).list_skills():
        name = entry.name
        if name in excluded_skills:
            continue
        escaped = re.escape(name)
        named = re.search(
            rf"(?<![\w-])(?:{escaped}\s+skill\b|skills?\s+(?:named\s+|called\s+)?[`'\"]?{escaped}(?![\w-])|/{escaped}(?![\w-])|`{escaped}`)",
            text, re.IGNORECASE)
        if named:
            chosen[name] = entry.owner_plugin or ""
    return chosen


def _normalize_phrase(value: str) -> str:
    return " ".join(_WORD.findall(str(value).casefold()))


def reset_skill_registry() -> None:
    get_skill_registry.cache_clear()
