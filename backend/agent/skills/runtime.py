from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agent.skills.registry import SkillRegistry


SKILLS_PATH = Path(__file__).resolve().parents[3] / ".skills"
CORE_TOOL_NAMES = {
    "append_to_note",
    "browser_action",
    "browser_click",
    "browser_close",
    "browser_hover",
    "browser_navigate",
    "browser_press_key",
    "browser_select_option",
    "browser_snapshot",
    "browser_tabs",
    "browser_type",
    "browser_wait",
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
    "obsidian_api",
    "read_file",
    "repo_docs",
    "search_amazon",
    "search_my_notes",
    "skills_list",
    "skill_view",
    "web_extract",
    "web_research",
    "web_search",
    "x_action",
}
CORE_TOOLSETS = {"browser", "filesystem", "github", "memory", "skills", "terminal", "web"}


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    return SkillRegistry(
        local_root=SKILLS_PATH / "packages",
        available_tools=set(CORE_TOOL_NAMES),
        available_toolsets=set(CORE_TOOLSETS),
    )


def build_skill_index_block(registry: SkillRegistry | None = None) -> str:
    active_registry = registry or get_skill_registry()
    entries = active_registry.list_skills()
    if not entries:
        return ""
    lines = [
        "## Available Skills",
        "Load a skill with skill_view only when its description matches the current task.",
    ]
    for entry in entries:
        lines.append(f"- {entry.name} [{entry.category}]: {entry.description}")
    return "\n".join(lines)
