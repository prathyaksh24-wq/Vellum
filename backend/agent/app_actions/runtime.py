"""Deep App Action Runtime shared by NLP and visible-control adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import secrets
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from agent.app_actions.models import (
    ActionAuthorization,
    ActionReceipt,
    ActionTarget,
    ActionUndo,
    AppActionCatalog,
    AppActionContext,
    AppActionDefinition,
    AppActionRequest,
    SurfacePresentation,
    UISurfaceDefinition,
)
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


SIDEBAR_ACTION_ID = "ui.sidebar.set"
SURFACE_ACTION_ID = "ui.surface.configure"
WORKSPACE_RESET_ACTION_ID = "ui.workspace.reset"
_UNDO_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class _UndoRecord:
    token: str
    action_id: str
    previous_arguments: dict[str, Any]
    target_reference: str
    expected_presentation: dict[str, Any]
    expected_revision: int
    expires_at: datetime


class SurfaceActionError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class InMemoryReceiptStore:
    """Process-local receipt state; device layout remains owned by the client."""

    def __init__(self) -> None:
        self._records: dict[str, _UndoRecord] = {}
        self._lock = Lock()

    def put(self, record: _UndoRecord) -> None:
        with self._lock:
            self._records[record.token] = record

    def get(self, token: str) -> _UndoRecord | None:
        with self._lock:
            return self._records.get(token)

    def remove(self, token: str) -> None:
        with self._lock:
            self._records.pop(token, None)


class AppActionRuntime:
    """Discover, authorize, dispatch, and undo semantic Vellum actions."""

    def __init__(
        self,
        *,
        receipt_store: InMemoryReceiptStore | None = None,
        clock: Callable[[], datetime] | None = None,
        receipt_id_factory: Callable[[], str] | None = None,
        undo_token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._receipt_store = receipt_store or InMemoryReceiptStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._receipt_id_factory = receipt_id_factory or (lambda: f"receipt_{uuid4().hex}")
        self._undo_token_factory = undo_token_factory or (lambda: secrets.token_urlsafe(24))
        self._surfaces = {surface.reference: surface for surface in self._surface_definitions()}
        self._definitions = {
            definition.id: definition
            for definition in (
                self._sidebar_definition(),
                self._surface_action_definition(),
                self._reset_definition(),
            )
        }
        self._registry = ToolRegistry()
        self._register(SIDEBAR_ACTION_ID, "Change sidebar visibility", self._set_sidebar)
        self._register(SURFACE_ACTION_ID, "Customize interface presentation", self._configure_surface)
        self._register(WORKSPACE_RESET_ACTION_ID, "Reset interface presentation", self._reset_workspace)

    def _register(self, name: str, label: str, adapter: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self._registry.register(
            CapabilityRecord(
                name=name,
                namespace="ui",
                access=CapabilityAccess.WRITE,
                allowed_agents=frozenset({"VellumAgent", "VellumUI"}),
                stream_label=label,
                adapter=adapter,
            )
        )

    def catalog(self, context: AppActionContext | None = None) -> AppActionCatalog:
        del context
        return AppActionCatalog(
            actions=list(self._definitions.values()),
            surfaces=list(self._surfaces.values()),
        )

    def match_submission(self, message: str) -> AppActionRequest | None:
        """Match only complete, explicitly submitted presentation instructions."""

        submitted = " ".join(str(message or "").strip().split())
        normalized = submitted.casefold()
        if not normalized:
            return None
        persistence = "device"
        if normalized.startswith("temporarily "):
            normalized = normalized.removeprefix("temporarily ")
            submitted = submitted[len("temporarily ") :]
            persistence = "session"
        elif normalized.startswith("please temporarily "):
            normalized = "please " + normalized.removeprefix("please temporarily ")
            submitted = submitted[: len("please ")] + submitted[len("please temporarily ") :]
            persistence = "session"
        for suffix in (" for this session", " just for this session", " for now"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)].rstrip()
                submitted = submitted[: -len(suffix)].rstrip()
                persistence = "session"
                break
        normalized = normalized.rstrip(".!?")
        submitted = submitted.rstrip(".!?")
        polite = r"(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"

        if re.fullmatch(
            polite + r"reset(?:\s+(?:the|my))?\s+(?:interface|workspace layout|layout|ui)",
            normalized,
        ):
            return AppActionRequest(action_id=WORKSPACE_RESET_ACTION_ID)

        theme = re.fullmatch(
            polite
            + r"(?:use|switch to|change(?:\s+the)?\s+theme\s+to|set(?:\s+the)?\s+theme\s+to)\s+"
            + r"(dark|light)(?:\s+(?:theme|mode))?",
            normalized,
        )
        if theme:
            return self._surface_request(
                "workspace",
                properties={"theme": theme.group(1)},
                persistence=persistence,
            )

        visibility = re.fullmatch(
            polite
            + r"(show|open|expand|hide|close|collapse)\s+(?:the\s+|my\s+)?"
            + r"(left sidebar|sidebar|settings panel|settings|right panel|details panel|panel)",
            normalized,
        )
        if visibility:
            visible = visibility.group(1) in {"show", "open", "expand"}
            reference = visibility.group(2)
            if reference in {"left sidebar", "sidebar"}:
                arguments: dict[str, Any] = {"visible": visible}
                if persistence == "session":
                    arguments["persistence"] = persistence
                return AppActionRequest(
                    action_id=SIDEBAR_ACTION_ID,
                    arguments=arguments,
                )
            return self._surface_request(reference, visible=visible, persistence=persistence)

        sidebar_toggle = re.fullmatch(
            polite + r"turn(?:\s+(?:the|my))?\s+(?:left\s+)?sidebar\s+(on|off)",
            normalized,
        )
        if sidebar_toggle:
            arguments = {"visible": sidebar_toggle.group(1) == "on"}
            if persistence == "session":
                arguments["persistence"] = persistence
            return AppActionRequest(
                action_id=SIDEBAR_ACTION_ID,
                arguments=arguments,
            )

        resize = re.fullmatch(
            polite
            + r"make\s+(?:the\s+|my\s+)?(composer|input box|chat input|prompt box|send button)\s+"
            + r"(bigger|larger|large|smaller|compact|normal|comfortable)",
            normalized,
        )
        if resize:
            reference = "composer.send" if resize.group(1) == "send button" else "composer"
            size = {
                "bigger": "large",
                "larger": "large",
                "large": "large",
                "smaller": "compact" if reference == "composer" else "small",
                "compact": "compact" if reference == "composer" else "small",
                "normal": "comfortable" if reference == "composer" else "medium",
                "comfortable": "comfortable" if reference == "composer" else "medium",
            }[resize.group(2)]
            return self._surface_request(
                reference,
                properties={"size": size},
                persistence=persistence,
            )

        relabel = re.fullmatch(
            polite
            + r"(?:change|set|rename)\s+(?:the\s+|my\s+)?(send button|this button)"
            + r"(?:\s+(?:text|label))?\s+to\s+(.+)",
            normalized,
        )
        if relabel:
            display_label = re.search(r"\s+to\s+(.+)$", submitted, flags=re.IGNORECASE)
            label = (display_label.group(1) if display_label else relabel.group(2)).strip().strip("\"'").strip()
            if not label:
                return None
            reference = "composer.send" if relabel.group(1) == "send button" else "this button"
            return self._surface_request(
                reference,
                properties={"label": label},
                persistence=persistence,
            )
        return None

    @staticmethod
    def _surface_request(
        reference: str,
        *,
        visible: bool | None = None,
        properties: dict[str, Any] | None = None,
        persistence: str = "device",
    ) -> AppActionRequest:
        arguments: dict[str, Any] = {"reference": reference}
        if persistence == "session":
            arguments["persistence"] = persistence
        if visible is not None:
            arguments["visible"] = visible
        if properties:
            arguments["properties"] = properties
        return AppActionRequest(action_id=SURFACE_ACTION_ID, arguments=arguments)

    def dispatch(self, request: AppActionRequest, context: AppActionContext) -> ActionReceipt:
        definition = self._definitions.get(request.action_id)
        if definition is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class="unknown",
                error_code="ACTION_UNAVAILABLE",
                message=f"{request.action_id} is unavailable.",
            )
        if request.action_version != definition.version:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="ACTION_VERSION_UNAVAILABLE",
                message=f"{request.action_id} version {request.action_version} is unavailable.",
            )

        try:
            result = self._registry.invoke(
                request.action_id,
                {"arguments": dict(request.arguments), "context": context},
                agent_name=self._agent_name(context),
            )
        except ToolPermissionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="ACTION_NOT_AUTHORIZED",
                message=str(exc),
            )
        except SurfaceActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                result=exc.details,
                authorized=True,
            )
        except (TypeError, ValueError) as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="INVALID_ACTION_ARGUMENTS",
                message=str(exc),
                authorized=True,
            )

        undo_arguments = result.pop("_undo_arguments", None)
        created_at = self._now()
        undo = None
        if result["changed"] and definition.supports_undo and undo_arguments:
            token = self._undo_token_factory()
            expires_at = created_at + _UNDO_TTL
            target_reference = str(result["target_reference"])
            expected_presentation = dict(result["presentation"])
            target_revision = int(result["workspace_layout_patch"]["revision"])
            self._receipt_store.put(
                _UndoRecord(
                    token=token,
                    action_id=request.action_id,
                    previous_arguments=undo_arguments,
                    target_reference=target_reference,
                    expected_presentation=expected_presentation,
                    expected_revision=target_revision,
                    expires_at=expires_at,
                )
            )
            undo = ActionUndo(
                token=token,
                action_id=request.action_id,
                arguments=undo_arguments,
                expires_at=expires_at,
                target_revision=target_revision,
            )

        target_reference = str(result.get("target_reference") or "workspace")
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="applied",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(
                kind="ui_surface" if target_reference != "workspace-layout" else "workspace_layout",
                id=target_reference,
                revision=result["workspace_layout_patch"]["revision"],
            ),
            result=result,
            undo=undo,
            message=self._result_message(result),
            audit_label=definition.audit_label,
            created_at=created_at,
        )

    def undo(self, token: str, context: AppActionContext) -> ActionReceipt:
        record = self._receipt_store.get(token)
        request = AppActionRequest(
            request_id=f"undo_{uuid4().hex}",
            action_id=record.action_id if record else SURFACE_ACTION_ID,
            arguments=record.previous_arguments if record else {},
        )
        definition = self._definitions.get(request.action_id) or self._definitions[SURFACE_ACTION_ID]
        if record is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="UNDO_UNAVAILABLE",
                message="Undo is unavailable.",
            )
        if record.expires_at <= self._now():
            self._receipt_store.remove(token)
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="UNDO_EXPIRED",
                message="Undo has expired.",
            )

        current = self._current_presentation(record.target_reference, context)
        if (
            current.model_dump(mode="json") != record.expected_presentation
            or context.workspace_layout.revision != record.expected_revision
        ):
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="STALE_ACTION_TARGET",
                message="The interface changed after this action, so Undo was not applied.",
                authorized=True,
            )

        try:
            result = self._registry.invoke(
                record.action_id,
                {"arguments": dict(record.previous_arguments), "context": context},
                agent_name=self._agent_name(context),
            )
        except (ToolPermissionError, SurfaceActionError, TypeError, ValueError) as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="UNDO_FAILED",
                message=str(exc),
                authorized=True,
            )

        result.pop("_undo_arguments", None)
        self._receipt_store.remove(token)
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=record.action_id,
            action_version=definition.version,
            source=context.source,
            status="undone",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(
                kind="ui_surface",
                id=record.target_reference,
                revision=result["workspace_layout_patch"]["revision"],
            ),
            result=result,
            message=f"{self._surfaces[record.target_reference].title} change undone.",
            audit_label=f"{definition.audit_label}.undo",
            created_at=self._now(),
        )

    def _set_sidebar(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        arguments["reference"] = "sidebar"
        return self._configure_surface({"arguments": arguments, "context": payload.get("context")})

    def _configure_surface(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = payload.get("arguments") or {}
        context = AppActionContext.model_validate(payload.get("context"))
        surface = self._resolve_surface(str(arguments.get("reference") or ""), context)
        current = self._current_presentation(surface.reference, context)
        visible_supplied = "visible" in arguments
        location_supplied = "location" in arguments
        properties_supplied = "properties" in arguments
        if not any((visible_supplied, location_supplied, properties_supplied)):
            raise SurfaceActionError("EMPTY_SURFACE_PATCH", "No interface change was requested.")

        next_presentation = current.model_copy(deep=True)
        if visible_supplied:
            visible = arguments.get("visible")
            if not isinstance(visible, bool):
                raise SurfaceActionError("INVALID_SURFACE_PROPERTY", "visible must be a boolean.")
            if surface.control_kernel and not visible:
                raise SurfaceActionError(
                    "CONTROL_KERNEL_PROTECTED",
                    f"{surface.title} is part of the Control Kernel and cannot be hidden.",
                )
            next_presentation.visible = visible
        if location_supplied:
            location = str(arguments.get("location") or "")
            if location not in surface.supported_locations:
                raise SurfaceActionError(
                    "UNSUPPORTED_SURFACE_LOCATION",
                    f"{surface.title} cannot be placed at {location or 'that location'}.",
                    details={"supported_locations": surface.supported_locations},
                )
            next_presentation.location = location
        if properties_supplied:
            properties = arguments.get("properties")
            if not isinstance(properties, dict):
                raise SurfaceActionError("INVALID_SURFACE_PROPERTY", "properties must be an object.")
            next_properties = dict(next_presentation.properties)
            for name, value in properties.items():
                schema = surface.configurable_properties.get(name)
                if schema is None:
                    raise SurfaceActionError(
                        "SURFACE_PROPERTY_NOT_ALLOWED",
                        f"{name} cannot be changed on {surface.title}.",
                        details={"allowed_properties": sorted(surface.configurable_properties)},
                    )
                next_properties[name] = self._validate_property(surface, name, value, schema)
            next_presentation.properties = next_properties

        persistence = str(arguments.get("persistence") or "device")
        if persistence not in {"device", "session"}:
            raise SurfaceActionError("INVALID_PERSISTENCE", "persistence must be device or session.")
        changed = current != next_presentation
        snapshot = context.workspace_layout
        revision = snapshot.revision + (1 if changed else 0)
        return {
            "changed": changed,
            "target_reference": surface.reference,
            "presentation": next_presentation.model_dump(mode="json"),
            "previous_presentation": current.model_dump(mode="json"),
            "persistence": persistence,
            "workspace_layout_patch": {
                "version": snapshot.version,
                "base_revision": snapshot.revision,
                "revision": revision,
                "persistence": persistence,
                "replace": False,
                "surfaces": {surface.reference: next_presentation.model_dump(mode="json")},
            },
            "_undo_arguments": {
                "reference": surface.reference,
                "visible": current.visible,
                "location": current.location,
                "properties": current.properties,
                "persistence": persistence,
            },
        }

    def _reset_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = AppActionContext.model_validate(payload.get("context"))
        snapshot = context.workspace_layout
        defaults = {
            reference: surface.default_presentation.model_dump(mode="json")
            for reference, surface in self._surfaces.items()
        }
        current = {
            reference: self._current_presentation(reference, context).model_dump(mode="json")
            for reference in self._surfaces
        }
        changed = current != defaults
        return {
            "changed": changed,
            "target_reference": "workspace-layout",
            "presentation": {},
            "previous_presentation": {},
            "persistence": "device",
            "workspace_layout_patch": {
                "version": snapshot.version,
                "base_revision": snapshot.revision,
                "revision": snapshot.revision + (1 if changed else 0),
                "persistence": "device",
                "replace": True,
                "surfaces": defaults,
            },
        }

    def _resolve_surface(self, reference: str, context: AppActionContext) -> UISurfaceDefinition:
        normalized = self._normalize_reference(reference)
        if normalized in {"this", "this button", "this control", "selected control"}:
            contextual = [context.selected_ui_reference, context.focused_ui_reference]
            matches = [
                self._surfaces[item]
                for item in contextual
                if item in self._surfaces
                and (
                    normalized not in {"this button"}
                    or "label" in self._surfaces[item].configurable_properties
                )
            ]
            unique = {item.reference: item for item in matches}
            if len(unique) == 1:
                return next(iter(unique.values()))
            raise SurfaceActionError(
                "UI_CONTEXT_REQUIRED",
                "Select or name the control you want to change.",
            )
        direct = self._surfaces.get(normalized)
        if direct:
            return direct
        matches = [
            surface
            for surface in self._surfaces.values()
            if normalized in {self._normalize_reference(alias) for alias in surface.aliases}
        ]
        if len(matches) > 1 and context.visible_ui_references:
            visible = set(context.visible_ui_references)
            visible_matches = [surface for surface in matches if surface.reference in visible]
            if len(visible_matches) == 1:
                return visible_matches[0]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            titles = [surface.title for surface in matches]
            raise SurfaceActionError(
                "AMBIGUOUS_UI_REFERENCE",
                f"Which panel do you mean: {' or '.join(titles)}?",
                details={"candidates": [surface.reference for surface in matches]},
            )
        raise SurfaceActionError(
            "UI_REFERENCE_UNAVAILABLE",
            f"{reference or 'That interface surface'} is unavailable.",
        )

    @staticmethod
    def _normalize_reference(reference: str) -> str:
        normalized = " ".join(reference.strip().casefold().split())
        return re.sub(r"^(?:the|my)\s+", "", normalized)

    @staticmethod
    def _validate_property(
        surface: UISurfaceDefinition,
        name: str,
        value: Any,
        schema: dict[str, Any],
    ) -> Any:
        if schema.get("type") == "string" and not isinstance(value, str):
            raise SurfaceActionError("INVALID_SURFACE_PROPERTY", f"{name} must be text.")
        if isinstance(value, str):
            value = value.strip()
            if len(value) < int(schema.get("minLength", 0)):
                raise SurfaceActionError("INVALID_SURFACE_PROPERTY", f"{name} is too short.")
            if len(value) > int(schema.get("maxLength", 10_000)):
                raise SurfaceActionError("INVALID_SURFACE_PROPERTY", f"{name} is too long.")
        allowed = schema.get("enum")
        if allowed and value not in allowed:
            raise SurfaceActionError(
                "INVALID_SURFACE_PROPERTY",
                f"{value} is not a supported {name} for {surface.title}.",
                details={"allowed_values": allowed},
            )
        return value

    def _current_presentation(self, reference: str, context: AppActionContext) -> SurfacePresentation:
        current = context.workspace_layout.surfaces.get(reference)
        if current is not None:
            default = self._surfaces[reference].default_presentation
            return SurfacePresentation(
                visible=current.visible,
                location=current.location or default.location,
                properties={**default.properties, **current.properties},
            )
        return self._surfaces[reference].default_presentation.model_copy(deep=True)

    @staticmethod
    def _result_message(result: dict[str, Any]) -> str:
        if result["target_reference"] == "workspace-layout":
            return "Interface reset to its registered defaults." if result["changed"] else "The interface already uses its registered defaults."
        reference = result["target_reference"]
        presentation = result["presentation"]
        previous = result["previous_presentation"]
        if not result["changed"]:
            return f"{reference.replace('-', ' ').title()} is already configured that way."
        if reference == "workspace" and presentation["properties"].get("theme") != previous["properties"].get("theme"):
            return f"Theme changed to {presentation['properties']['theme']}."
        if reference == "composer" and presentation["properties"].get("size") != previous["properties"].get("size"):
            return f"Composer size changed to {presentation['properties']['size']}."
        if reference == "composer.send":
            if presentation["properties"].get("label") != previous["properties"].get("label"):
                return f"Send button label changed to {presentation['properties']['label']}."
            return f"Send button size changed to {presentation['properties']['size']}."
        title = {"sidebar": "Sidebar", "settings": "Settings", "right-panel": "Right panel"}.get(reference, reference.title())
        return f"{title} {'shown' if presentation['visible'] else 'hidden'}."

    @staticmethod
    def _surface_definitions() -> list[UISurfaceDefinition]:
        return [
            UISurfaceDefinition(
                reference="workspace", owner="workspace-layout", title="Workspace",
                aliases=["app", "application", "theme"],
                default_presentation=SurfacePresentation(visible=True, location="application", properties={"theme": "dark"}),
                supported_locations=["application"],
                configurable_properties={"theme": {"type": "string", "enum": ["dark", "light"]}},
                control_kernel=True,
            ),
            UISurfaceDefinition(
                reference="sidebar", owner="workspace-layout", title="Sidebar",
                aliases=["sidebar", "left sidebar"],
                default_presentation=SurfacePresentation(visible=True, location="left"),
                supported_locations=["left"],
            ),
            UISurfaceDefinition(
                reference="settings", owner="workspace-layout", title="Settings",
                aliases=["settings", "settings panel", "panel"],
                default_presentation=SurfacePresentation(visible=False, location="overlay"),
                supported_locations=["overlay"],
            ),
            UISurfaceDefinition(
                reference="right-panel", owner="workspace-layout", title="Right panel",
                aliases=["right panel", "details panel", "panel"],
                default_presentation=SurfacePresentation(visible=False, location="right"),
                supported_locations=["right"],
            ),
            UISurfaceDefinition(
                reference="composer", owner="control-kernel", title="Composer",
                aliases=["composer", "input box", "chat input", "prompt box"],
                default_presentation=SurfacePresentation(visible=True, location="bottom", properties={"size": "comfortable"}),
                supported_locations=["bottom"],
                configurable_properties={"size": {"type": "string", "enum": ["compact", "comfortable", "large"]}},
                control_kernel=True,
            ),
            UISurfaceDefinition(
                reference="composer.send", owner="control-kernel", title="Send button",
                aliases=["send button", "submit button"],
                default_presentation=SurfacePresentation(visible=True, location="composer-action", properties={"label": "Send", "size": "medium"}),
                supported_locations=["composer-action"],
                configurable_properties={
                    "label": {"type": "string", "minLength": 1, "maxLength": 24},
                    "size": {"type": "string", "enum": ["small", "medium", "large"]},
                },
                control_kernel=True,
            ),
        ]

    @staticmethod
    def _sidebar_definition() -> AppActionDefinition:
        return AppActionDefinition(
            id=SIDEBAR_ACTION_ID, version="1", owner="workspace-layout", title="Set sidebar visibility",
            description="Show or hide the registered sidebar UI Surface.", scope="device",
            access_class=CapabilityAccess.WRITE.value, confirmation_rule="none", executor_location="client",
            supports_undo=True, idempotent=True,
            argument_schema={
                "type": "object", "required": ["visible"], "additionalProperties": False,
                "properties": {"visible": {"type": "boolean"}, "persistence": {"enum": ["device", "session"]}},
            },
            result_schema={"type": "object", "required": ["workspace_layout_patch", "changed"]},
            ui_reference="sidebar", audit_label="workspace.sidebar.visibility",
        )

    @staticmethod
    def _surface_action_definition() -> AppActionDefinition:
        return AppActionDefinition(
            id=SURFACE_ACTION_ID, version="1", owner="workspace-layout", title="Configure an interface surface",
            description="Change allowlisted presentation properties on a registered UI Surface.", scope="device",
            access_class=CapabilityAccess.WRITE.value, confirmation_rule="none", executor_location="client",
            supports_undo=True, idempotent=True,
            argument_schema={
                "type": "object", "required": ["reference"],
                "properties": {
                    "reference": {"type": "string"}, "visible": {"type": "boolean"},
                    "location": {"type": "string"}, "properties": {"type": "object"},
                    "persistence": {"enum": ["device", "session"]},
                },
            },
            result_schema={"type": "object", "required": ["workspace_layout_patch", "changed"]},
            ui_reference="workspace-layout", audit_label="workspace.surface.configure",
        )

    @staticmethod
    def _reset_definition() -> AppActionDefinition:
        return AppActionDefinition(
            id=WORKSPACE_RESET_ACTION_ID, version="1", owner="workspace-layout", title="Reset interface layout",
            description="Remove presentation overrides and restore every registered default.", scope="device",
            access_class=CapabilityAccess.WRITE.value, confirmation_rule="none", executor_location="client",
            supports_undo=False, idempotent=True,
            argument_schema={"type": "object", "additionalProperties": False},
            result_schema={"type": "object", "required": ["workspace_layout_patch", "changed"]},
            ui_reference="workspace-layout", audit_label="workspace.layout.reset",
        )

    def _error_receipt(
        self, *, request: AppActionRequest, context: AppActionContext, status: str,
        access_class: str, error_code: str, message: str, result: dict[str, Any] | None = None,
        authorized: bool = False,
    ) -> ActionReceipt:
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(), request_id=request.request_id,
            action_id=request.action_id, action_version=request.action_version, source=context.source,
            status=status, authorization=self._authorization(access_class, context, allowed=authorized),
            target=ActionTarget(kind="app_action", id=request.action_id), result=result or {},
            message=message, error_code=error_code, audit_label="app_action.rejected", created_at=self._now(),
        )

    def _authorization(self, access_class: str, context: AppActionContext, *, allowed: bool) -> ActionAuthorization:
        return ActionAuthorization(
            decision="allowed" if allowed else "denied", access_class=access_class,
            confirmation_required=False, agent_name=self._agent_name(context),
        )

    @staticmethod
    def _agent_name(context: AppActionContext) -> str:
        return "VellumAgent" if context.source == "nlp" else "VellumUI"

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


_runtime: AppActionRuntime | None = None


def get_app_action_runtime() -> AppActionRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AppActionRuntime()
    return _runtime


def reset_app_action_runtime() -> None:
    global _runtime
    _runtime = None
