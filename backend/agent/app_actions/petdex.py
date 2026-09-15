"""Device-local Petdex actions and versioned client patches."""

from __future__ import annotations

from typing import Any

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.tools.registry import CapabilityAccess


PETDEX_INSTALL_ACTION_ID = "petdex.install"
PETDEX_REMOVE_ACTION_ID = "petdex.remove"
PETDEX_ACTIVE_SET_ACTION_ID = "petdex.active.set"
PETDEX_VISIBILITY_SET_ACTION_ID = "petdex.visibility.set"
PETDEX_SIZE_SET_ACTION_ID = "petdex.size.set"
PETDEX_POSITION_SET_ACTION_ID = "petdex.position.set"

PETDEX_ACTION_IDS = frozenset({
    PETDEX_INSTALL_ACTION_ID,
    PETDEX_REMOVE_ACTION_ID,
    PETDEX_ACTIVE_SET_ACTION_ID,
    PETDEX_VISIBILITY_SET_ACTION_ID,
    PETDEX_SIZE_SET_ACTION_ID,
    PETDEX_POSITION_SET_ACTION_ID,
})


class PetdexActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


def execute_petdex_action(
    action_id: str,
    arguments: dict[str, Any],
    context: AppActionContext,
) -> dict[str, Any]:
    current = _state(context.petdex)
    next_state = dict(current)
    message = "Petdex updated."

    if action_id == PETDEX_INSTALL_ACTION_ID:
        slug = _pet_slug(arguments, current)
        installed = list(current["installed"])
        if slug not in installed:
            installed.append(slug)
        next_state["installed"] = installed
        if not current["active"]:
            next_state["active"] = slug
        message = f"{slug} installed."
    elif action_id == PETDEX_REMOVE_ACTION_ID:
        slug = _required_string(arguments, "slug")
        installed = [item for item in current["installed"] if item != slug]
        next_state["installed"] = installed
        if current["active"] == slug:
            next_state["active"] = installed[0] if installed else ""
        message = f"{slug} removed from Petdex."
    elif action_id == PETDEX_ACTIVE_SET_ACTION_ID:
        slug = _required_string(arguments, "slug")
        if slug not in current["installed"]:
            raise PetdexActionError("PET_NOT_INSTALLED", f"Install {slug} before selecting it.", unavailable=True)
        next_state["active"] = slug
        next_state["hidden"] = False
        message = f"{slug} selected and shown."
    elif action_id == PETDEX_VISIBILITY_SET_ACTION_ID:
        visible = arguments.get("visible")
        if not isinstance(visible, bool):
            raise PetdexActionError("INVALID_ACTION_ARGUMENTS", "Pet visibility must be true or false.")
        next_state["hidden"] = not visible
        message = f"Pet {'shown' if visible else 'hidden'}."
    elif action_id == PETDEX_SIZE_SET_ACTION_ID:
        size = str(arguments.get("size") or "").casefold()
        size = {"small": "sm", "medium": "md", "large": "lg"}.get(size, size)
        if size not in {"sm", "md", "lg"}:
            raise PetdexActionError("INVALID_ACTION_ARGUMENTS", "Pet size must be small, medium, or large.")
        next_state["size"] = size
        size_label = {"sm": "small", "md": "medium", "lg": "large"}[size]
        message = f"Pet size changed to {size_label}."
    elif action_id == PETDEX_POSITION_SET_ACTION_ID:
        anchor = str(arguments.get("anchor") or "").casefold().replace("_", "-").replace(" ", "-")
        if anchor:
            if anchor not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
                raise PetdexActionError("INVALID_ACTION_ARGUMENTS", "Pet position must be a supported corner.")
            next_state["position"] = {"anchor": anchor}
            message = f"Pet moved to the {anchor.replace('-', ' ')}."
        else:
            x, y = arguments.get("x"), arguments.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                raise PetdexActionError("INVALID_ACTION_ARGUMENTS", "Pet position requires numeric x and y coordinates.")
            next_state["position"] = {"x": max(0, round(x)), "y": max(0, round(y))}
            message = "Pet position saved."
    else:
        raise PetdexActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    changed = _mutable_state(next_state) != _mutable_state(current)
    revision = current["revision"] + (1 if changed else 0)
    next_state["revision"] = revision
    return {
        "changed": changed,
        "petdex_patch": {
            "version": 1,
            "base_revision": current["revision"],
            "revision": revision,
            "state": _mutable_state(next_state),
        },
        "_target_kind": "device_presentation",
        "_target_id": "petdex",
        "_message": message,
    }


def petdex_action_definitions() -> list[AppActionDefinition]:
    common = {
        "version": "1",
        "owner": "petdex",
        "scope": "device",
        "access_class": CapabilityAccess.WRITE.value,
        "confirmation_rule": "none",
        "executor_location": "client",
        "supports_undo": False,
        "idempotent": True,
        "result_schema": {"type": "object", "required": ["changed", "petdex_patch"]},
        "ui_reference": "petdex.companion",
    }
    return [
        _definition(PETDEX_INSTALL_ACTION_ID, "Install a Petdex pet", "Add a gallery pet to this device.", {"slug": {"type": "string"}}, "petdex.install", common),
        _definition(PETDEX_REMOVE_ACTION_ID, "Remove a Petdex pet", "Remove a pet from this device.", {"slug": {"type": "string"}}, "petdex.remove", common),
        _definition(PETDEX_ACTIVE_SET_ACTION_ID, "Select a Petdex pet", "Choose and show an installed pet.", {"slug": {"type": "string"}}, "petdex.active.set", common),
        _definition(PETDEX_VISIBILITY_SET_ACTION_ID, "Set pet visibility", "Show or hide the floating pet.", {"visible": {"type": "boolean"}}, "petdex.visibility.set", common),
        _definition(PETDEX_SIZE_SET_ACTION_ID, "Set pet size", "Set the floating pet size.", {"size": {"enum": ["sm", "md", "lg", "small", "medium", "large"]}}, "petdex.size.set", common),
        _definition(
            PETDEX_POSITION_SET_ACTION_ID,
            "Set pet position",
            "Move the floating pet to a supported corner or device coordinates.",
            {"anchor": {"enum": ["top-left", "top-right", "bottom-left", "bottom-right"]}, "x": {"type": "number"}, "y": {"type": "number"}},
            "petdex.position.set",
            common,
            required=[],
        ),
    ]


def _definition(
    action_id: str,
    title: str,
    description: str,
    properties: dict[str, Any],
    audit_label: str,
    common: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> AppActionDefinition:
    return AppActionDefinition(
        id=action_id,
        title=title,
        description=description,
        argument_schema={"type": "object", "required": required if required is not None else list(properties), "properties": properties},
        audit_label=audit_label,
        **common,
    )


def _state(raw: dict[str, Any]) -> dict[str, Any]:
    source = dict(raw or {})
    installed = [str(item).strip() for item in source.get("installed") or [] if str(item).strip()]
    available = [str(item).strip() for item in source.get("available") or [] if str(item).strip()]
    try:
        revision = max(0, int(source.get("revision") or 0))
    except (TypeError, ValueError):
        revision = 0
    return {
        "revision": revision,
        "installed": list(dict.fromkeys(installed)),
        "available": list(dict.fromkeys(available)),
        "active": str(source.get("active") or "").strip(),
        "hidden": bool(source.get("hidden", False)),
        "size": str(source.get("size") or "md"),
        "position": dict(source.get("position") or {}),
    }


def _pet_slug(arguments: dict[str, Any], state: dict[str, Any]) -> str:
    slug = _required_string(arguments, "slug")
    available = state["available"]
    if available and slug not in available:
        raise PetdexActionError("PET_UNAVAILABLE", f"{slug} is not in the current Petdex gallery.", unavailable=True)
    return slug


def _mutable_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state[key] for key in ("installed", "active", "hidden", "size", "position")}


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = str(arguments.get(key) or "").strip().casefold()
    if not value:
        raise PetdexActionError("INVALID_ACTION_ARGUMENTS", f"{key.title()} is required.")
    return value
