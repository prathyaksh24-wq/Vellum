from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.skills import SkillHub, SkillHubError, TapsManager, create_skill_source_router
from agent.skills.runtime import SKILLS_PATH


_HUB: SkillHub | None = None
_TAPS: TapsManager | None = None


def _hub() -> SkillHub:
    global _HUB
    if _HUB is None:
        _HUB = SkillHub(SKILLS_PATH, sources=create_skill_source_router())
    return _HUB


def _taps() -> TapsManager:
    global _TAPS
    if _TAPS is None:
        _TAPS = TapsManager(SKILLS_PATH)
    return _TAPS


@tool
def skill_hub(
    action: str,
    query: str = "",
    identifier: str = "",
    name: str = "",
    source: str = "all",
    category: str = "uncategorized",
    repo: str = "",
    path: str = "skills/",
    limit: int = 10,
    force: bool = False,
    confirm: bool = False,
) -> str:
    """Search, inspect, install, update, audit, uninstall, and manage taps for skills."""
    normalized = action.strip().casefold().replace("-", "_")
    try:
        if normalized in {"search", "browse"}:
            result = {"ok": True, "results": _hub().search(query, source_filter=source, limit=limit)}
        elif normalized == "inspect":
            result = {"ok": True, "skill": _hub().inspect(identifier)}
        elif normalized == "install":
            result = _hub().install(identifier, category=category, confirm=confirm, force=force)
        elif normalized == "list":
            result = {"ok": True, "skills": _hub().list_installed()}
        elif normalized == "check":
            result = {"ok": True, "update": _hub().check(name)}
        elif normalized == "update":
            result = _hub().update(name, confirm=confirm, force=force)
        elif normalized == "audit":
            result = {"ok": True, "audit": _hub().audit(name)}
        elif normalized == "uninstall":
            result = _hub().uninstall(name, confirm=confirm)
        elif normalized == "tap_list":
            result = {"ok": True, "taps": _taps().list()}
        elif normalized == "tap_add":
            result = _taps().add(repo, path=path, confirm=confirm)
        elif normalized == "tap_remove":
            result = _taps().remove(repo, confirm=confirm)
        else:
            result = {"ok": False, "error": f"Unsupported hub action: {normalized}"}
    except (SkillHubError, OSError, ValueError, KeyError) as exc:
        result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)
