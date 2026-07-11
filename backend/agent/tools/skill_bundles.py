from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.skills import SkillBundleError, SkillBundleStore, get_skill_registry
from agent.skills.runtime import SKILLS_PATH
from agent.skills.usage_intelligence import record_current_activation


_STORE: SkillBundleStore | None = None


def _store() -> SkillBundleStore:
    global _STORE
    if _STORE is None:
        _STORE = SkillBundleStore(SKILLS_PATH, get_skill_registry())
    return _STORE


@tool
def skill_bundles(
    action: str,
    name: str = "",
    skills: list[str] | None = None,
    description: str = "",
    instruction: str = "",
    confirm: bool = False,
) -> str:
    """List, inspect, create, delete, or load a bundle of installed skills."""
    normalized = action.strip().casefold().replace("-", "_")
    store = _store()
    try:
        if normalized == "list":
            result = {"ok": True, "bundles": store.list()}
        elif normalized == "show":
            result = {"ok": True, "bundle": store.show(name)}
        elif normalized == "load":
            result = store.load(name)
            for member in result.get("skills", []):
                record_current_activation(member, source=f"bundle:{name}")
        elif normalized == "create":
            result = store.create(
                name,
                skills or [],
                description=description,
                instruction=instruction,
                confirm=confirm,
            )
        elif normalized == "delete":
            result = store.delete(name, confirm=confirm)
        else:
            result = {"ok": False, "error": f"Unsupported bundle action: {normalized}"}
    except (SkillBundleError, OSError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)
