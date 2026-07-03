from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.skills import SkillManager, SkillMutationError, build_learn_prompt
from agent.skills.runtime import SKILLS_PATH


_MANAGER: SkillManager | None = None


def _manager() -> SkillManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = SkillManager(SKILLS_PATH)
    return _MANAGER


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


@tool
def skill_manage(
    action: str,
    name: str = "",
    skill_md: str = "",
    path: str = "",
    content: str = "",
    old_text: str = "",
    new_text: str = "",
    category: str = "uncategorized",
    origin: str = "foreground",
    confirm: bool = False,
) -> str:
    """Create or mutate a local skill package. Every mutation requires confirm=true."""
    normalized = action.strip().casefold().replace("-", "_")
    if origin != "foreground":
        return _json({"ok": False, "error": "background_review origin is reserved for the background review path"})
    manager = _manager()
    try:
        if normalized == "create":
            return _json(
                manager.create(
                    skill_md,
                    category=category,
                    origin="foreground",
                    confirm=confirm,
                )
            )
        if normalized == "patch":
            return _json(manager.patch(name, old_text, new_text, confirm=confirm))
        if normalized == "edit":
            return _json(manager.edit(name, skill_md, confirm=confirm))
        if normalized == "write_file":
            return _json(manager.write_file(name, path, content, confirm=confirm))
        if normalized == "remove_file":
            return _json(manager.remove_file(name, path, confirm=confirm))
        if normalized == "archive":
            return _json(manager.archive(name, confirm=confirm))
        if normalized == "restore":
            return _json(manager.restore(name, confirm=confirm))
        if normalized == "delete":
            return _json(manager.delete(name, confirm=confirm))
        return _json({"ok": False, "error": f"Unsupported skill action: {normalized}"})
    except (SkillMutationError, ValueError, OSError) as exc:
        return _json({"ok": False, "error": str(exc)})


@tool
def skill_learn(source: str, focus: str = "") -> str:
    """Build standards-guided instructions for learning a reusable skill from supplied sources."""
    try:
        return _json({"ok": True, "prompt": build_learn_prompt(source, focus)})
    except ValueError as exc:
        return _json({"ok": False, "error": str(exc)})
