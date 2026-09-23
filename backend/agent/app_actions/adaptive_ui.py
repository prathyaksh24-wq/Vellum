"""Device-local Adaptive UI rules for the existing Workspace Layout owner."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4
from typing import Any

from agent.app_actions.models import (
    AdaptiveScope,
    AdaptiveUISignal,
    AdaptiveUIRule,
    AdaptiveUIState,
    AppActionContext,
    AppActionDefinition,
)
from agent.tools.registry import CapabilityAccess


RULE_CREATE = "ui.adaptive.rule.create"
RULE_LIST = "ui.adaptive.rule.list"
RULE_EXPLAIN = "ui.adaptive.rule.explain"
RULE_SET_ENABLED = "ui.adaptive.rule.set_enabled"
RULE_REMOVE = "ui.adaptive.rule.remove"
RULE_SUPPRESS = "ui.adaptive.rule.suppress"
RULE_APPLY = "ui.adaptive.apply"
ACTION_IDS = frozenset({
    RULE_CREATE, RULE_LIST, RULE_EXPLAIN, RULE_SET_ENABLED,
    RULE_REMOVE, RULE_SUPPRESS, RULE_APPLY,
})

# These fields are presentation only, reversible through Workspace Layout, and
# never include privacy, data, plugin lifecycle, or external action classes.
_FIELDS = {
    "workspace": frozenset({"theme"}),
    "sidebar": frozenset({"visible"}),
    "right-panel": frozenset({"visible"}),
    "composer": frozenset({"size"}),
    "composer.send": frozenset({"size", "label"}),
}
_MAX_RULES = 100
_MAX_SIGNALS = 200
_MAX_SUPPRESSIONS = 200


class AdaptiveUIError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_arguments(action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Reduce one allowlisted UI change to one stable rule target."""

    if action_id == "ui.sidebar.set":
        if set(arguments) - {"visible", "persistence"}:
            raise AdaptiveUIError("ADAPTIVE_ACTION_FORBIDDEN", "Only sidebar visibility can be learned from this action.")
        arguments = {"reference": "sidebar", **arguments}
    elif action_id != "ui.surface.configure":
        raise AdaptiveUIError("ADAPTIVE_ACTION_FORBIDDEN", "Only reversible presentation actions can be learned.")
    if arguments.get("persistence") == "session":
        raise AdaptiveUIError("ADAPTIVE_ACTION_FORBIDDEN", "Temporary interface changes cannot become rules.")
    reference = str(arguments.get("reference") or "")
    allowed = _FIELDS.get(reference)
    if not allowed:
        raise AdaptiveUIError("ADAPTIVE_ACTION_FORBIDDEN", "This interface surface cannot be learned.")
    if "location" in arguments or set(arguments) - {"reference", "visible", "properties", "persistence"}:
        raise AdaptiveUIError("ADAPTIVE_ACTION_FORBIDDEN", "Only allowlisted presentation fields can be learned.")
    properties = arguments.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise AdaptiveUIError("INVALID_ACTION_ARGUMENTS", "Presentation properties must be an object.")
    fields = (["visible"] if "visible" in arguments else []) + list(properties or {})
    if len(fields) != 1 or fields[0] not in allowed:
        raise AdaptiveUIError("ADAPTIVE_ACTION_FORBIDDEN", "A rule must change one allowlisted presentation field.")
    if fields[0] == "visible":
        if not isinstance(arguments["visible"], bool):
            raise AdaptiveUIError("INVALID_ACTION_ARGUMENTS", "Visibility must be true or false.")
        return {"reference": reference, "visible": arguments["visible"]}
    return {"reference": reference, "properties": {fields[0]: properties[fields[0]]}}


def signature(arguments: dict[str, Any]) -> str:
    serialized = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def inferred_scope(context: AppActionContext) -> tuple[AdaptiveScope, str]:
    if context.project_id:
        return "project", context.project_id
    if context.active_agent:
        return "agent", context.active_agent
    if context.window_id:
        return "window", context.window_id
    return "device", context.device_id


def scope_id(scope: AdaptiveScope, context: AppActionContext) -> str:
    return {
        "global": "",
        "device": context.device_id,
        "agent": context.active_agent,
        "project": context.project_id,
        "window": context.window_id,
    }[scope]


def matches(rule: AdaptiveUIRule, context: AppActionContext) -> bool:
    return rule.scope == "global" or (bool(rule.scope_id) and rule.scope_id == scope_id(rule.scope, context))


def state_patch(before: AdaptiveUIState, after: AdaptiveUIState) -> dict[str, Any]:
    after.revision = before.revision + 1
    return {
        "base_revision": before.revision,
        "revision": after.revision,
        "state": after.model_dump(mode="json"),
    }


def observation(
    context: AppActionContext,
    result: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """Count successful user customizations in their narrowest active context."""

    if (
        not result.get("changed")
        or result.get("persistence") == "session"
        or (context.source != "nlp" and not context.adaptive_learning_signal)
    ):
        return None, ""
    reference = str(result.get("target_reference") or "")
    current = result.get("presentation") or {}
    previous = result.get("previous_presentation") or {}
    changed_fields: dict[str, Any] = {}
    if current.get("visible") != previous.get("visible"):
        changed_fields["visible"] = current.get("visible")
    if current.get("location") != previous.get("location"):
        return None, ""
    for key, value in (current.get("properties") or {}).items():
        if value != (previous.get("properties") or {}).get(key):
            changed_fields[key] = value
    if len(changed_fields) != 1:
        return None, ""
    field, value = next(iter(changed_fields.items()))
    try:
        arguments = canonical_arguments(
            "ui.surface.configure",
            {"reference": reference, **({"visible": value} if field == "visible" else {"properties": {field: value}})},
        )
    except AdaptiveUIError:
        return None, ""
    key = signature(arguments)
    before = context.workspace_layout.adaptive_ui
    if key in before.suppressions:
        return None, key
    scope, identifier = inferred_scope(context)
    if any(rule.signature == key and rule.scope == scope and rule.scope_id == identifier for rule in before.rules):
        return None, key
    after = before.model_copy(deep=True)
    signal = next(
        (item for item in after.signals if item.signature == key and item.scope == scope and item.scope_id == identifier),
        None,
    )
    if signal is None:
        signal = AdaptiveUISignal(signature=key, arguments=arguments, scope=scope, scope_id=identifier)
        after.signals.append(signal)
    else:
        signal.count += 1
    if signal.count >= 3:
        after.signals.remove(signal)
        after.rules.append(AdaptiveUIRule(
            id=f"adaptive_{uuid4().hex}", signature=key, arguments=arguments,
            scope=scope, scope_id=identifier, origin="inferred", evidence_count=signal.count,
        ))
        local_contexts = {
            (rule.scope, rule.scope_id)
            for rule in after.rules
            if rule.signature == key and rule.origin == "inferred" and rule.scope != "global"
        }
        if len(local_contexts) >= 3 and not any(
            rule.signature == key and rule.scope == "global" for rule in after.rules
        ):
            after.rules.append(AdaptiveUIRule(
                id=f"adaptive_{uuid4().hex}", signature=key, arguments=arguments,
                scope="global", origin="inferred", evidence_count=len(local_contexts) * 3,
            ))
    after.rules = after.rules[-_MAX_RULES:]
    after.signals = after.signals[-_MAX_SIGNALS:]
    return state_patch(before, after), key


def create_rule(
    context: AppActionContext,
    rule_action_id: str,
    raw_arguments: dict[str, Any],
    scope: AdaptiveScope = "global",
) -> tuple[AdaptiveUIRule, dict[str, Any] | None]:
    arguments = canonical_arguments(rule_action_id, raw_arguments)
    identifier = scope_id(scope, context)
    if scope != "global" and not identifier:
        raise AdaptiveUIError("ADAPTIVE_CONTEXT_REQUIRED", f"No {scope} is active for this rule.")
    before = context.workspace_layout.adaptive_ui
    after = before.model_copy(deep=True)
    key = signature(arguments)
    existing = next(
        (rule for rule in after.rules if rule.signature == key and rule.scope == scope and rule.scope_id == identifier),
        None,
    )
    if existing is not None:
        if existing.enabled and not existing.suppressed and existing.origin == "explicit":
            return existing, None
        existing.origin = "explicit"
        existing.enabled = True
        existing.suppressed = False
        rule = existing
    else:
        rule = AdaptiveUIRule(
            id=f"adaptive_{uuid4().hex}", signature=key, arguments=arguments,
            scope=scope, scope_id=identifier, origin="explicit",
        )
        after.rules.append(rule)
    after.suppressions = [item for item in after.suppressions if item != key]
    after.rules = after.rules[-_MAX_RULES:]
    return rule, state_patch(before, after)


def find_rule(state: AdaptiveUIState, rule_id: str) -> AdaptiveUIRule:
    identifier = rule_id or state.last_rule_id
    rule = next((item for item in state.rules if item.id == identifier), None)
    if rule is None:
        raise AdaptiveUIError("ADAPTIVE_RULE_UNAVAILABLE", "That Adaptive UI rule is unavailable.")
    return rule


def update_rule(
    state: AdaptiveUIState,
    rule_id: str,
    *,
    enabled: bool | None = None,
    remove: bool = False,
    suppress: bool = False,
) -> tuple[AdaptiveUIRule, dict[str, Any] | None]:
    before = state
    after = before.model_copy(deep=True)
    rule = find_rule(after, rule_id)
    if remove:
        after.rules.remove(rule)
        if after.last_rule_id == rule.id:
            after.last_rule_id = ""
    elif suppress:
        after.suppressions = [*after.suppressions, rule.signature][-_MAX_SUPPRESSIONS:]
        after.signals = [item for item in after.signals if item.signature != rule.signature]
        for item in after.rules:
            if item.signature == rule.signature:
                item.suppressed = True
                item.enabled = False
    elif enabled is not None:
        rule.enabled = enabled
        if enabled:
            rule.suppressed = False
            after.suppressions = [item for item in after.suppressions if item != rule.signature]
    if after == before:
        return rule, None
    return rule, state_patch(before, after)


def suppress_signature(state: AdaptiveUIState, key: str) -> dict[str, Any] | None:
    if not key:
        return None
    before = state
    after = before.model_copy(deep=True)
    if key not in after.suppressions:
        after.suppressions = [*after.suppressions, key][-_MAX_SUPPRESSIONS:]
    after.signals = [item for item in after.signals if item.signature != key]
    for rule in after.rules:
        if rule.signature == key:
            rule.suppressed = True
            rule.enabled = False
    return None if after == before else state_patch(before, after)


def mark_applied(state: AdaptiveUIState, rule_id: str) -> tuple[bool, dict[str, Any]]:
    before = state
    after = before.model_copy(deep=True)
    rule = find_rule(after, rule_id)
    first_use = not rule.explained
    rule.explained = True
    after.last_rule_id = rule.id
    return first_use, state_patch(before, after)


def explain(rule: AdaptiveUIRule) -> str:
    change = rule.arguments
    value = change.get("visible") if "visible" in change else next(iter(change.get("properties", {}).values()), "")
    basis = "your explicit instruction" if rule.origin == "explicit" else f"{rule.evidence_count} matching changes"
    location = "all contexts" if rule.scope == "global" else f"this {rule.scope} ({rule.scope_id})"
    return f"{change['reference']} is set to {value} in {location} because of {basis}."


def action_definitions() -> list[AppActionDefinition]:
    rule_id = {"rule_id": {"type": "string"}}
    specs = (
        (RULE_CREATE, "Always use this presentation", CapabilityAccess.WRITE, {
            "rule_action_id": {"enum": ["ui.sidebar.set", "ui.surface.configure"]},
            "rule_arguments": {"type": "object"},
            "scope": {"enum": ["global", "device", "agent", "project", "window"]},
        }),
        (RULE_LIST, "List Adaptive UI rules", CapabilityAccess.READ, {}),
        (RULE_EXPLAIN, "Explain an Adaptive UI rule", CapabilityAccess.READ, rule_id),
        (RULE_SET_ENABLED, "Enable or disable an Adaptive UI rule", CapabilityAccess.WRITE, {
            **rule_id, "enabled": {"type": "boolean"},
        }),
        (RULE_REMOVE, "Remove an Adaptive UI rule", CapabilityAccess.WRITE, rule_id),
        (RULE_SUPPRESS, "Do not learn this UI preference", CapabilityAccess.WRITE, rule_id),
        (RULE_APPLY, "Apply a learned UI rule", CapabilityAccess.WRITE, rule_id),
    )
    return [AppActionDefinition(
        id=action_id,
        version="1",
        owner="workspace-layout",
        title=title,
        description="Manage local, inspectable rules for reversible interface presentation.",
        scope="device",
        access_class=access.value,
        confirmation_rule="none",
        executor_location="server_and_client",
        supports_undo=action_id == RULE_APPLY,
        idempotent=action_id != RULE_APPLY,
        argument_schema={"type": "object", "additionalProperties": False, "properties": properties},
        result_schema={"type": "object", "required": ["changed"], "properties": {"changed": {"type": "boolean"}}},
        ui_reference="settings",
        audit_label=action_id,
    ) for action_id, title, access, properties in specs]
