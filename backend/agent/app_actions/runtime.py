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
)
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


SIDEBAR_ACTION_ID = "ui.sidebar.set"
_UNDO_TTL = timedelta(minutes=15)


@dataclass(frozen=True)
class _UndoRecord:
    token: str
    original_request_id: str
    action_id: str
    previous_arguments: dict[str, Any]
    expected_visible: bool
    expected_revision: int
    expires_at: datetime


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
        self._definitions = {SIDEBAR_ACTION_ID: self._sidebar_definition()}
        self._registry = ToolRegistry()
        self._registry.register(
            CapabilityRecord(
                name=SIDEBAR_ACTION_ID,
                namespace="ui",
                access=CapabilityAccess.WRITE,
                allowed_agents=frozenset({"VellumAgent", "VellumUI"}),
                stream_label="Change sidebar visibility",
                adapter=self._set_sidebar,
            )
        )

    def catalog(self, context: AppActionContext | None = None) -> AppActionCatalog:
        del context
        return AppActionCatalog(actions=list(self._definitions.values()))

    def match_submission(self, message: str) -> AppActionRequest | None:
        """Match only a complete, explicitly submitted sidebar instruction."""

        normalized = " ".join(str(message or "").strip().split()).casefold()
        normalized = normalized.rstrip(".!?")
        polite = r"(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
        target = r"(?:\s+(?:the|my))?\s+(?:left\s+)?sidebar(?:\s+please)?"
        match = re.fullmatch(polite + r"(show|open|expand|hide|close|collapse)" + target, normalized)
        if match:
            return AppActionRequest(
                action_id=SIDEBAR_ACTION_ID,
                arguments={"visible": match.group(1) in {"show", "open", "expand"}},
            )
        match = re.fullmatch(polite + r"turn" + target + r"\s+(on|off)", normalized)
        if match:
            return AppActionRequest(
                action_id=SIDEBAR_ACTION_ID,
                arguments={"visible": match.group(1) == "on"},
            )
        return None

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

        agent_name = self._agent_name(context)
        try:
            result = self._registry.invoke(
                request.action_id,
                {"arguments": dict(request.arguments), "context": context},
                agent_name=agent_name,
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
        except (TypeError, ValueError) as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="INVALID_ACTION_ARGUMENTS",
                message=str(exc),
            )

        created_at = self._now()
        undo = None
        if result["changed"]:
            token = self._undo_token_factory()
            expires_at = created_at + _UNDO_TTL
            self._receipt_store.put(
                _UndoRecord(
                    token=token,
                    original_request_id=request.request_id,
                    action_id=request.action_id,
                    previous_arguments={"visible": result["previous_visible"]},
                    expected_visible=result["visible"],
                    expected_revision=result["workspace_layout_patch"]["revision"],
                    expires_at=expires_at,
                )
            )
            undo = ActionUndo(
                token=token,
                action_id=request.action_id,
                arguments={"visible": result["previous_visible"]},
                expires_at=expires_at,
                target_revision=result["workspace_layout_patch"]["revision"],
            )

        visible = result["visible"]
        message = (
            f"Sidebar {'shown' if visible else 'hidden'}."
            if result["changed"]
            else f"The sidebar is already {'shown' if visible else 'hidden'}."
        )
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="applied",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(
                kind="ui_surface",
                id=definition.ui_reference,
                revision=result["workspace_layout_patch"]["revision"],
            ),
            result=result,
            undo=undo,
            message=message,
            audit_label=definition.audit_label,
            created_at=created_at,
        )

    def undo(self, token: str, context: AppActionContext) -> ActionReceipt:
        record = self._receipt_store.get(token)
        request = AppActionRequest(
            request_id=f"undo_{uuid4().hex}",
            action_id=record.action_id if record else SIDEBAR_ACTION_ID,
            arguments=record.previous_arguments if record else {},
        )
        definition = self._definitions[SIDEBAR_ACTION_ID]
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

        sidebar = context.workspace_layout.surfaces.get("sidebar", SurfacePresentation())
        if (
            sidebar.visible != record.expected_visible
            or context.workspace_layout.revision != record.expected_revision
        ):
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="STALE_ACTION_TARGET",
                message="The sidebar changed after this action, so Undo was not applied.",
            )

        try:
            result = self._registry.invoke(
                record.action_id,
                {"arguments": dict(record.previous_arguments), "context": context},
                agent_name=self._agent_name(context),
            )
        except (ToolPermissionError, TypeError, ValueError) as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="UNDO_FAILED",
                message=str(exc),
            )

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
                id=definition.ui_reference,
                revision=result["workspace_layout_patch"]["revision"],
            ),
            result=result,
            message="Sidebar change undone.",
            audit_label=f"{definition.audit_label}.undo",
            created_at=self._now(),
        )

    @staticmethod
    def _sidebar_definition() -> AppActionDefinition:
        return AppActionDefinition(
            id=SIDEBAR_ACTION_ID,
            version="1",
            owner="workspace-layout",
            title="Set sidebar visibility",
            description="Show or hide the registered sidebar UI Surface.",
            scope="device",
            access_class=CapabilityAccess.WRITE.value,
            confirmation_rule="none",
            executor_location="client",
            supports_undo=True,
            idempotent=True,
            argument_schema={
                "type": "object",
                "required": ["visible"],
                "additionalProperties": False,
                "properties": {"visible": {"type": "boolean"}},
            },
            result_schema={
                "type": "object",
                "required": ["workspace_layout_patch", "changed"],
            },
            ui_reference="sidebar",
            audit_label="workspace.sidebar.visibility",
        )

    @staticmethod
    def _set_sidebar(payload: dict[str, Any]) -> dict[str, Any]:
        arguments = payload.get("arguments") or {}
        visible = arguments.get("visible")
        if not isinstance(visible, bool):
            raise ValueError("visible must be a boolean")
        context = AppActionContext.model_validate(payload.get("context"))
        snapshot = context.workspace_layout
        previous = snapshot.surfaces.get("sidebar", SurfacePresentation()).visible
        changed = previous != visible
        revision = snapshot.revision + (1 if changed else 0)
        return {
            "changed": changed,
            "visible": visible,
            "previous_visible": previous,
            "workspace_layout_patch": {
                "version": snapshot.version,
                "base_revision": snapshot.revision,
                "revision": revision,
                "surfaces": {"sidebar": {"visible": visible}},
            },
        }

    def _error_receipt(
        self,
        *,
        request: AppActionRequest,
        context: AppActionContext,
        status: str,
        access_class: str,
        error_code: str,
        message: str,
    ) -> ActionReceipt:
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=request.action_version,
            source=context.source,
            status=status,
            authorization=self._authorization(access_class, context, allowed=False),
            target=ActionTarget(kind="app_action", id=request.action_id),
            message=message,
            error_code=error_code,
            audit_label="app_action.rejected",
            created_at=self._now(),
        )

    def _authorization(
        self,
        access_class: str,
        context: AppActionContext,
        *,
        allowed: bool,
    ) -> ActionAuthorization:
        return ActionAuthorization(
            decision="allowed" if allowed else "denied",
            access_class=access_class,
            confirmation_required=False,
            agent_name=self._agent_name(context),
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
