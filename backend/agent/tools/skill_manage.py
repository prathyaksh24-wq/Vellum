from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.skills import SkillLearningWorkflow, SkillMutationCoordinator, SkillMutationError
from agent.skills.runtime import SKILLS_PATH


_COORDINATOR: SkillMutationCoordinator | None = None
_LEARNING: SkillLearningWorkflow | None = None


def _coordinator() -> SkillMutationCoordinator:
    global _COORDINATOR
    if _COORDINATOR is None:
        _COORDINATOR = SkillMutationCoordinator(SKILLS_PATH)
    return _COORDINATOR


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _learning() -> SkillLearningWorkflow:
    global _LEARNING
    if _LEARNING is None:
        _LEARNING = SkillLearningWorkflow(SKILLS_PATH)
    return _LEARNING


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
    idempotency_key: str = "",
) -> str:
    """Stage a local skill mutation for approval, or apply it when approval gating is disabled."""
    normalized = action.strip().casefold().replace("-", "_")
    if origin != "foreground":
        return _json({"ok": False, "error": "background_review origin is reserved for the background review path"})
    coordinator = _coordinator()
    try:
        if normalized == "pending":
            return _json({"ok": True, "pending": coordinator.list_pending()})
        if normalized == "diff":
            return _json(coordinator.diff(name))
        if normalized == "approve":
            return _json(coordinator.approve(name))
        if normalized == "reject":
            return _json(coordinator.reject(name))
        if normalized == "approve_all":
            return _json(coordinator.approve_all())
        if normalized == "reject_all":
            return _json(coordinator.reject_all())
        if normalized == "approval_on":
            return _json(coordinator.set_write_approval(True))
        if normalized == "approval_off":
            return _json(coordinator.set_write_approval(False))
        if normalized in {"create", "patch", "edit", "write_file", "remove_file", "archive", "restore", "delete", "retire"}:
            return _json(
                coordinator.submit(
                    normalized,
                    name=name,
                    skill_md=skill_md,
                    path=path,
                    content=content,
                    old_text=old_text,
                    new_text=new_text,
                    category=category,
                    origin="foreground",
                    idempotency_key=idempotency_key or None,
                )
            )
        return _json({"ok": False, "error": f"Unsupported skill action: {normalized}"})
    except (SkillMutationError, ValueError, OSError) as exc:
        return _json({"ok": False, "error": str(exc)})


@tool
def skill_learn(source: str, focus: str = "") -> str:
    """Build standards-guided instructions for learning a reusable skill from supplied sources."""
    try:
        return _json(_learning().compose(source, focus))
    except ValueError as exc:
        return _json({"ok": False, "error": str(exc)})
