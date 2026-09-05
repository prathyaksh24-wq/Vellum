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
    ActionConfirmation,
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
from agent.conversations.lifecycle import ConversationLifecycle, ConversationLifecycleError
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


SIDEBAR_ACTION_ID = "ui.sidebar.set"
SURFACE_ACTION_ID = "ui.surface.configure"
WORKSPACE_RESET_ACTION_ID = "ui.workspace.reset"
CONVERSATION_NEW_ACTION_ID = "conversation.new"
CONVERSATION_OPEN_ACTION_ID = "conversation.open"
CONVERSATION_PIN_ACTION_ID = "conversation.pin"
CONVERSATION_UNPIN_ACTION_ID = "conversation.unpin"
CONVERSATION_RENAME_ACTION_ID = "conversation.rename"
CONVERSATION_SPACE_ACTION_ID = "conversation.space.set"
CONVERSATION_ARCHIVE_ACTION_ID = "conversation.archive"
CONVERSATION_RESTORE_ACTION_ID = "conversation.restore"
CONVERSATION_DELETE_ACTION_ID = "conversation.delete"
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


@dataclass(frozen=True)
class _ConversationUndoRecord:
    token: str
    action_id: str
    undo_action_id: str
    previous_arguments: dict[str, Any]
    target_reference: str
    expected_revision: int
    expires_at: datetime


@dataclass(frozen=True)
class _ConfirmationRecord:
    token: str
    action_id: str
    action_version: str
    arguments: dict[str, Any]
    target_reference: str
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
        self._records: dict[str, _UndoRecord | _ConversationUndoRecord] = {}
        self._confirmations: dict[str, _ConfirmationRecord] = {}
        self._lock = Lock()

    def put(self, record: _UndoRecord | _ConversationUndoRecord) -> None:
        with self._lock:
            self._records[record.token] = record

    def get(self, token: str) -> _UndoRecord | _ConversationUndoRecord | None:
        with self._lock:
            return self._records.get(token)

    def remove(self, token: str) -> None:
        with self._lock:
            self._records.pop(token, None)

    def put_confirmation(self, record: _ConfirmationRecord) -> None:
        with self._lock:
            self._confirmations[record.token] = record

    def get_confirmation(self, token: str) -> _ConfirmationRecord | None:
        with self._lock:
            return self._confirmations.get(token)

    def remove_confirmation(self, token: str) -> None:
        with self._lock:
            self._confirmations.pop(token, None)


class AppActionRuntime:
    """Discover, authorize, dispatch, and undo semantic Vellum actions."""

    def __init__(
        self,
        *,
        receipt_store: InMemoryReceiptStore | None = None,
        clock: Callable[[], datetime] | None = None,
        receipt_id_factory: Callable[[], str] | None = None,
        undo_token_factory: Callable[[], str] | None = None,
        confirmation_token_factory: Callable[[], str] | None = None,
        conversation_lifecycle: ConversationLifecycle | Callable[[], ConversationLifecycle] | None = None,
    ) -> None:
        self._receipt_store = receipt_store or InMemoryReceiptStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._receipt_id_factory = receipt_id_factory or (lambda: f"receipt_{uuid4().hex}")
        self._undo_token_factory = undo_token_factory or (lambda: secrets.token_urlsafe(24))
        self._confirmation_token_factory = confirmation_token_factory or (lambda: secrets.token_urlsafe(24))
        self._conversation_lifecycle = conversation_lifecycle
        self._conversation_actions_registered = False
        self._surfaces = {surface.reference: surface for surface in self._surface_definitions()}
        self._definitions = {
            definition.id: definition
            for definition in (
                self._sidebar_definition(),
                self._surface_action_definition(),
                self._reset_definition(),
                *self._conversation_definitions(),
            )
        }
        self._registry = ToolRegistry()
        self._register(SIDEBAR_ACTION_ID, "Change sidebar visibility", self._set_sidebar)
        self._register(SURFACE_ACTION_ID, "Customize interface presentation", self._configure_surface)
        self._register(WORKSPACE_RESET_ACTION_ID, "Reset interface presentation", self._reset_workspace)
        if self._conversation_lifecycle is not None:
            self.set_conversation_lifecycle_provider(self._conversation_lifecycle)

    def _register(
        self,
        name: str,
        label: str,
        adapter: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        access: CapabilityAccess = CapabilityAccess.WRITE,
    ) -> None:
        self._registry.register(
            CapabilityRecord(
                name=name,
                namespace=name.split(".", 1)[0],
                access=access,
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
            polite + r"(?:start|create|open)(?:\s+(?:a|another))?\s+new\s+(?:chat|conversation)",
            normalized,
        ):
            return AppActionRequest(action_id=CONVERSATION_NEW_ACTION_ID)

        rename_referenced_chat = re.fullmatch(
            polite
            + r'''rename\s+(?:the\s+)?(?:chat|conversation)\s+(?:called|named)\s+("[^"]+"|'[^']+')\s+to\s+(.+)''',
            submitted,
            flags=re.IGNORECASE,
        )
        if rename_referenced_chat:
            reference = self._spoken_value(rename_referenced_chat.group(1))
            title = self._spoken_value(rename_referenced_chat.group(2))
            return AppActionRequest(
                action_id=CONVERSATION_RENAME_ACTION_ID,
                arguments={"reference": reference, "title": title},
            ) if reference and title else None

        rename_chat = re.fullmatch(
            polite
            + r"rename\s+(?:(?:this|the\s+current|current)\s+)?(?:chat|conversation)\s+to\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if rename_chat:
            title = self._spoken_value(rename_chat.group(1))
            return AppActionRequest(
                action_id=CONVERSATION_RENAME_ACTION_ID,
                arguments={"title": title},
            ) if title else None

        move_referenced_chat = re.fullmatch(
            polite
            + r'''(?:move|put)\s+(?:the\s+)?(?:chat|conversation)\s+(?:called|named)\s+("[^"]+"|'[^']+')\s+to\s+(.+?)(?:\s+space)?''',
            submitted,
            flags=re.IGNORECASE,
        )
        if move_referenced_chat:
            reference = self._spoken_value(move_referenced_chat.group(1))
            space_label = self._spoken_value(move_referenced_chat.group(2))
            return AppActionRequest(
                action_id=CONVERSATION_SPACE_ACTION_ID,
                arguments={"reference": reference, "space_label": space_label},
            ) if reference and space_label else None

        move_chat = re.fullmatch(
            polite
            + r"(?:move|put)\s+(?:(?:this|the\s+current|current)\s+)?(?:chat|conversation)\s+to\s+(.+?)(?:\s+space)?",
            submitted,
            flags=re.IGNORECASE,
        )
        if move_chat:
            space_label = self._spoken_value(move_chat.group(1))
            return AppActionRequest(
                action_id=CONVERSATION_SPACE_ACTION_ID,
                arguments={"space_label": space_label},
            ) if space_label else None

        current_chat_action = re.fullmatch(
            polite
            + r"(pin|unpin|archive|restore|delete)\s+"
            + r"(?:(?:this|the\s+current|current)\s+)(?:chat|conversation)",
            normalized,
        )
        if current_chat_action:
            action_id = {
                "pin": CONVERSATION_PIN_ACTION_ID,
                "unpin": CONVERSATION_UNPIN_ACTION_ID,
                "archive": CONVERSATION_ARCHIVE_ACTION_ID,
                "restore": CONVERSATION_RESTORE_ACTION_ID,
                "delete": CONVERSATION_DELETE_ACTION_ID,
            }[current_chat_action.group(1)]
            return AppActionRequest(action_id=action_id)

        referenced_chat_action = re.fullmatch(
            polite
            + r"(open|pin|unpin|archive|restore|delete)\s+(?:the\s+)?(?:chat|conversation)"
            + r"(?:\s+(?:called|named))?\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if referenced_chat_action:
            reference = self._spoken_value(referenced_chat_action.group(2))
            if not reference:
                return None
            action_id = {
                "open": CONVERSATION_OPEN_ACTION_ID,
                "pin": CONVERSATION_PIN_ACTION_ID,
                "unpin": CONVERSATION_UNPIN_ACTION_ID,
                "archive": CONVERSATION_ARCHIVE_ACTION_ID,
                "restore": CONVERSATION_RESTORE_ACTION_ID,
                "delete": CONVERSATION_DELETE_ACTION_ID,
            }[referenced_chat_action.group(1).casefold()]
            return AppActionRequest(action_id=action_id, arguments={"reference": reference})

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
            submitted,
            flags=re.IGNORECASE,
        )
        if relabel:
            label = relabel.group(2).strip().strip("\"'").strip()
            if not label:
                return None
            reference = "composer.send" if relabel.group(1).casefold() == "send button" else "this button"
            return self._surface_request(
                reference,
                properties={"label": label},
                persistence=persistence,
            )
        return None

    @staticmethod
    def _spoken_value(value: str) -> str:
        return " ".join(str(value or "").strip().strip("\"'").split())

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

        if request.action_id.startswith("conversation."):
            return self._dispatch_conversation(request, context, definition)

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
        if isinstance(record, _ConversationUndoRecord):
            return self._undo_conversation(record, context)
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

    def _dispatch_conversation(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
    ) -> ActionReceipt:
        if self._conversation_lifecycle is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="CONVERSATION_ACTIONS_UNAVAILABLE",
                message="Conversation actions are unavailable.",
            )
        if definition.confirmation_rule == "operation_bound" and not confirmed:
            try:
                return self._confirmation_receipt(request, context, definition)
            except ConversationLifecycleError as exc:
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
        except ConversationLifecycleError as exc:
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
        undo_action_id = result.pop("_undo_action_id", request.action_id)
        created_at = self._now()
        undo = None
        if result["changed"] and definition.supports_undo and undo_arguments:
            token = self._undo_token_factory()
            expires_at = created_at + _UNDO_TTL
            target_revision = int(result["target_revision"])
            self._receipt_store.put(
                _ConversationUndoRecord(
                    token=token,
                    action_id=request.action_id,
                    undo_action_id=str(undo_action_id),
                    previous_arguments=dict(undo_arguments),
                    target_reference=str(result["target_id"]),
                    expected_revision=target_revision,
                    expires_at=expires_at,
                )
            )
            undo = ActionUndo(
                token=token,
                action_id=str(undo_action_id),
                arguments=dict(undo_arguments),
                expires_at=expires_at,
                target_revision=target_revision,
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
                kind=str(result.get("target_kind") or "conversation"),
                id=str(result["target_id"]),
                revision=int(result["target_revision"]),
            ),
            result=result,
            undo=undo,
            message=str(result.get("message") or "Conversation updated."),
            audit_label=definition.audit_label,
            created_at=created_at,
        )

    def _confirmation_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        conversation_id = self._conversation_target(request.arguments, context)
        conversation = self._conversation_service().get(conversation_id)
        revision = int(conversation.get("revision", 0))
        expected = self._expected_target_revision(request.arguments)
        if expected is not None and expected != revision:
            raise ConversationLifecycleError(
                "STALE_ACTION_TARGET",
                "The conversation changed before this action could be confirmed.",
            )
        token = self._confirmation_token_factory()
        expires_at = self._now() + _UNDO_TTL
        self._receipt_store.put_confirmation(
            _ConfirmationRecord(
                token=token,
                action_id=request.action_id,
                action_version=request.action_version,
                arguments=dict(request.arguments),
                target_reference=conversation_id,
                expected_revision=revision,
                expires_at=expires_at,
            )
        )
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="confirmation_required",
            authorization=self._authorization(
                definition.access_class,
                context,
                allowed=True,
                confirmation_required=True,
            ),
            target=ActionTarget(kind="conversation", id=conversation_id, revision=revision),
            result={
                "conversation": {
                    "id": conversation_id,
                    "title": conversation.get("title"),
                    "revision": revision,
                },
            },
            confirmation=ActionConfirmation(
                token=token,
                expires_at=expires_at,
                target_revision=revision,
            ),
            message=f"Confirm deletion of {conversation.get('title') or 'this chat'}.",
            audit_label=f"{definition.audit_label}.confirmation_requested",
            created_at=self._now(),
        )

    def confirm(
        self,
        token: str,
        request: AppActionRequest,
        context: AppActionContext,
    ) -> ActionReceipt:
        record = self._receipt_store.get_confirmation(token)
        definition = self._definitions.get(request.action_id)
        access_class = definition.access_class if definition else "unknown"
        if record is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=access_class,
                error_code="CONFIRMATION_UNAVAILABLE",
                message="Confirmation is unavailable.",
            )
        if record.expires_at <= self._now():
            self._receipt_store.remove_confirmation(token)
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=access_class,
                error_code="CONFIRMATION_EXPIRED",
                message="Confirmation has expired.",
            )
        if (
            request.action_id != record.action_id
            or request.action_version != record.action_version
            or request.arguments != record.arguments
        ):
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=access_class,
                error_code="CONFIRMATION_MISMATCH",
                message="Confirmation does not match the requested operation.",
                authorized=True,
            )
        try:
            current = self._conversation_service().get(record.target_reference)
        except ConversationLifecycleError as exc:
            self._receipt_store.remove_confirmation(token)
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=True,
            )
        if int(current.get("revision", 0)) != record.expected_revision:
            self._receipt_store.remove_confirmation(token)
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=access_class,
                error_code="STALE_ACTION_TARGET",
                message="The conversation changed before deletion was confirmed.",
                authorized=True,
            )
        self._receipt_store.remove_confirmation(token)
        return self._dispatch_conversation(request, context, definition, confirmed=True)

    def set_conversation_lifecycle_provider(
        self,
        provider: ConversationLifecycle | Callable[[], ConversationLifecycle],
    ) -> None:
        self._conversation_lifecycle = provider
        if self._conversation_actions_registered:
            return
        self._register(CONVERSATION_NEW_ACTION_ID, "Start new conversation", self._new_conversation)
        self._register(CONVERSATION_OPEN_ACTION_ID, "Open conversation", self._open_conversation)
        self._register(CONVERSATION_PIN_ACTION_ID, "Pin conversation", self._pin_conversation)
        self._register(CONVERSATION_UNPIN_ACTION_ID, "Unpin conversation", self._unpin_conversation)
        self._register(CONVERSATION_RENAME_ACTION_ID, "Rename conversation", self._rename_conversation)
        self._register(CONVERSATION_SPACE_ACTION_ID, "Change conversation Space", self._set_conversation_space)
        self._register(CONVERSATION_ARCHIVE_ACTION_ID, "Archive conversation", self._archive_conversation)
        self._register(CONVERSATION_RESTORE_ACTION_ID, "Restore conversation", self._restore_conversation)
        self._register(
            CONVERSATION_DELETE_ACTION_ID,
            "Delete conversation",
            self._delete_conversation,
            access=CapabilityAccess.DESTRUCTIVE,
        )
        self._conversation_actions_registered = True

    def _conversation_service(self) -> ConversationLifecycle:
        provider = self._conversation_lifecycle
        if provider is None:
            raise ConversationLifecycleError(
                "CONVERSATION_ACTIONS_UNAVAILABLE",
                "Conversation actions are unavailable.",
            )
        return provider() if callable(provider) else provider

    def _undo_conversation(
        self,
        record: _ConversationUndoRecord,
        context: AppActionContext,
    ) -> ActionReceipt:
        definition = self._definitions[record.action_id]
        request = AppActionRequest(
            request_id=f"undo_{uuid4().hex}",
            action_id=record.undo_action_id,
            arguments=dict(record.previous_arguments),
        )
        if record.expires_at <= self._now():
            self._receipt_store.remove(record.token)
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="UNDO_EXPIRED",
                message="Undo has expired.",
            )
        try:
            current = self._conversation_service().get(record.target_reference)
            if int(current.get("revision", 0)) != record.expected_revision:
                raise ConversationLifecycleError(
                    "STALE_ACTION_TARGET",
                    "The conversation changed after this action, so Undo was not applied.",
                )
            result = self._registry.invoke(
                record.undo_action_id,
                {"arguments": dict(record.previous_arguments), "context": context},
                agent_name=self._agent_name(context),
            )
        except (ToolPermissionError, ConversationLifecycleError, TypeError, ValueError) as exc:
            code = exc.code if isinstance(exc, ConversationLifecycleError) else "UNDO_FAILED"
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code=code,
                message=str(exc),
                authorized=True,
            )
        result.pop("_undo_arguments", None)
        result.pop("_undo_action_id", None)
        self._receipt_store.remove(record.token)
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=record.action_id,
            action_version=definition.version,
            source=context.source,
            status="undone",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(
                kind="conversation",
                id=record.target_reference,
                revision=int(result["target_revision"]),
            ),
            result=result,
            message="Conversation change undone.",
            audit_label=f"{definition.audit_label}.undo",
            created_at=self._now(),
        )

    def _pin_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._set_conversation_flag(
            payload,
            field="pinned",
            value=True,
            inverse=CONVERSATION_UNPIN_ACTION_ID,
            message="Chat pinned.",
        )

    def _new_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {
            "changed": True,
            "target_kind": "conversation_navigation",
            "target_id": "new",
            "target_revision": 0,
            "navigation": {"view": "chat", "conversation_id": None},
            "message": "New chat ready.",
        }

    def _open_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        conversation = self._conversation_service().get(conversation_id)
        return {
            "changed": True,
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": int(conversation.get("revision", 0)),
            "conversation": conversation,
            "navigation": {"view": "chat", "conversation_id": conversation_id},
            "message": f"Opened {conversation.get('title') or 'chat'}.",
        }

    def _unpin_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._set_conversation_flag(
            payload,
            field="pinned",
            value=False,
            inverse=CONVERSATION_PIN_ACTION_ID,
            message="Chat unpinned.",
        )

    def _archive_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._set_conversation_flag(
            payload,
            field="archived",
            value=True,
            inverse=CONVERSATION_RESTORE_ACTION_ID,
            message="Chat archived.",
        )

    def _restore_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._set_conversation_flag(
            payload,
            field="archived",
            value=False,
            inverse=CONVERSATION_ARCHIVE_ACTION_ID,
            message="Chat restored.",
        )

    def _delete_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        expected = self._expected_target_revision(arguments)
        mutation = self._conversation_service().delete(
            conversation_id,
            expected_revision=expected,
        )
        deleted = mutation["conversation"]
        result = {
            "changed": True,
            "deleted": True,
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": int(deleted.get("revision", 0)),
            "conversation_id": conversation_id,
            "deleted_fts_rows": mutation.get("deleted_fts_rows", 0),
            "deleted_context_refs": mutation.get("deleted_context_refs", 0),
            "obsidian_projection": mutation.get("obsidian_projection", {}),
            "message": "Chat deleted.",
        }
        if conversation_id == context.invocation_conversation_id:
            result["navigation"] = {"view": "chat", "conversation_id": None}
        return result

    def _rename_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        title = " ".join(str(arguments.get("title") or "").split())
        if not title:
            raise ValueError("title is required.")
        if len(title) > 160:
            raise ValueError("title must be 160 characters or fewer.")
        expected = self._expected_target_revision(arguments)
        mutation = self._conversation_service().patch(
            conversation_id,
            {"title": title},
            expected_revision=expected,
        )
        conversation = mutation["conversation"]
        previous = mutation["previous_conversation"]
        revision = int(conversation.get("revision", 0))
        result = {
            "changed": bool(mutation["changed"]),
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": revision,
            "conversation": conversation,
            "message": f"Chat renamed to {title}.",
            "_undo_action_id": CONVERSATION_RENAME_ACTION_ID,
            "_undo_arguments": {
                "conversation_id": conversation_id,
                "title": str(previous.get("title") or "New chat"),
                "target_revision": revision,
            },
        }
        return result

    def _set_conversation_space(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        expected = self._expected_target_revision(arguments)
        if "restore_organization" in arguments:
            organization = arguments.get("restore_organization")
            if organization is not None and not isinstance(organization, dict):
                raise ValueError("restore_organization must be an object.")
        elif arguments.get("assignment") == "automatic":
            organization = None
        else:
            space_id = " ".join(str(arguments.get("space_id") or "").split())
            space_label = " ".join(str(arguments.get("space_label") or "").split())
            if not space_id and not space_label:
                raise ValueError("space_id or space_label is required.")
            current = self._conversation_service().get(conversation_id)
            existing = current.get("organization") if isinstance(current.get("organization"), dict) else {}
            organization = {**existing, "assignment": "manual"}
            if space_id:
                organization["space_id"] = space_id
                if not space_label:
                    organization.pop("space_label", None)
            if space_label:
                organization["space_label"] = space_label
                if not space_id:
                    organization.pop("space_id", None)
            for key in ("topic_id", "topic_label"):
                if key in arguments:
                    organization[key] = " ".join(str(arguments.get(key) or "").split())
        mutation = self._conversation_service().set_organization(
            conversation_id,
            organization,
            expected_revision=expected,
        )
        conversation = mutation["conversation"]
        previous = mutation["previous_conversation"]
        previous_organization = previous.get("organization") if isinstance(previous.get("organization"), dict) else None
        revision = int(conversation.get("revision", 0))
        space = conversation.get("organization") or {}
        result = {
            "changed": bool(mutation["changed"]),
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": revision,
            "conversation": conversation,
            "message": f"Chat moved to {space.get('space_label') or space.get('space_id') or 'Automatic'}.",
            "_undo_action_id": CONVERSATION_SPACE_ACTION_ID,
            "_undo_arguments": {
                "conversation_id": conversation_id,
                "restore_organization": previous_organization,
                "target_revision": revision,
            },
        }
        return result

    def _set_conversation_flag(
        self,
        payload: dict[str, Any],
        *,
        field: str,
        value: bool,
        inverse: str,
        message: str,
    ) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        expected = self._expected_target_revision(arguments)
        mutation = self._conversation_service().patch(
            conversation_id,
            {field: value},
            expected_revision=expected,
        )
        conversation = mutation["conversation"]
        revision = int(conversation.get("revision", 0))
        result = {
            "changed": bool(mutation["changed"]),
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": revision,
            "conversation": conversation,
            "message": message,
            "_undo_action_id": inverse,
            "_undo_arguments": {
                "conversation_id": conversation_id,
                "target_revision": revision,
            },
        }
        if field == "archived" and value and conversation_id == context.invocation_conversation_id:
            result["navigation"] = {"view": "chat", "conversation_id": None}
        return result

    def _conversation_target(self, arguments: dict[str, Any], context: AppActionContext) -> str:
        conversation_id = str(arguments.get("conversation_id") or "").strip()
        if conversation_id:
            return str(self._conversation_service().get(conversation_id).get("id") or "")
        reference = str(arguments.get("reference") or "").strip()
        if reference:
            return str(self._conversation_service().resolve(reference).get("id") or "")
        conversation_id = str(context.invocation_conversation_id or "").strip()
        if not conversation_id:
            raise ConversationLifecycleError("CONVERSATION_TARGET_REQUIRED", "Name the conversation to update.")
        return str(self._conversation_service().get(conversation_id).get("id") or "")

    @staticmethod
    def _expected_target_revision(arguments: dict[str, Any]) -> int | None:
        expected = arguments.get("target_revision")
        if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int)):
            raise ValueError("target_revision must be an integer.")
        return expected

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

    @staticmethod
    def _conversation_definitions() -> list[AppActionDefinition]:
        reference = {"reference": {"type": "string"}}
        specs = [
            (CONVERSATION_NEW_ACTION_ID, "Start a new chat", "Prepare an empty chat workspace.", False, True, "none", {}),
            (CONVERSATION_OPEN_ACTION_ID, "Open a chat", "Open an existing conversation.", False, True, "none", {"conversation_id": {"type": "string"}, "reference": {"type": "string"}}),
            (CONVERSATION_PIN_ACTION_ID, "Pin a chat", "Pin a conversation in the sidebar.", True, True, "none", {"conversation_id": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_UNPIN_ACTION_ID, "Unpin a chat", "Remove a conversation from the pinned group.", True, True, "none", {"conversation_id": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_RENAME_ACTION_ID, "Rename a chat", "Change a conversation title.", True, False, "none", {"conversation_id": {"type": "string"}, "title": {"type": "string", "minLength": 1, "maxLength": 160}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_SPACE_ACTION_ID, "Change chat Space", "Move a conversation to a Space.", True, False, "none", {"conversation_id": {"type": "string"}, "assignment": {"enum": ["automatic", "manual"]}, "space_id": {"type": "string"}, "space_label": {"type": "string"}, "topic_id": {"type": "string"}, "topic_label": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_ARCHIVE_ACTION_ID, "Archive a chat", "Move a conversation to the archive.", True, True, "none", {"conversation_id": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_RESTORE_ACTION_ID, "Restore a chat", "Restore an archived conversation.", True, True, "none", {"conversation_id": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_DELETE_ACTION_ID, "Delete a chat", "Permanently delete a conversation and its canonical runtime state.", False, True, "operation_bound", {"conversation_id": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
        ]
        return [
            AppActionDefinition(
                id=action_id,
                version="1",
                owner="conversation-lifecycle",
                title=title,
                description=description,
                scope="conversation",
                access_class=(CapabilityAccess.DESTRUCTIVE.value if action_id == CONVERSATION_DELETE_ACTION_ID else CapabilityAccess.WRITE.value),
                confirmation_rule=confirmation_rule,
                executor_location="client" if action_id in {CONVERSATION_NEW_ACTION_ID, CONVERSATION_OPEN_ACTION_ID} else "server",
                supports_undo=supports_undo,
                idempotent=idempotent,
                argument_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                },
                result_schema={"type": "object"},
                ui_reference="conversation",
                audit_label=action_id.replace("conversation.", "conversation.lifecycle."),
            )
            for action_id, title, description, supports_undo, idempotent, confirmation_rule, properties in specs
        ]

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

    def _authorization(
        self,
        access_class: str,
        context: AppActionContext,
        *,
        allowed: bool,
        confirmation_required: bool = False,
    ) -> ActionAuthorization:
        return ActionAuthorization(
            decision="allowed" if allowed else "denied", access_class=access_class,
            confirmation_required=confirmation_required, agent_name=self._agent_name(context),
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
