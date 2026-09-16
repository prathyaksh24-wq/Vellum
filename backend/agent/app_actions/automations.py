"""Typed App Actions over the canonical automation store and runner."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Lock
from typing import Any, Awaitable, Callable

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.automations.store import AutomationStore
from agent.automations.validation import (
    parse_schedule_expression,
    validate_destination,
    validate_model_profile,
    validate_notifications_level,
)
from agent.tools.registry import CapabilityAccess


AUTOMATION_CREATE_ACTION_ID = "automation.create"
AUTOMATION_UPDATE_ACTION_ID = "automation.update"
AUTOMATION_PAUSE_ACTION_ID = "automation.pause"
AUTOMATION_RESUME_ACTION_ID = "automation.resume"
AUTOMATION_RUN_ACTION_ID = "automation.run"
AUTOMATION_HISTORY_ACTION_ID = "automation.history"
AUTOMATION_REMOVE_ACTION_ID = "automation.remove"

AUTOMATION_ACTION_IDS = frozenset({
    AUTOMATION_CREATE_ACTION_ID,
    AUTOMATION_UPDATE_ACTION_ID,
    AUTOMATION_PAUSE_ACTION_ID,
    AUTOMATION_RESUME_ACTION_ID,
    AUTOMATION_RUN_ACTION_ID,
    AUTOMATION_HISTORY_ACTION_ID,
    AUTOMATION_REMOVE_ACTION_ID,
})


class AutomationActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


StoreProvider = Callable[[], AutomationStore]
SchedulerAvailable = Callable[[], bool]
MutationNotifier = Callable[[str], Any]
AutomationRunner = Callable[[dict[str, Any], AutomationStore], Awaitable[dict[str, Any]]]


def _default_store_provider() -> AutomationStore:
    from agent.automations.api import get_store

    return get_store()


def _default_scheduler_available() -> bool:
    from agent.automations.api import mutation_hook_available

    return mutation_hook_available()


def _default_mutation_notifier(automation_id: str) -> None:
    from agent.automations.api import notify_mutation

    notify_mutation(automation_id, required=True)


def _default_runner(automation: dict[str, Any], store: AutomationStore) -> Awaitable[dict[str, Any]]:
    from agent.automations.runner import run_automation_now

    return run_automation_now(automation, store)


class AutomationActionService:
    """Validate and execute automation actions through existing runtime owners."""

    def __init__(
        self,
        *,
        store_provider: StoreProvider | None = None,
        scheduler_available: SchedulerAvailable | None = None,
        mutation_notifier: MutationNotifier | None = None,
        runner: AutomationRunner | None = None,
    ) -> None:
        self._store_provider = store_provider or _default_store_provider
        self._scheduler_available = scheduler_available or _default_scheduler_available
        self._mutation_notifier = mutation_notifier or _default_mutation_notifier
        self._runner = runner or _default_runner
        self._run_locks: dict[str, Lock] = {}
        self._run_locks_guard = Lock()

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
        *,
        confirmed: bool = False,
        confirmation_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._execute(
                action_id,
                arguments,
                confirmed=confirmed,
                confirmation_binding=confirmation_binding,
            )
        except AutomationActionError:
            raise
        except (TypeError, ValueError) as exc:
            raise AutomationActionError("INVALID_ACTION_ARGUMENTS", str(exc)) from exc

    def _execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool,
        confirmation_binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if action_id == AUTOMATION_CREATE_ACTION_ID:
            return self._create(arguments)
        if action_id == AUTOMATION_UPDATE_ACTION_ID:
            return self._update(arguments)
        if action_id == AUTOMATION_PAUSE_ACTION_ID:
            return self._set_state(arguments, "paused")
        if action_id == AUTOMATION_RESUME_ACTION_ID:
            return self._set_state(arguments, "active")
        if action_id == AUTOMATION_HISTORY_ACTION_ID:
            return self._history(arguments)
        if action_id in {AUTOMATION_RUN_ACTION_ID, AUTOMATION_REMOVE_ACTION_ID}:
            return self._confirmed_operation(
                action_id,
                arguments,
                confirmed=confirmed,
                confirmation_binding=confirmation_binding,
            )
        raise AutomationActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    def _create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        fields = self._create_fields(arguments)
        self._require_scheduler()
        store = self._store_provider()
        record = store.create(**fields)
        self._notify(record["id"])
        return self._automation_result(record, message=f"Created automation {record['name']}.")

    def _update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        store = self._store_provider()
        current = self._resolve(store, arguments)
        fields = self._update_fields(arguments)
        if not fields:
            raise AutomationActionError("INVALID_ACTION_ARGUMENTS", "No automation changes were provided.")
        self._require_scheduler()
        try:
            updated = store.update(current["id"], **fields)
        except ValueError as exc:
            raise AutomationActionError("AUTOMATION_UPDATE_FAILED", str(exc)) from exc
        self._notify(updated["id"])
        return self._automation_result(updated, message=f"Updated automation {updated['name']}.")

    def _set_state(self, arguments: dict[str, Any], state: str) -> dict[str, Any]:
        store = self._store_provider()
        current = self._resolve(store, arguments)
        self._require_scheduler()
        if current.get("state") == state:
            verb = "paused" if state == "paused" else "active"
            return self._automation_result(current, changed=False, message=f"{current['name']} is already {verb}.")
        updated = store.update(current["id"], state=state)
        self._notify(updated["id"])
        verb = "Paused" if state == "paused" else "Resumed"
        return self._automation_result(updated, message=f"{verb} automation {updated['name']}.")

    def _history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        store = self._store_provider()
        record = self._resolve(store, arguments)
        runs = store.runs(record["id"])
        return {
            "changed": False,
            "automation": record,
            "runs": runs,
            "_target_kind": "automation",
            "_target_id": record["id"],
            "_message": f"{record['name']} has {len(runs)} recorded run{'s' if len(runs) != 1 else ''}.",
        }

    def _confirmed_operation(
        self,
        action_id: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool,
        confirmation_binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        store = self._store_provider()
        record = self._resolve(store, arguments)
        if action_id == AUTOMATION_REMOVE_ACTION_ID:
            self._require_scheduler()
        binding = self._binding(record)
        review = {
            "id": record["id"],
            "name": record["name"],
            "builtin": bool(record.get("builtin")),
            "state": record.get("state"),
        }
        if not confirmed:
            operation = "reset" if record.get("builtin") and action_id == AUTOMATION_REMOVE_ACTION_ID else (
                "remove" if action_id == AUTOMATION_REMOVE_ACTION_ID else "run"
            )
            return {
                "changed": False,
                "automation_review": {**review, "operation": operation},
                "_confirmation_binding": binding,
                "_target_kind": "automation",
                "_target_id": record["id"],
                "_message": f"Confirm {operation} for automation {record['name']}.",
            }
        if confirmation_binding != binding:
            raise AutomationActionError(
                "STALE_ACTION_TARGET",
                "The automation changed before this operation was confirmed.",
            )
        if action_id == AUTOMATION_REMOVE_ACTION_ID:
            return self._remove(store, record)
        return self._run(store, record)

    def _remove(self, store: AutomationStore, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("builtin"):
            from agent.automations.builtins import reset_builtin

            restored = reset_builtin(store, record)
            self._notify(record["id"])
            return self._automation_result(
                restored,
                message=f"Reset built-in automation {record['name']}.",
                extra={"restored": True},
            )
        store.remove(record["id"])
        self._notify(record["id"])
        return {
            "changed": True,
            "removed": record["id"],
            "_target_kind": "automation",
            "_target_id": record["id"],
            "_message": f"Removed automation {record['name']}.",
        }

    def _run(self, store: AutomationStore, record: dict[str, Any]) -> dict[str, Any]:
        lock = self._run_lock(record["id"])
        if not lock.acquire(blocking=False):
            raise AutomationActionError("AUTOMATION_BUSY", f"{record['name']} is already running.", unavailable=True)
        try:
            current = store.get(record["id"])
            if any(run.get("status") == "running" for run in current.get("run_history", [])):
                raise AutomationActionError("AUTOMATION_BUSY", f"{record['name']} is already running.", unavailable=True)
            try:
                run = self._run_awaitable(lambda: self._runner(current, store))
            except AutomationActionError:
                raise
            except Exception as exc:
                raise AutomationActionError("AUTOMATION_RUN_FAILED", "The automation could not be run.") from exc
            updated = store.get(record["id"])
        finally:
            lock.release()
        return self._automation_result(
            updated,
            message=f"Ran automation {record['name']}: {run.get('status', 'complete')}.",
            extra={"run": run},
        )

    def _create_fields(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = self._required_text(arguments, "name")
        instructions = self._required_text(arguments, "instructions")
        schedule = parse_schedule_expression(self._required_text(arguments, "schedule"))
        destination = self._destination(arguments.get("destination"))
        model_profile = self._model_profile(arguments.get("model_profile"))
        permission = self._permission(arguments.get("permission"))
        notifications = self._notifications(arguments.get("notifications"))
        return {
            "name": name,
            "description": self._optional_text(arguments.get("description")),
            "instructions": instructions,
            "schedule": schedule,
            "destination": destination,
            "project_id": self._project_id(arguments.get("project_id")),
            "model_profile": model_profile,
            "permission": permission,
            "notifications": notifications,
        }

    def _update_fields(self, arguments: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if "name" in arguments:
            fields["name"] = self._required_text(arguments, "name")
        if "description" in arguments:
            fields["description"] = self._optional_text(arguments.get("description"))
        if "instructions" in arguments:
            fields["instructions"] = self._required_text(arguments, "instructions")
        if "schedule" in arguments:
            fields["schedule"] = parse_schedule_expression(self._required_text(arguments, "schedule"))
        if "destination" in arguments:
            fields["destination"] = self._destination(arguments.get("destination"))
        if "project_id" in arguments:
            fields["project_id"] = self._project_id(arguments.get("project_id"))
        if "model_profile" in arguments:
            fields["model_profile"] = self._model_profile(arguments.get("model_profile"))
        if "permission" in arguments:
            fields["permission"] = self._permission(arguments.get("permission"))
        if "notifications" in arguments:
            fields["notifications"] = self._notifications(arguments.get("notifications"))
        return fields

    @staticmethod
    def _required_text(arguments: dict[str, Any], key: str) -> str:
        value = str(arguments.get(key) or "").strip()
        if not value:
            raise AutomationActionError("INVALID_ACTION_ARGUMENTS", f"{key} is required.")
        return value

    @staticmethod
    def _optional_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _project_id(value: Any) -> str | None:
        project_id = str(value or "").strip()
        return project_id or None

    @staticmethod
    def _object(value: Any, label: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise AutomationActionError("INVALID_ACTION_ARGUMENTS", f"{label} must be an object.")
        return dict(value)

    def _destination(self, value: Any) -> dict[str, Any]:
        destination = self._object(value, "destination")
        return validate_destination(
            str(destination.get("kind") or "new_chat"),
            str(destination.get("thread_id") or "").strip() or None,
        )

    def _model_profile(self, value: Any) -> dict[str, Any]:
        profile = self._object(value, "model_profile")
        return validate_model_profile(
            tier=str(profile.get("tier") or "").strip() or None,
            model=str(profile.get("model") or "").strip() or None,
            reasoning_mode=str(profile.get("reasoning_mode") or "").strip() or None,
        )

    def _permission(self, value: Any) -> dict[str, bool]:
        permission = self._object(value, "permission")
        full_access = permission.get("full_access", False)
        if not isinstance(full_access, bool):
            raise AutomationActionError("INVALID_ACTION_ARGUMENTS", "permission.full_access must be true or false.")
        return {"full_access": full_access}

    def _notifications(self, value: Any) -> dict[str, str]:
        notifications = self._object(value, "notifications")
        return validate_notifications_level(str(notifications.get("level") or "all"))

    @staticmethod
    def _resolve(store: AutomationStore, arguments: dict[str, Any]) -> dict[str, Any]:
        automation_id = str(arguments.get("automation_id") or "").strip()
        reference = str(arguments.get("reference") or "").strip()
        if automation_id:
            try:
                return store.get(automation_id)
            except ValueError as exc:
                raise AutomationActionError("AUTOMATION_NOT_FOUND", str(exc), unavailable=True) from exc
        if not reference:
            raise AutomationActionError("INVALID_ACTION_ARGUMENTS", "An automation id or name is required.")
        matches = [record for record in store.list() if str(record.get("name") or "").casefold() == reference.casefold()]
        if len(matches) != 1:
            message = f"Automation {reference} was not found." if not matches else f"Automation name {reference} is ambiguous."
            raise AutomationActionError("AUTOMATION_NOT_FOUND", message, unavailable=True)
        return matches[0]

    def _require_scheduler(self) -> None:
        try:
            available = bool(self._scheduler_available())
        except Exception as exc:
            raise AutomationActionError(
                "AUTOMATION_SCHEDULER_UNAVAILABLE",
                "The automation scheduler is unavailable.",
                unavailable=True,
            ) from exc
        if not available:
            raise AutomationActionError(
                "AUTOMATION_SCHEDULER_UNAVAILABLE",
                "The automation scheduler is unavailable.",
                unavailable=True,
            )

    def _notify(self, automation_id: str) -> None:
        try:
            self._mutation_notifier(automation_id)
        except Exception as exc:
            raise AutomationActionError(
                "AUTOMATION_SCHEDULER_UNAVAILABLE",
                "The automation scheduler could not apply the change.",
                unavailable=True,
            ) from exc

    def _run_lock(self, automation_id: str) -> Lock:
        with self._run_locks_guard:
            return self._run_locks.setdefault(automation_id, Lock())

    @staticmethod
    def _run_awaitable(factory: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(factory())
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="vellum-automation-run") as executor:
            return executor.submit(lambda: asyncio.run(factory())).result()

    @staticmethod
    def _binding(record: dict[str, Any]) -> dict[str, Any]:
        values = (
            str(record.get("id") or ""),
            str(record.get("updated_at") or ""),
            str(record.get("state") or ""),
            str(len(record.get("run_history") or [])),
        )
        return {
            "automation_id": values[0],
            "fingerprint": sha256("\n".join(values).encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _automation_result(
        record: dict[str, Any],
        *,
        message: str,
        changed: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "changed": changed,
            "automation": record,
            **(extra or {}),
            "_target_kind": "automation",
            "_target_id": record["id"],
            "_message": message,
        }


def automation_action_definitions() -> list[AppActionDefinition]:
    identity = {
        "automation_id": {"type": "string"},
        "reference": {"type": "string"},
    }
    destination = {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["new_chat", "existing_chat"]}, "thread_id": {"type": "string"}},
        "additionalProperties": False,
    }
    model_profile = {
        "type": "object",
        "properties": {"tier": {"type": "string", "enum": ["primary", "fast"]}, "model": {"type": "string"}, "reasoning_mode": {"type": "string"}},
        "additionalProperties": False,
    }
    editable = {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "instructions": {"type": "string"},
        "schedule": {"type": "string"},
        "destination": destination,
        "project_id": {"type": ["string", "null"]},
        "model_profile": model_profile,
        "permission": {"type": "object", "properties": {"full_access": {"type": "boolean"}}, "additionalProperties": False},
        "notifications": {"type": "object", "properties": {"level": {"type": "string", "enum": ["all", "important", "failures", "none"]}}, "additionalProperties": False},
    }
    specs = [
        (AUTOMATION_CREATE_ACTION_ID, "Create automation", "Create a validated scheduled reasoning task.", CapabilityAccess.WRITE, "none", editable, ["name", "instructions", "schedule"]),
        (AUTOMATION_UPDATE_ACTION_ID, "Update automation", "Update a scheduled reasoning task.", CapabilityAccess.WRITE, "none", {**identity, **editable}, []),
        (AUTOMATION_PAUSE_ACTION_ID, "Pause automation", "Pause future scheduled runs.", CapabilityAccess.WRITE, "none", identity, []),
        (AUTOMATION_RESUME_ACTION_ID, "Resume automation", "Resume future scheduled runs.", CapabilityAccess.WRITE, "none", identity, []),
        (AUTOMATION_RUN_ACTION_ID, "Run automation now", "Run a scheduled reasoning task immediately.", CapabilityAccess.EXTERNAL_WRITE, "operation_bound", identity, []),
        (AUTOMATION_HISTORY_ACTION_ID, "Inspect automation history", "Read the bounded run history for a scheduled reasoning task.", CapabilityAccess.READ, "none", identity, []),
        (AUTOMATION_REMOVE_ACTION_ID, "Remove automation", "Remove a scheduled task or reset a built-in task.", CapabilityAccess.DESTRUCTIVE, "operation_bound", identity, []),
    ]
    return [
        AppActionDefinition(
            id=action_id,
            version="1",
            owner="automations",
            title=title,
            description=description,
            scope="application",
            access_class=access.value,
            confirmation_rule=confirmation_rule,
            executor_location="server",
            supports_undo=False,
            idempotent=action_id in {AUTOMATION_PAUSE_ACTION_ID, AUTOMATION_RESUME_ACTION_ID, AUTOMATION_HISTORY_ACTION_ID},
            argument_schema={
                "type": "object",
                "properties": properties,
                **({"required": required} if required else {}),
                "additionalProperties": False,
            },
            result_schema={"type": "object", "required": ["changed"]},
            ui_reference="scheduled",
            audit_label=action_id,
        )
        for action_id, title, description, access, confirmation_rule, properties, required in specs
    ]
