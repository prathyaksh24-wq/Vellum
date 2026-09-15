"""App Action adapter over the canonical plugin and skill lifecycle owners."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.plugins.registry import PluginRegistry, PluginRegistryError
from agent.skills.manager import SkillMutationError
from agent.tools.registry import CapabilityAccess


PLUGIN_STATE_SET_ACTION_ID = "plugin.state.set"
SKILL_MUTATION_SUBMIT_ACTION_ID = "skill.mutation.submit"
SKILL_MUTATION_APPROVE_ACTION_ID = "skill.mutation.approve"
SKILL_MUTATION_REJECT_ACTION_ID = "skill.mutation.reject"
SKILL_UNINSTALL_ACTION_ID = "skill.uninstall"

LIFECYCLE_CONTROL_ACTION_IDS = frozenset({
    PLUGIN_STATE_SET_ACTION_ID,
    SKILL_MUTATION_SUBMIT_ACTION_ID,
    SKILL_MUTATION_APPROVE_ACTION_ID,
    SKILL_MUTATION_REJECT_ACTION_ID,
    SKILL_UNINSTALL_ACTION_ID,
})


class LifecycleControlError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


class PluginSkillActionService:
    """Translate App Actions into existing registry and mutation interfaces."""

    def __init__(
        self,
        *,
        plugin_registry: PluginRegistry,
        skill_surface_provider: Callable[[], Any],
        skill_hub_handler: Callable[[dict[str, Any]], dict[str, Any]],
        uninstall_handler: Callable[[str], dict[str, Any]],
        plugin_state_changed: Callable[[], None] | None = None,
    ) -> None:
        self.plugin_registry = plugin_registry
        self.skill_surface_provider = skill_surface_provider
        self.skill_hub_handler = skill_hub_handler
        self.uninstall_handler = uninstall_handler
        self.plugin_state_changed = plugin_state_changed or (lambda: None)

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            if action_id == PLUGIN_STATE_SET_ACTION_ID:
                return self._set_plugin_state(arguments)
            if action_id == SKILL_MUTATION_SUBMIT_ACTION_ID:
                return self._submit_skill_mutation(arguments)
            if action_id == SKILL_MUTATION_APPROVE_ACTION_ID:
                return self._resolve_skill_mutation(arguments, approve=True)
            if action_id == SKILL_MUTATION_REJECT_ACTION_ID:
                return self._resolve_skill_mutation(arguments, approve=False)
            if action_id == SKILL_UNINSTALL_ACTION_ID:
                if not confirmed:
                    raise LifecycleControlError("CONFIRMATION_REQUIRED", "Confirm skill removal.")
                return self._uninstall_skill(arguments)
        except LifecycleControlError:
            raise
        except KeyError as exc:
            raise LifecycleControlError("LIFECYCLE_TARGET_NOT_FOUND", "The requested plugin or skill was not found.", unavailable=True) from exc
        except (PluginRegistryError, SkillMutationError, OSError, ValueError) as exc:
            raise LifecycleControlError("LIFECYCLE_ACTION_FAILED", str(exc)) from exc
        raise LifecycleControlError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    def _set_plugin_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        plugin_id = _required_string(arguments, "plugin_id")
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise LifecycleControlError("INVALID_ACTION_ARGUMENTS", "Plugin enabled must be true or false.")
        previous = self.plugin_registry.is_enabled(plugin_id)
        plugin = self.plugin_registry.set_enabled(plugin_id, enabled)
        changed = previous != enabled
        if changed:
            self.plugin_state_changed()
        return {
            "changed": changed,
            "plugin": plugin,
            "_target_kind": "plugin",
            "_target_id": plugin_id,
            "_message": f"{plugin.get('name') or plugin_id} {'enabled' if enabled else 'disabled'}.",
        }

    def _submit_skill_mutation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = _required_string(arguments, "operation").casefold().replace("-", "_")
        name = str(arguments.get("name") or "").strip()
        if operation in {"install", "update", "import_local"}:
            payload = {
                "action": operation,
                "identifier": str(arguments.get("identifier") or "").strip(),
                "name": name,
                "category": str(arguments.get("category") or "uncategorized"),
                "force": arguments.get("force") is True,
                "confirm": False,
            }
            result = self.skill_hub_handler(payload)
            if result.get("ok") is False:
                raise LifecycleControlError("SKILL_MUTATION_FAILED", str(result.get("error") or "Skill mutation failed."))
        else:
            surface_action = {
                "enable": "restore",
                "disable": "archive",
                "archive": "archive",
                "restore": "restore",
                "remove": "delete",
            }.get(operation)
            if surface_action is None:
                raise LifecycleControlError("INVALID_ACTION_ARGUMENTS", f"Unsupported skill operation: {operation}")
            result = self.skill_surface_provider().action(surface_action, name=name)
        mutation = dict(result.get("result") or result)
        identity = str(mutation.get("identity") or mutation.get("name") or name)
        status = str(mutation.get("status") or "applied")
        return {
            "changed": True,
            "mutation": mutation,
            "_target_kind": "skill_mutation",
            "_target_id": str(mutation.get("id") or identity),
            "_message": f"{operation.replace('_', ' ').title()} for {identity or 'the skill'} is {status}.",
        }

    def _resolve_skill_mutation(self, arguments: dict[str, Any], *, approve: bool) -> dict[str, Any]:
        mutation_id = _required_string(arguments, "mutation_id")
        coordinator = self.skill_surface_provider().mutations
        result = coordinator.approve(mutation_id) if approve else coordinator.reject(mutation_id)
        identity = str(result.get("name") or result.get("identity") or mutation_id)
        return {
            "changed": True,
            "mutation": result,
            "_target_kind": "skill_mutation",
            "_target_id": mutation_id,
            "_message": f"Skill change for {identity} {'approved' if approve else 'rejected'}.",
        }

    def _uninstall_skill(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = _required_string(arguments, "name")
        result = self.uninstall_handler(name)
        if result.get("ok") is False:
            raise LifecycleControlError("SKILL_UNINSTALL_FAILED", str(result.get("error") or "Skill removal failed."))
        return {
            "changed": True,
            "mutation": result,
            "recoverable_snapshot": result.get("snapshot"),
            "_target_kind": "skill",
            "_target_id": name,
            "_message": f"{name} removed. A recovery snapshot was created.",
        }


def lifecycle_action_definitions() -> list[AppActionDefinition]:
    common = {
        "version": "1",
        "scope": "user",
        "access_class": CapabilityAccess.WRITE.value,
        "executor_location": "server",
        "supports_undo": False,
        "idempotent": False,
        "result_schema": {"type": "object", "required": ["changed"]},
    }
    return [
        AppActionDefinition(
            id=PLUGIN_STATE_SET_ACTION_ID,
            owner="plugin-registry",
            title="Set plugin state",
            description="Enable or disable a plugin through the canonical PluginRegistry.",
            confirmation_rule="none",
            argument_schema={
                "type": "object",
                "required": ["plugin_id", "enabled"],
                "additionalProperties": False,
                "properties": {"plugin_id": {"type": "string"}, "enabled": {"type": "boolean"}},
            },
            ui_reference="plugins",
            audit_label="plugin.state.set",
            **common,
        ),
        AppActionDefinition(
            id=SKILL_MUTATION_SUBMIT_ACTION_ID,
            owner="skill-mutation-coordinator",
            title="Stage a skill change",
            description="Stage install, update, import, archive, restore, enable, disable, or removal through the skill mutation coordinator.",
            confirmation_rule="existing_mutation_approval",
            argument_schema={
                "type": "object",
                "required": ["operation"],
                "properties": {
                    "operation": {"enum": ["install", "update", "import_local", "enable", "disable", "archive", "restore", "remove"]},
                    "name": {"type": "string"},
                    "identifier": {"type": "string"},
                    "category": {"type": "string"},
                    "force": {"type": "boolean"},
                },
            },
            ui_reference="skills",
            audit_label="skill.mutation.submit",
            **common,
        ),
        AppActionDefinition(
            id=SKILL_MUTATION_APPROVE_ACTION_ID,
            owner="skill-mutation-coordinator",
            title="Approve a skill change",
            description="Apply one reviewed pending skill mutation.",
            confirmation_rule="current_user_intent",
            argument_schema={"type": "object", "required": ["mutation_id"], "properties": {"mutation_id": {"type": "string"}}},
            ui_reference="skills.review",
            audit_label="skill.mutation.approve",
            **common,
        ),
        AppActionDefinition(
            id=SKILL_MUTATION_REJECT_ACTION_ID,
            owner="skill-mutation-coordinator",
            title="Reject a skill change",
            description="Reject one reviewed pending skill mutation.",
            confirmation_rule="current_user_intent",
            argument_schema={"type": "object", "required": ["mutation_id"], "properties": {"mutation_id": {"type": "string"}}},
            ui_reference="skills.review",
            audit_label="skill.mutation.reject",
            **common,
        ),
        AppActionDefinition(
            id=SKILL_UNINSTALL_ACTION_ID,
            owner="skill-mutation-coordinator",
            title="Uninstall a skill",
            description="Remove a hub-installed skill after operation-bound confirmation and create a recovery snapshot.",
            confirmation_rule="operation_bound",
            argument_schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
            ui_reference="skills",
            audit_label="skill.uninstall",
            **common,
        ),
    ]


def decode_skill_hub_result(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {"ok": False, "error": "Skill Hub returned an invalid result."}
    return dict(value or {})


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = str(arguments.get(key) or "").strip()
    if not value:
        raise LifecycleControlError("INVALID_ACTION_ARGUMENTS", f"{key.replace('_', ' ').title()} is required.")
    return value
