from __future__ import annotations

import json
import os
from pathlib import PurePosixPath, PureWindowsPath

from langchain_core.tools import tool

from agent.skills import HubLockFile, SkillCatalog, SkillConfigStore, SkillPackageError, SkillUsageStore, get_skill_registry
from agent.skills.runtime import SKILLS_PATH
from agent.skills.usage_intelligence import record_current_activation
from agent.profiles.policy import get_active_profile_policy


_CONFIG: SkillConfigStore | None = None
_USAGE: SkillUsageStore | None = None


def _config_store() -> SkillConfigStore:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = SkillConfigStore(SKILLS_PATH / "config.yaml")
    return _CONFIG


def _usage_store() -> SkillUsageStore:
    global _USAGE
    if _USAGE is None:
        _USAGE = SkillUsageStore(SKILLS_PATH)
    return _USAGE


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _visible_skill_names(registry=None) -> set[str]:
    policy = get_active_profile_policy()
    if policy is not None:
        return set(policy.allowed_skills)

    registry = registry or get_skill_registry()
    available = {entry.name for entry in registry.list_skills(include_unavailable=True)}
    try:
        from agent.master.live_runtime import get_agent_catalog

        specialist_owned = get_agent_catalog().specialist_skill_ids()
    except Exception:
        specialist_owned = frozenset()
    return available - set(specialist_owned)


@tool
def skills_list(category: str = "", include_unavailable: bool = False) -> str:
    """List installed skills using compact metadata only."""
    registry = get_skill_registry()
    entries = registry.list_skills(include_unavailable=include_unavailable)
    visible = _visible_skill_names(registry)
    skills = []
    for entry in entries:
        if entry.name not in visible:
            continue
        if category and entry.category.casefold() != category.casefold():
            continue
        item = {
            "name": entry.name,
            "description": entry.description,
            "category": entry.category,
            "available": entry.available,
        }
        if entry.unavailable_reason:
            item["unavailable_reason"] = entry.unavailable_reason
        skills.append(item)
    return _json({"skills": skills})


@tool
def skills_history(since: str = "", until: str = "", action: str = "", limit: int = 100) -> str:
    """List immutable skill lifecycle events, including removed skills."""
    catalog = SkillCatalog(SKILLS_PATH)
    catalog.backfill_events()
    visible = _visible_skill_names()
    events = catalog.events(since=since, until=until, event=action, limit=limit)
    events = [item for item in events if not item.get("skill_name") or item.get("skill_name") in visible]
    return _json({"events": events})


@tool
def skill_view(name: str, path: str = "") -> str:
    """Load a skill's full instructions or one relative support file."""
    registry = get_skill_registry()
    if name not in _visible_skill_names(registry):
        return _json({"ok": False, "error": "Skill not found or unavailable to this agent."})
    try:
        if path:
            content = registry.view_file(name, path)
            if HubLockFile(SKILLS_PATH).get(name) is None:
                _usage_store().increment_view(name)
            return _json({"name": name, "path": path, "content": content})
        package = registry.view(name)
    except KeyError:
        return _json({"ok": False, "error": f"Skill not found: {name}"})
    except SkillPackageError as exc:
        return _json({"ok": False, "error": str(exc)})
    if HubLockFile(SKILLS_PATH).get(name) is None:
        _usage_store().increment_view(name)
        _usage_store().increment_use(name)
    record_current_activation(name, source="skill_view")
    resolved = _config_store().resolve(package)
    safe_values = {key: _safe_config_value(key, value) for key, value in resolved["values"].items()}
    missing_environment = [
        requirement.name
        for requirement in package.metadata.required_environment_variables
        if not os.environ.get(requirement.name)
    ]
    credential_base = package.source_root.parent
    missing_credentials = [
        requirement.path
        for requirement in package.metadata.required_credential_files
        if not (credential_base / requirement.path).is_file()
    ]
    return _json(
        {
            "name": package.metadata.name,
            "description": package.metadata.description,
            "category": package.metadata.metadata.hermes.category,
            "metadata": _safe_metadata(package.metadata.model_dump(mode="json", exclude_none=True)),
            "content": package.body,
            "resolved_config": safe_values,
            "setup_needed": {
                "environment_variables": missing_environment,
                "credential_files": missing_credentials,
                "config_keys": resolved["missing"],
            },
        }
    )


def _safe_metadata(metadata: dict) -> dict:
    config = metadata.get("metadata", {}).get("hermes", {}).get("config", [])
    for setting in config:
        key = str(setting.get("key") or "")
        if "default" in setting:
            setting["default"] = _safe_config_value(key, setting["default"])
    return metadata


def _safe_config_value(key: str, value):
    if not isinstance(value, str):
        return value
    normalized_key = key.casefold()
    looks_like_path_key = normalized_key.endswith((".path", "_path", ".dir", "_dir", ".directory"))
    looks_absolute = PurePosixPath(value.replace("\\", "/")).is_absolute() or PureWindowsPath(value).is_absolute()
    if looks_like_path_key or looks_absolute or value.startswith("~"):
        return "[LOCAL_PATH_CONFIGURED]"
    return value
