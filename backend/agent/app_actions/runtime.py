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
    DeviceSettingsSnapshot,
    SurfacePresentation,
    UISurfaceDefinition,
    WorkspaceLayoutSnapshot,
)
from agent.app_actions.attachments import AttachmentImportError
from agent.app_actions.automations import (
    AUTOMATION_ACTION_IDS,
    AUTOMATION_CREATE_ACTION_ID,
    AUTOMATION_HISTORY_ACTION_ID,
    AUTOMATION_PAUSE_ACTION_ID,
    AUTOMATION_REMOVE_ACTION_ID,
    AUTOMATION_RESUME_ACTION_ID,
    AUTOMATION_RUN_ACTION_ID,
    AUTOMATION_UPDATE_ACTION_ID,
    AutomationActionError,
    automation_action_definitions,
)
from agent.app_actions.coding_github import (
    CODING_GITHUB_ACTION_IDS,
    CODING_WORKSPACE_OPEN_ACTION_ID,
    GITHUB_PULL_REQUEST_CREATE_ACTION_ID,
    GITHUB_PULL_REQUEST_OPEN_ACTION_ID,
    CodingGitHubActionError,
    coding_github_action_definitions,
)
from agent.app_actions.session_controls import (
    AGENT_SELECT_ACTION_ID,
    MEMORY_CONVERSATION_SET_ACTION_ID,
    MODEL_SELECT_ACTION_ID,
    REASONING_SET_ACTION_ID,
    SessionControlError,
)
from agent.app_actions.settings_runtime import (
    CONFIRMED_SETTINGS_RUNTIME_ACTION_IDS,
    DEFAULT_MODEL_SET_ACTION_ID,
    DEVICE_SETTINGS_UPDATE_ACTION_ID,
    MEMORY_SETTINGS_UPDATE_ACTION_ID,
    MEMORY_ENTRY_ARCHIVE_ACTION_ID,
    MEMORY_ENTRY_CREATE_ACTION_ID,
    MEMORY_ENTRY_DELETE_ACTION_ID,
    MEMORY_ENTRY_PIN_ACTION_ID,
    MEMORY_ENTRY_UPDATE_ACTION_ID,
    MEMORY_DREAMING_RUN_ACTION_ID,
    MEMORY_CONVERSATIONS_IMPORT_ACTION_ID,
    MEMORY_OBSIDIAN_IMPORT_ACTION_ID,
    PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
    ROUTING_CREDENTIAL_ADD_ACTION_ID,
    ROUTING_CREDENTIAL_REMOVE_ACTION_ID,
    ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
    ROUTING_FALLBACKS_SET_ACTION_ID,
    ROUTING_POLICY_SET_ACTION_ID,
    ROUTING_MODEL_POLICY_REMOVE_ACTION_ID,
    ROUTING_POOL_RESET_ACTION_ID,
    SETTINGS_RUNTIME_ACTION_IDS,
    SettingsRuntimeActionError,
    settings_runtime_action_definitions,
)
from agent.app_actions.lifecycle_controls import (
    LIFECYCLE_CONTROL_ACTION_IDS,
    PLUGIN_STATE_SET_ACTION_ID,
    SKILL_MUTATION_APPROVE_ACTION_ID,
    SKILL_MUTATION_REJECT_ACTION_ID,
    SKILL_MUTATION_SUBMIT_ACTION_ID,
    SKILL_UNINSTALL_ACTION_ID,
    LifecycleControlError,
    lifecycle_action_definitions,
)
from agent.app_actions.knowledge_sources import (
    BOOK_COMPILE_ACTION_ID,
    BOOK_IMPORT_ACTION_ID,
    BOOK_PROCESS_ACTION_ID,
    KNOWLEDGE_INDEX_REBUILD_ACTION_ID,
    KNOWLEDGE_SOURCE_ACTION_IDS,
    KNOWLEDGE_SOURCE_CONFIRMED_ACTION_IDS,
    KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
    KnowledgeSourceActionError,
    knowledge_source_action_definitions,
)
from agent.app_actions.observability import (
    OBSERVABILITY_ACTION_IDS,
    OBSERVABILITY_OPEN_ACTION_ID,
    OBSERVABILITY_REFRESH_ACTION_ID,
    OBSERVABILITY_STATUS_ACTION_ID,
    OBSERVABILITY_STREAM_SET_ACTION_ID,
    ObservabilityActionError,
    observability_action_definitions,
)
from agent.app_actions.petdex import (
    PETDEX_ACTION_IDS,
    PETDEX_ACTIVE_SET_ACTION_ID,
    PETDEX_INSTALL_ACTION_ID,
    PETDEX_POSITION_SET_ACTION_ID,
    PETDEX_REMOVE_ACTION_ID,
    PETDEX_SIZE_SET_ACTION_ID,
    PETDEX_VISIBILITY_SET_ACTION_ID,
    PetdexActionError,
    execute_petdex_action,
    petdex_action_definitions,
)
from agent.conversations.lifecycle import ConversationLifecycle, ConversationLifecycleError
from agent.conversations.sharing import ConversationShareError, ConversationShareService
from agent.plugins.contributions import (
    PluginContribution,
    PluginContributionActionError,
    PluginContributionCatalog,
)
from agent.plugins.registry import PluginRegistry
from agent.plugins.youtube_contract import (
    YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
    YOUTUBE_CONNECTION_START_ACTION_ID,
    YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
    YOUTUBE_SYNC_ACTION_ID,
)
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
CONVERSATION_FORK_ACTION_ID = "conversation.fork"
CONVERSATION_WINDOW_OPEN_ACTION_ID = "conversation.window.open"
CONVERSATION_SHARE_ACTION_ID = "conversation.share"
ATTACHMENT_IMPORT_ACTION_ID = "composer.attachment.import"
SESSION_CONTROL_ACTION_IDS = frozenset({
    AGENT_SELECT_ACTION_ID,
    MODEL_SELECT_ACTION_ID,
    REASONING_SET_ACTION_ID,
    MEMORY_CONVERSATION_SET_ACTION_ID,
})
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
    target_kind: str
    target_reference: str
    expected_revision: int
    expires_at: datetime
    binding: dict[str, Any] | None = None


@dataclass(frozen=True)
class AppActionTurn:
    """The actions and conversational work found in one submitted turn."""

    actions: tuple[AppActionRequest, ...] = ()
    conversation_message: str = ""

    @property
    def is_mixed(self) -> bool:
        return bool(self.actions and self.conversation_message)


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
        conversation_sharing: ConversationShareService | Callable[[], ConversationShareService] | None = None,
        attachment_importer: Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]] | None = None,
        session_control_handler: Callable[[str, dict[str, Any], AppActionContext], dict[str, Any]] | None = None,
        settings_runtime_handler: Callable[..., dict[str, Any]] | None = None,
        lifecycle_control_handler: Callable[[str, dict[str, Any], AppActionContext, bool], dict[str, Any]] | None = None,
        observability_handler: Callable[[str, dict[str, Any], AppActionContext], dict[str, Any]] | None = None,
        coding_github_handler: Callable[..., dict[str, Any]] | None = None,
        automation_handler: Callable[..., dict[str, Any]] | None = None,
        knowledge_source_handler: Callable[..., dict[str, Any]] | None = None,
        plugin_registry: PluginRegistry | None = None,
        action_availability: Callable[[AppActionDefinition, AppActionContext | None], bool] | None = None,
    ) -> None:
        self._receipt_store = receipt_store or InMemoryReceiptStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._receipt_id_factory = receipt_id_factory or (lambda: f"receipt_{uuid4().hex}")
        self._undo_token_factory = undo_token_factory or (lambda: secrets.token_urlsafe(24))
        self._confirmation_token_factory = confirmation_token_factory or (lambda: secrets.token_urlsafe(24))
        self._conversation_lifecycle = conversation_lifecycle
        self._conversation_sharing = conversation_sharing
        self._attachment_importer = attachment_importer
        self._session_control_handler = session_control_handler
        self._settings_runtime_handler = settings_runtime_handler
        self._lifecycle_control_handler = lifecycle_control_handler
        self._observability_handler = observability_handler
        self._coding_github_handler = coding_github_handler
        self._automation_handler = automation_handler
        self._knowledge_source_handler = knowledge_source_handler
        self._action_availability = action_availability or (lambda _definition, _context: True)
        self._conversation_actions_registered = False
        self._registry = ToolRegistry()
        self._surfaces = {surface.reference: surface for surface in self._surface_definitions()}
        self._definitions = {
            definition.id: definition
            for definition in (
                self._sidebar_definition(),
                self._surface_action_definition(),
                self._reset_definition(),
                self._attachment_definition(),
                *self._session_control_definitions(),
                *settings_runtime_action_definitions(),
                *self._conversation_definitions(),
                *lifecycle_action_definitions(),
                *observability_action_definitions(),
                *coding_github_action_definitions(),
                *automation_action_definitions(),
                *knowledge_source_action_definitions(),
                *petdex_action_definitions(),
            )
        }
        self._plugin_contributions = (
            PluginContributionCatalog(
                plugins=plugin_registry,
                capabilities=self._registry,
                reserved_action_ids=set(self._definitions),
                reserved_surface_references=set(self._surfaces),
                control_kernel_references={
                    reference
                    for reference, surface in self._surfaces.items()
                    if surface.control_kernel
                },
            )
            if plugin_registry is not None
            else None
        )
        self._register(SIDEBAR_ACTION_ID, "Change sidebar visibility", self._set_sidebar)
        self._register(SURFACE_ACTION_ID, "Customize interface presentation", self._configure_surface)
        self._register(WORKSPACE_RESET_ACTION_ID, "Reset interface presentation", self._reset_workspace)
        for action_id in LIFECYCLE_CONTROL_ACTION_IDS:
            definition = self._definitions[action_id]
            self._register(
                action_id,
                definition.title,
                lambda payload, registered_action_id=action_id: self._invoke_lifecycle_control(
                    registered_action_id,
                    payload,
                ),
                access=CapabilityAccess(definition.access_class),
            )
        for action_id in SETTINGS_RUNTIME_ACTION_IDS:
            definition = self._definitions[action_id]
            self._register(
                action_id,
                definition.title,
                lambda payload, registered_action_id=action_id: self._invoke_settings_runtime(
                    registered_action_id,
                    payload,
                ),
                access=CapabilityAccess(definition.access_class),
            )
        for action_id in OBSERVABILITY_ACTION_IDS:
            definition = self._definitions[action_id]
            self._register(
                action_id,
                definition.title,
                lambda payload, registered_action_id=action_id: self._invoke_observability(
                    registered_action_id,
                    payload,
                ),
                access=CapabilityAccess(definition.access_class),
            )
        for action_id in CODING_GITHUB_ACTION_IDS:
            definition = self._definitions[action_id]
            self._register(
                action_id,
                definition.title,
                lambda payload, registered_action_id=action_id: self._invoke_coding_github(
                    registered_action_id,
                    payload,
                ),
                access=CapabilityAccess(definition.access_class),
            )
        for action_id in AUTOMATION_ACTION_IDS:
            definition = self._definitions[action_id]
            self._register(
                action_id,
                definition.title,
                lambda payload, registered_action_id=action_id: self._invoke_automation(
                    registered_action_id,
                    payload,
                ),
                access=CapabilityAccess(definition.access_class),
            )
        for action_id in KNOWLEDGE_SOURCE_ACTION_IDS:
            definition = self._definitions[action_id]
            self._register(
                action_id,
                definition.title,
                lambda payload, registered_action_id=action_id: self._invoke_knowledge_source(
                    registered_action_id,
                    payload,
                ),
                access=CapabilityAccess(definition.access_class),
            )
        if self._conversation_lifecycle is not None:
            self.set_conversation_lifecycle_provider(self._conversation_lifecycle)

    def set_attachment_importer(
        self,
        importer: Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]],
    ) -> None:
        self._attachment_importer = importer

    def set_session_control_handler(
        self,
        handler: Callable[[str, dict[str, Any], AppActionContext], dict[str, Any]],
    ) -> None:
        self._session_control_handler = handler

    def set_settings_runtime_handler(
        self,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        self._settings_runtime_handler = handler

    def set_lifecycle_control_handler(
        self,
        handler: Callable[[str, dict[str, Any], AppActionContext, bool], dict[str, Any]],
    ) -> None:
        self._lifecycle_control_handler = handler

    def set_observability_handler(
        self,
        handler: Callable[[str, dict[str, Any], AppActionContext], dict[str, Any]],
    ) -> None:
        self._observability_handler = handler

    def set_coding_github_handler(
        self,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        self._coding_github_handler = handler

    def set_automation_handler(
        self,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        self._automation_handler = handler

    def set_knowledge_source_handler(
        self,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        self._knowledge_source_handler = handler

    def register_plugin_contribution(self, contribution: PluginContribution) -> None:
        if self._plugin_contributions is None:
            raise RuntimeError("Plugin contributions require a PluginRegistry")
        self._plugin_contributions.register(contribution)

    def plugin_contribution_diagnostics(self) -> list[dict[str, str]]:
        if self._plugin_contributions is None:
            return []
        return [diagnostic.__dict__.copy() for diagnostic in self._plugin_contributions.diagnostics()]

    def plugin_contribution_summary(self, plugin_id: str) -> dict[str, list[dict[str, Any]]]:
        if self._plugin_contributions is None:
            return {"app_actions": [], "ui_surfaces": []}
        return self._plugin_contributions.summary(plugin_id)

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
        contributed_actions = self._plugin_contributions.actions(context) if self._plugin_contributions else []
        surfaces = self._surface_map(context)
        return AppActionCatalog(
            actions=[
                definition
                for definition in [*self._definitions.values(), *contributed_actions]
                if self._is_available(definition, context)
            ],
            surfaces=list(surfaces.values()),
        )

    def plan_submission(self, message: str) -> AppActionTurn:
        """Separate explicitly submitted App Actions from conversational work."""

        submitted = " ".join(str(message or "").strip().split())
        if not submitted:
            return AppActionTurn()
        exact = self.match_submission(submitted)
        clauses = self._split_mixed_clauses(submitted)
        if len(clauses) >= 2:
            actions: list[AppActionRequest] = []
            conversation_clauses: list[str] = []
            for clause in clauses:
                request = self.match_submission(clause)
                if request is None:
                    conversation_clauses.append(clause)
                else:
                    actions.append(request)
            if actions and self._is_confident_mixed_submission(
                submitted,
                actions=actions,
                conversation_clauses=conversation_clauses,
                exact=exact,
            ):
                return AppActionTurn(
                    actions=tuple(actions),
                    conversation_message=" and ".join(conversation_clauses),
                )
        if exact is not None:
            return AppActionTurn(actions=(exact,))
        return AppActionTurn(conversation_message=submitted)

    @classmethod
    def _is_confident_mixed_submission(
        cls,
        submitted: str,
        *,
        actions: list[AppActionRequest],
        conversation_clauses: list[str],
        exact: AppActionRequest | None,
    ) -> bool:
        if not conversation_clauses or exact is None or len(actions) > 1:
            return True
        if cls._has_unquoted_explicit_separator(submitted):
            return True
        return all(cls._looks_like_conversation_clause(clause) for clause in conversation_clauses)

    @staticmethod
    def _looks_like_conversation_clause(clause: str) -> bool:
        normalized = clause.strip().casefold()
        if normalized.endswith("?"):
            return True
        return re.match(
            r"(?:please\s+)?(?:"
            r"tell|explain|summarize|describe|answer|reply|write|draft|brainstorm|compare|analyze|analyse|"
            r"research|find|search|look|show|give|list|recommend|calculate|translate|help|"
            r"what|what's|whats|who|whose|when|where|why|how|is|are|can|could|would|should|do|does"
            r")\b",
            normalized,
        ) is not None

    @staticmethod
    def _has_unquoted_explicit_separator(submitted: str) -> bool:
        normalized = submitted.casefold()
        quote = ""
        index = 0
        while index < len(submitted):
            character = submitted[index]
            if character in {"'", '"'}:
                if (
                    character == "'"
                    and index > 0
                    and index + 1 < len(submitted)
                    and submitted[index - 1].isalnum()
                    and submitted[index + 1].isalnum()
                ):
                    index += 1
                    continue
                quote = "" if quote == character else (character if not quote else quote)
                index += 1
                continue
            if not quote and (
                character in {",", ";"}
                or normalized.startswith(" and then ", index)
                or normalized.startswith(" then ", index)
            ):
                return True
            index += 1
        return False

    def _is_available(
        self,
        definition: AppActionDefinition,
        context: AppActionContext | None,
    ) -> bool:
        if self._plugin_contributions and self._plugin_contributions.has_action(definition.id):
            return self._plugin_contributions.action_available(definition.id, context)
        if definition.id in SESSION_CONTROL_ACTION_IDS and self._session_control_handler is None:
            return False
        if definition.id in SETTINGS_RUNTIME_ACTION_IDS and self._settings_runtime_handler is None:
            return False
        if definition.id in LIFECYCLE_CONTROL_ACTION_IDS and self._lifecycle_control_handler is None:
            return False
        if definition.id in OBSERVABILITY_ACTION_IDS and self._observability_handler is None:
            return False
        if definition.id in CODING_GITHUB_ACTION_IDS and self._coding_github_handler is None:
            return False
        if definition.id in AUTOMATION_ACTION_IDS and self._automation_handler is None:
            return False
        if definition.id in KNOWLEDGE_SOURCE_ACTION_IDS and self._knowledge_source_handler is None:
            return False
        return bool(self._action_availability(definition, context))

    def _definition(self, action_id: str) -> AppActionDefinition | None:
        definition = self._definitions.get(action_id)
        if definition is not None or self._plugin_contributions is None:
            return definition
        return self._plugin_contributions.action_definition(action_id)

    def _surface_map(
        self,
        context: AppActionContext | None = None,
    ) -> dict[str, UISurfaceDefinition]:
        surfaces = dict(self._surfaces)
        if self._plugin_contributions is not None:
            surfaces.update({
                surface.reference: surface
                for surface in self._plugin_contributions.surfaces(context)
            })
        return surfaces

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

        device_appearance = re.fullmatch(
            polite + r"(?:change|set|switch)\s+(?:the\s+|my\s+)?(background|accent(?:\s+palette)?|dock\s+position)\s+to\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if device_appearance:
            kind = device_appearance.group(1).casefold()
            key = "background" if kind == "background" else "accent" if kind.startswith("accent") else "dock_position"
            value = self._spoken_value(device_appearance.group(2)).casefold().replace(" ", "-")
            if key == "background":
                value = {"gold-rays": "god-rays"}.get(value, value)
            elif key == "accent":
                value = {
                    "vellum": "default",
                    "eucalyptus-grove": "eucalyptus",
                    "under-the-moonlight": "moonlight",
                    "the-matrix": "matrix",
                }.get(value, value)
            return AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {key: value}},
            )

        dock_visibility = re.fullmatch(
            polite + r"(?:keep|make)\s+(?:the\s+)?dock\s+(always\s+)?visible|(?:unlock|hide)\s+(?:the\s+)?dock",
            normalized,
        )
        if dock_visibility:
            return AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"dock_locked": not normalized.startswith(("unlock", "hide"))}},
            )

        personalization_choice = re.fullmatch(
            polite
            + r"set\s+(?:my\s+)?(base style|warmth|enthusiasm|headers|emoji)\s+to\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if personalization_choice:
            key = {
                "base style": "baseStyle",
                "warmth": "warm",
                "enthusiasm": "enthusiastic",
                "headers": "headers",
                "emoji": "emoji",
            }[personalization_choice.group(1).casefold()]
            return AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={
                    "patch": {
                        "personalization": {
                            key: self._spoken_value(personalization_choice.group(2)).casefold()
                        }
                    }
                },
            )

        personalization_toggle = re.fullmatch(
            polite
            + r"(?:turn|switch|set)\s+(fast answers|record history|web search|canvas|voice|advanced voice|connector search)\s+(on|off)",
            normalized,
        )
        if personalization_toggle:
            key = {
                "fast answers": "fastAnswers",
                "record history": "recordHist",
                "web search": "webSearch",
                "canvas": "canvas",
                "voice": "voice",
                "advanced voice": "advVoice",
                "connector search": "connector",
            }[personalization_toggle.group(1)]
            return AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"personalization": {key: personalization_toggle.group(2) == "on"}}},
            )

        personalization_text = re.fullmatch(
            polite + r"set\s+(?:my\s+)?(nickname|occupation|about me|custom instructions)\s+to\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if personalization_text:
            key = {
                "nickname": "nickname",
                "occupation": "occupation",
                "about me": "about",
                "custom instructions": "custom",
            }[personalization_text.group(1).casefold()]
            return AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"personalization": {key: self._spoken_value(personalization_text.group(2))}}},
            )

        computer_preview = re.fullmatch(
            polite + r"(?:enable|disable|turn\s+(on|off))\s+(?:the\s+)?computer use preview",
            normalized,
        )
        if computer_preview:
            enabled = normalized.startswith("enable") or computer_preview.group(1) == "on"
            return AppActionRequest(
                action_id=DEVICE_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"computer_use_preview": enabled}},
            )

        default_model = re.fullmatch(
            polite + r"(?:use|select|switch(?:\s+over)?\s+to|change|set)\s+(?:the\s+)?default\s+model(?:\s+to)?\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if default_model:
            model = self._spoken_value(default_model.group(1))
            if model:
                return AppActionRequest(action_id=DEFAULT_MODEL_SET_ACTION_ID, arguments={"model": model})

        global_memory = re.fullmatch(
            polite
            + r"(?:turn|switch|set)\s+(?:the\s+)?(?:global\s+|all\s+)?memory\s+(on|off)"
            + r"(?:\s+(?:globally|everywhere|for\s+all\s+(?:chats|conversations)))?",
            normalized,
        )
        if global_memory and any(marker in normalized for marker in ("global", "everywhere", "all chat", "all conversation")):
            return AppActionRequest(
                action_id=MEMORY_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {"memory_enabled": global_memory.group(1) == "on"}},
            )

        memory_setting = re.fullmatch(
            polite
            + r"(?:turn|switch|set)\s+(?:the\s+)?"
            + r"(reference history|dreaming|saving new memories|auto archive|using archived memories)\s+(on|off)",
            normalized,
        )
        if memory_setting:
            key = {
                "reference history": "reference_history_enabled",
                "dreaming": "dreaming_enabled",
                "saving new memories": "save_new_memories",
                "auto archive": "auto_archive_enabled",
                "using archived memories": "use_archived_memories",
            }[memory_setting.group(1)]
            return AppActionRequest(
                action_id=MEMORY_SETTINGS_UPDATE_ACTION_ID,
                arguments={"patch": {key: memory_setting.group(2) == "on"}},
            )

        remember_explicit = re.fullmatch(
            polite + r"(?:remember|save as (?:a )?memory)(?:\s+that)?\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if remember_explicit:
            return AppActionRequest(
                action_id=MEMORY_ENTRY_CREATE_ACTION_ID,
                arguments={"text": self._spoken_value(remember_explicit.group(1)), "kind": "manual", "scope": "global"},
            )

        memory_update = re.fullmatch(
            polite + r"update\s+memory\s+#?(\d+)\s+to\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if memory_update:
            return AppActionRequest(
                action_id=MEMORY_ENTRY_UPDATE_ACTION_ID,
                arguments={"memory_id": int(memory_update.group(1)), "text": self._spoken_value(memory_update.group(2))},
            )

        memory_pin = re.fullmatch(
            polite + r"(pin|unpin)\s+memory\s+#?(\d+)",
            normalized,
        )
        if memory_pin:
            return AppActionRequest(
                action_id=MEMORY_ENTRY_PIN_ACTION_ID,
                arguments={"memory_id": int(memory_pin.group(2)), "pinned": memory_pin.group(1) == "pin"},
            )

        memory_archive = re.fullmatch(polite + r"archive\s+memory\s+#?(\d+)", normalized)
        if memory_archive:
            return AppActionRequest(
                action_id=MEMORY_ENTRY_ARCHIVE_ACTION_ID,
                arguments={"memory_id": int(memory_archive.group(1))},
            )

        memory_delete = re.fullmatch(polite + r"delete\s+memory\s+#?(\d+)", normalized)
        if memory_delete:
            return AppActionRequest(
                action_id=MEMORY_ENTRY_DELETE_ACTION_ID,
                arguments={"memory_id": int(memory_delete.group(1))},
            )

        if re.fullmatch(
            polite
            + r"(?:(?:run|start)\s+(?:memory\s+)?dreaming|dream\s+(?:about\s+)?(?:my\s+)?(?:chats|memories)\s+now)",
            normalized,
        ):
            return AppActionRequest(action_id=MEMORY_DREAMING_RUN_ACTION_ID)

        memory_import = re.fullmatch(
            polite
            + r"import\s+(?:my\s+)?(?:old\s+|existing\s+|past\s+)?(?:chats|conversations)\s+(?:into|to)\s+memory"
            + r"(?:\s+limit\s+(\d+))?",
            normalized,
        )
        if memory_import:
            arguments = {"limit": int(memory_import.group(1))} if memory_import.group(1) else {}
            return AppActionRequest(action_id=MEMORY_CONVERSATIONS_IMPORT_ACTION_ID, arguments=arguments)

        provider_credential = re.fullmatch(
            polite
            + r"(?:configure|connect|set|update|change|replace)\s+(?:my\s+|the\s+)?"
            + r"(openrouter|openai|anthropic|google)(?:\s+api)?\s+key(?:\s+to\s+.+)?",
            normalized,
        )
        if provider_credential:
            return AppActionRequest(
                action_id=PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID,
                arguments={"provider": provider_credential.group(1)},
            )

        routing_sort = re.fullmatch(
            polite + r"(?:sort|route)\s+(?:llm\s+|model\s+|inference\s+)?providers?\s+by\s+(price|latency|throughput)",
            normalized,
        )
        if routing_sort:
            return AppActionRequest(
                action_id=ROUTING_POLICY_SET_ACTION_ID,
                arguments={"sort": routing_sort.group(1)},
            )

        routing_fallback_toggle = re.fullmatch(
            polite + r"(?:turn|set|switch)\s+(?:provider\s+|model\s+)?fallbacks\s+(on|off)",
            normalized,
        )
        if routing_fallback_toggle:
            return AppActionRequest(
                action_id=ROUTING_POLICY_SET_ACTION_ID,
                arguments={"allow_fallbacks": routing_fallback_toggle.group(1) == "on"},
            )

        if re.fullmatch(polite + r"(?:clear|remove)\s+(?:all\s+)?(?:model\s+)?fallbacks", normalized):
            return AppActionRequest(action_id=ROUTING_FALLBACKS_SET_ACTION_ID, arguments={"models": []})

        routing_fallbacks = re.fullmatch(
            polite + r"(?:set|replace)\s+(?:the\s+)?(?:model\s+)?fallbacks(?:\s+to|\s+with)\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if routing_fallbacks:
            models = [self._spoken_value(value) for value in re.split(r"\s*,\s*|\s+and\s+", routing_fallbacks.group(1))]
            return AppActionRequest(
                action_id=ROUTING_FALLBACKS_SET_ACTION_ID,
                arguments={"models": [model for model in models if model]},
            )

        credential_strategy = re.fullmatch(
            polite
            + r"set\s+(?:(openrouter|openai)\s+)?credential\s+strategy\s+to\s+"
            + r"(fill[ _-]?first|round[ _-]?robin|least[ _-]?used|random)",
            normalized,
        )
        if credential_strategy:
            return AppActionRequest(
                action_id=ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
                arguments={
                    "provider": credential_strategy.group(1) or "openrouter",
                    "strategy": credential_strategy.group(2).replace("-", "_").replace(" ", "_"),
                },
            )

        credential_pool_reset = re.fullmatch(
            polite + r"reset\s+(?:(openrouter|openai)\s+)?credential\s+pool",
            normalized,
        )
        if credential_pool_reset:
            return AppActionRequest(
                action_id=ROUTING_POOL_RESET_ACTION_ID,
                arguments={"provider": credential_pool_reset.group(1) or "openrouter"},
            )

        agent_selection = re.fullmatch(
            polite
            + r"(?:open|use|select|switch(?:\s+over)?\s+to|change(?:\s+over)?\s+to|go\s+to)\s+"
            + r"(?:the\s+)?(?:(vellum|x|twitter|youtube|sports|books|research|memory)(?:\s+agent)?|(.+?)\s+agent)",
            normalized,
        )
        if agent_selection:
            return AppActionRequest(
                action_id=AGENT_SELECT_ACTION_ID,
                arguments={"agent": agent_selection.group(1) or agent_selection.group(2)},
            )

        model_selection = re.fullmatch(
            polite
            + r"(?:use|select|switch(?:\s+over)?\s+to|change(?:\s+the)?\s+model\s+to|set(?:\s+the)?\s+model\s+to)\s+"
            + r"(?:the\s+)?(?:model\s+)?(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if model_selection and re.search(r"\bmodel\b", normalized):
            model = self._spoken_value(model_selection.group(1))
            if model:
                return AppActionRequest(action_id=MODEL_SELECT_ACTION_ID, arguments={"model": model})

        reasoning_selection = re.fullmatch(
            polite
            + r"(?:use|set|change(?:\s+the)?)(?:\s+reasoning)?(?:\s+(?:mode|level))?(?:\s+to)?\s+"
            + r"(light|medium|high|extra high|max|ultra|default|standard|off)(?:\s+reasoning)?",
            normalized,
        )
        if reasoning_selection and "reason" in normalized:
            return AppActionRequest(
                action_id=REASONING_SET_ACTION_ID,
                arguments={"mode": reasoning_selection.group(1)},
            )

        memory_selection = re.fullmatch(
            polite
            + r"(?:turn|switch|set)\s+(?:the\s+)?memory\s+(on|off)"
            + r"(?:\s+for\s+(?:(?:this|the current)\s+)?(?:chat|conversation))?",
            normalized,
        )
        if memory_selection:
            return AppActionRequest(
                action_id=MEMORY_CONVERSATION_SET_ACTION_ID,
                arguments={"enabled": memory_selection.group(1) == "on"},
            )
        if re.fullmatch(
            polite + r"(?:do not|don't|dont|stop)\s+(?:save|store|remember)(?:ing)?\s+(?:this\s+)?(?:chat|conversation)(?:\s+(?:to|in)\s+memory)?",
            normalized,
        ):
            return AppActionRequest(
                action_id=MEMORY_CONVERSATION_SET_ACTION_ID,
                arguments={"enabled": False},
            )

        if re.fullmatch(polite + r"(?:connect|reconnect)\s+(?:my\s+)?youtube(?:\s+account)?", normalized):
            return AppActionRequest(action_id=YOUTUBE_CONNECTION_START_ACTION_ID)
        if re.fullmatch(polite + r"(?:sync|synchronize|refresh)\s+(?:my\s+)?youtube(?:\s+(?:subscriptions|account|data))?", normalized):
            return AppActionRequest(action_id=YOUTUBE_SYNC_ACTION_ID)
        if re.fullmatch(polite + r"disconnect\s+(?:my\s+)?youtube(?:\s+account)?", normalized):
            return AppActionRequest(action_id=YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID)
        youtube_rebuild = re.fullmatch(
            polite + r"rebuild\s+(?:my\s+)?youtube\s+intelligence(?:\s+(incrementally|from scratch))?",
            normalized,
        )
        if youtube_rebuild:
            mode = "incremental" if youtube_rebuild.group(1) == "incrementally" else "backfill" if youtube_rebuild.group(1) else ""
            return AppActionRequest(
                action_id=YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
                arguments={"mode": mode} if mode else {},
            )

        if re.fullmatch(polite + r"(?:rebuild|refresh)\s+(?:the\s+)?knowledge\s+index", normalized):
            return AppActionRequest(action_id=KNOWLEDGE_INDEX_REBUILD_ACTION_ID)
        if re.fullmatch(polite + r"(?:import|add)\s+(?:a\s+|an\s+)?(?:epub|book)(?:\s+file)?", normalized):
            return AppActionRequest(action_id=BOOK_IMPORT_ACTION_ID)
        book_process = re.fullmatch(
            polite + r"process\s+(?:the\s+)?(?:epub|book)\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if book_process:
            return AppActionRequest(
                action_id=BOOK_PROCESS_ACTION_ID,
                arguments={"reference": self._spoken_value(book_process.group(1))},
            )
        book_compile = re.fullmatch(
            polite + r"(?:build|compile)\s+(?:the\s+)?book\s+(?:skill|knowledge)(?:\s+for)?\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if book_compile:
            return AppActionRequest(
                action_id=BOOK_COMPILE_ACTION_ID,
                arguments={"reference": self._spoken_value(book_compile.group(1))},
            )
        source_import = re.fullmatch(
            polite + r"import\s+(?:the\s+)?knowledge\s+source(?:\s+at|\s+from)?\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if source_import:
            return AppActionRequest(
                action_id=KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
                arguments={"source_path": self._spoken_value(source_import.group(1))},
            )

        coding_workspace = re.fullmatch(
            polite
            + r"(?:open|show|go\s+to|switch\s+to)\s+(?:the\s+)?coding(?:\s+(?:workspace|room))?",
            normalized,
        )
        if coding_workspace:
            return AppActionRequest(action_id=CODING_WORKSPACE_OPEN_ACTION_ID)

        coding_conversation = re.fullmatch(
            polite
            + r"(?:open|show|go\s+to)\s+(?:the\s+)?coding\s+(?:conversation|session)\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if coding_conversation:
            reference = self._spoken_value(coding_conversation.group(1))
            if reference:
                return AppActionRequest(
                    action_id=CODING_WORKSPACE_OPEN_ACTION_ID,
                    arguments={"session": reference},
                )

        pull_request_read = re.fullmatch(
            polite
            + r"(open|inspect|show|view)\s+(?:(?:the\s+)?(?:github\s+)?(?:pull request|pr))\s+#?(\d+)"
            + r"(?:\s+(?:in|from|on)\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?",
            normalized,
        )
        if pull_request_read:
            arguments: dict[str, Any] = {
                "pull_number": int(pull_request_read.group(2)),
                "open": pull_request_read.group(1) == "open",
            }
            if pull_request_read.group(3):
                arguments["repository"] = pull_request_read.group(3)
            return AppActionRequest(action_id=GITHUB_PULL_REQUEST_OPEN_ACTION_ID, arguments=arguments)

        pull_request_create = re.fullmatch(
            polite
            + r"(create|draft|make)\s+(?:a\s+|the\s+)?(draft\s+)?(?:github\s+)?(?:pull request|pr)"
            + r"(?:\s+(?:titled|called|named)\s+(.+))?",
            submitted,
            flags=re.IGNORECASE,
        )
        if pull_request_create:
            arguments = {
                "draft": pull_request_create.group(1).casefold() == "draft" or bool(pull_request_create.group(2))
            }
            title = self._spoken_value(pull_request_create.group(3) or "")
            if title:
                arguments["title"] = title
            return AppActionRequest(action_id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID, arguments=arguments)

        automation_create = re.fullmatch(
            polite
            + r"(?:create|add|schedule)\s+(?:a\s+|an\s+)?(?:automation|scheduled task)\s+"
            + r"(?:called|named)\s+(.+?)\s+(?:to|with instructions?\s+to?)\s+(.+?)\s+"
            + r"((?:every|in)\s+.+|\d{1,2}\s+\d{1,2}\s+\S+\s+\S+\s+\S+|\d{4}-\d{2}-\d{2}T\S+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if automation_create:
            return AppActionRequest(
                action_id=AUTOMATION_CREATE_ACTION_ID,
                arguments={
                    "name": self._spoken_value(automation_create.group(1)),
                    "instructions": self._spoken_value(automation_create.group(2)),
                    "schedule": self._spoken_value(automation_create.group(3)),
                    "destination": {"kind": "new_chat"},
                    "permission": {"full_access": False},
                },
            )

        automation_update = re.fullmatch(
            polite
            + r"(?:update|change|set)\s+(?:the\s+)?(?:automation|scheduled task)\s+(.+?)\s+"
            + r"(schedule|instructions?|description|name)\s+to\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if automation_update:
            field = automation_update.group(2).casefold()
            field = "instructions" if field.startswith("instruction") else field
            return AppActionRequest(
                action_id=AUTOMATION_UPDATE_ACTION_ID,
                arguments={
                    "reference": self._spoken_value(automation_update.group(1)),
                    field: self._spoken_value(automation_update.group(3)),
                },
            )

        automation_history = re.fullmatch(
            polite
            + r"(?:show|inspect|view|get)\s+(?:the\s+)?(?:run\s+)?history\s+(?:for|of)\s+"
            + r"(?:the\s+)?(?:automation|scheduled task)\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if automation_history:
            return AppActionRequest(
                action_id=AUTOMATION_HISTORY_ACTION_ID,
                arguments={"reference": self._spoken_value(automation_history.group(1))},
            )

        automation_control = re.fullmatch(
            polite
            + r"(pause|resume|run|run now|remove|delete)\s+(?:the\s+)?(?:automation|scheduled task)"
            + r"(?:\s+(?:called|named))?\s+(.+?)(?:\s+now)?",
            submitted,
            flags=re.IGNORECASE,
        )
        if automation_control:
            operation = automation_control.group(1).casefold()
            action_id = {
                "pause": AUTOMATION_PAUSE_ACTION_ID,
                "resume": AUTOMATION_RESUME_ACTION_ID,
                "run": AUTOMATION_RUN_ACTION_ID,
                "run now": AUTOMATION_RUN_ACTION_ID,
                "remove": AUTOMATION_REMOVE_ACTION_ID,
                "delete": AUTOMATION_REMOVE_ACTION_ID,
            }[operation]
            return AppActionRequest(
                action_id=action_id,
                arguments={"reference": self._spoken_value(automation_control.group(2))},
            )

        observability_status = re.fullmatch(
            polite
            + r"(?:(?:show|get|check|tell\s+me)\s+(?:the\s+)?observability\s+status|"
            + r"(?:what(?:'s|\s+is)|how\s+is)\s+(?:the\s+)?observability(?:\s+status)?|"
            + r"is\s+(?:the\s+)?observability\s+(?:running|live|working))",
            normalized,
        )
        if observability_status:
            return AppActionRequest(action_id=OBSERVABILITY_STATUS_ACTION_ID)

        observability_refresh = re.fullmatch(
            polite + r"refresh\s+(?:the\s+)?observability(?:\s+(?:view|dashboard|surface))?",
            normalized,
        )
        if observability_refresh:
            return AppActionRequest(action_id=OBSERVABILITY_REFRESH_ACTION_ID)

        observability_stream = re.fullmatch(
            polite
            + r"(pause|resume|start|run|reconnect)\s+(?:the\s+)?observability(?:\s+(?:stream|feed))?",
            normalized,
        )
        if observability_stream:
            operation = observability_stream.group(1)
            return AppActionRequest(
                action_id=OBSERVABILITY_STREAM_SET_ACTION_ID,
                arguments={
                    "enabled": operation != "pause",
                    **({"reconnect": True} if operation == "reconnect" else {}),
                },
            )

        observability_open = re.fullmatch(
            polite
            + r"(?:open|show|go\s+to|view)\s+(?:the\s+)?observability(?:\s+(?:view|dashboard|surface))?",
            normalized,
        )
        if observability_open:
            return AppActionRequest(action_id=OBSERVABILITY_OPEN_ACTION_ID)

        plugin_state = re.fullmatch(
            polite + r"(enable|disable|turn\s+on|turn\s+off)\s+(?:the\s+)?(.+?)\s+plugin",
            normalized,
        )
        if plugin_state:
            return AppActionRequest(
                action_id=PLUGIN_STATE_SET_ACTION_ID,
                arguments={
                    "plugin_id": self._spoken_value(plugin_state.group(2)),
                    "enabled": plugin_state.group(1) in {"enable", "turn on"},
                },
            )

        skill_review = re.fullmatch(
            polite + r"(approve|reject)\s+(?:the\s+)?(?:skill\s+)?(?:change|mutation)\s+(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if skill_review:
            return AppActionRequest(
                action_id=(SKILL_MUTATION_APPROVE_ACTION_ID if skill_review.group(1).casefold() == "approve" else SKILL_MUTATION_REJECT_ACTION_ID),
                arguments={"mutation_id": self._spoken_value(skill_review.group(2))},
            )

        skill_install = re.fullmatch(
            polite + r"install\s+(?:the\s+)?(?:skill\s+(.+)|(.+?)\s+skill)",
            submitted,
            flags=re.IGNORECASE,
        )
        if skill_install:
            return AppActionRequest(
                action_id=SKILL_MUTATION_SUBMIT_ACTION_ID,
                arguments={"operation": "install", "identifier": self._spoken_value(skill_install.group(1) or skill_install.group(2))},
            )

        skill_mutation = re.fullmatch(
            polite
            + r"(update|enable|disable|archive|restore|remove|uninstall)\s+"
            + r"(?:the\s+)?(?:(?:skill\s+)?(?:called|named)\s+)?(.+?)(?:\s+skill)?",
            submitted,
            flags=re.IGNORECASE,
        )
        if skill_mutation and "skill" in normalized:
            operation = skill_mutation.group(1).casefold()
            name = self._spoken_value(skill_mutation.group(2))
            if operation == "uninstall":
                return AppActionRequest(action_id=SKILL_UNINSTALL_ACTION_ID, arguments={"name": name})
            return AppActionRequest(
                action_id=SKILL_MUTATION_SUBMIT_ACTION_ID,
                arguments={"operation": "remove" if operation == "remove" else operation, "name": name},
            )

        pet_visibility = re.fullmatch(
            polite + r"(?:show|hide)\s+(?:the\s+|my\s+)?(?:pet|companion)",
            normalized,
        )
        if pet_visibility:
            return AppActionRequest(
                action_id=PETDEX_VISIBILITY_SET_ACTION_ID,
                arguments={"visible": "hide" not in normalized},
            )
        pet_toggle = re.fullmatch(
            polite + r"turn\s+(?:the\s+|my\s+)?(?:pet|companion)\s+(on|off)",
            normalized,
        )
        if pet_toggle:
            return AppActionRequest(
                action_id=PETDEX_VISIBILITY_SET_ACTION_ID,
                arguments={"visible": pet_toggle.group(1) == "on"},
            )
        pet_size = re.fullmatch(
            polite + r"(?:make|set)\s+(?:the\s+|my\s+)?(?:pet|companion)(?:\s+size)?(?:\s+to)?\s+(small|medium|large)",
            normalized,
        )
        if pet_size:
            return AppActionRequest(action_id=PETDEX_SIZE_SET_ACTION_ID, arguments={"size": pet_size.group(1)})
        pet_position = re.fullmatch(
            polite + r"(?:move|put)\s+(?:the\s+|my\s+)?(?:pet|companion)\s+(?:to|in)\s+(?:the\s+)?(top left|top right|bottom left|bottom right)",
            normalized,
        )
        if pet_position:
            return AppActionRequest(
                action_id=PETDEX_POSITION_SET_ACTION_ID,
                arguments={"anchor": pet_position.group(1).replace(" ", "-")},
            )
        pet_install = re.fullmatch(
            polite + r"(install|remove)\s+(?:the\s+)?(.+?)\s+(?:pet|companion)",
            submitted,
            flags=re.IGNORECASE,
        )
        if pet_install:
            return AppActionRequest(
                action_id=PETDEX_INSTALL_ACTION_ID if pet_install.group(1).casefold() == "install" else PETDEX_REMOVE_ACTION_ID,
                arguments={"slug": self._spoken_value(pet_install.group(2)).casefold()},
            )
        pet_selection = re.fullmatch(
            polite + r"(?:use|select|switch(?:\s+over)?\s+to)\s+(?:the\s+)?(.+?)\s+(?:pet|companion)",
            submitted,
            flags=re.IGNORECASE,
        )
        if pet_selection:
            return AppActionRequest(
                action_id=PETDEX_ACTIVE_SET_ACTION_ID,
                arguments={"slug": self._spoken_value(pet_selection.group(1)).casefold()},
            )

        if re.fullmatch(
            polite + r"(?:attach|add|import|use)\s+(?:(?:the|my)\s+)?(?:current\s+)?(?:clipboard|clipboard content|copied text|copied image)",
            normalized,
        ):
            return AppActionRequest(
                action_id=ATTACHMENT_IMPORT_ACTION_ID,
                arguments={"source": "clipboard"},
            )

        recent_attachment = re.fullmatch(
            polite
            + r"(?:attach|add|import)\s+(?:the\s+)?(?:most\s+)?recent\s+(?:file|image|photo|document|attachment)"
            + r"(?:\s+(?:called|named)\s+(.+))?",
            submitted,
            flags=re.IGNORECASE,
        )
        if recent_attachment:
            reference = self._spoken_value(recent_attachment.group(1) or "")
            arguments = {"source": "recent"}
            if reference:
                arguments["reference"] = reference
            return AppActionRequest(action_id=ATTACHMENT_IMPORT_ACTION_ID, arguments=arguments)

        if re.fullmatch(
            polite + r"(?:attach|add|import|upload|choose)\s+(?:an?\s+|the\s+)?(?:file|image|photo|document)(?:\s+for\s+me)?",
            normalized,
        ):
            return AppActionRequest(
                action_id=ATTACHMENT_IMPORT_ACTION_ID,
                arguments={"source": "picker"},
            )

        path_attachment = re.fullmatch(
            polite
            + r"(?:attach|add|import|upload)\s+(?:(?:the|this)\s+)?(?:(?:file|image|photo|document)\s+)?(?:at\s+|from\s+)?(.+)",
            submitted,
            flags=re.IGNORECASE,
        )
        if path_attachment:
            path = self._spoken_value(path_attachment.group(1))
            if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", path):
                return AppActionRequest(
                    action_id=ATTACHMENT_IMPORT_ACTION_ID,
                    arguments={"source": "path", "path": path},
                )

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

        open_referenced_window = re.fullmatch(
            polite
            + r'''open\s+(?:the\s+)?(?:chat|conversation)\s+(?:called|named)\s+("[^"]+"|'[^']+')\s+in\s+(?:a\s+)?new\s+window''',
            submitted,
            flags=re.IGNORECASE,
        )
        if open_referenced_window:
            return AppActionRequest(
                action_id=CONVERSATION_WINDOW_OPEN_ACTION_ID,
                arguments={"reference": self._spoken_value(open_referenced_window.group(1))},
            )

        fork_referenced_chat = re.fullmatch(
            polite
            + r'''fork\s+(?:the\s+)?(?:chat|conversation)\s+(?:called|named)\s+("[^"]+"|'[^']+')'''
            + r"(?:\s+(?:from|through|at)\s+message\s+(.+))?",
            submitted,
            flags=re.IGNORECASE,
        )
        if fork_referenced_chat:
            arguments = {"reference": self._spoken_value(fork_referenced_chat.group(1))}
            boundary = self._spoken_value(fork_referenced_chat.group(2) or "")
            if boundary:
                arguments["through_message_id"] = boundary
            return AppActionRequest(action_id=CONVERSATION_FORK_ACTION_ID, arguments=arguments)

        share_referenced_chat = re.fullmatch(
            polite
            + r'''share\s+(?:the\s+)?(?:chat|conversation)\s+(?:called|named)\s+("[^"]+"|'[^']+')''',
            submitted,
            flags=re.IGNORECASE,
        )
        if share_referenced_chat:
            return AppActionRequest(
                action_id=CONVERSATION_SHARE_ACTION_ID,
                arguments={"reference": self._spoken_value(share_referenced_chat.group(1))},
            )

        open_window = re.fullmatch(
            polite
            + r"open\s+(?:(?:this|the\s+current|current)\s+)?(?:chat|conversation)\s+in\s+(?:a\s+)?new\s+window",
            normalized,
        )
        if open_window:
            return AppActionRequest(action_id=CONVERSATION_WINDOW_OPEN_ACTION_ID)

        fork_chat = re.fullmatch(
            polite
            + r"fork\s+(?:(?:this|the\s+current|current)\s+)?(?:chat|conversation)"
            + r"(?:\s+(?:from|through|at)\s+(?:message\s+(.+)|here))?",
            submitted,
            flags=re.IGNORECASE,
        )
        if fork_chat:
            boundary = self._spoken_value(fork_chat.group(1) or "")
            arguments = {"through_message_id": boundary} if boundary else {}
            if re.search(r"\s(?:from|through|at)\s+here$", normalized):
                arguments["from_selected"] = True
            return AppActionRequest(action_id=CONVERSATION_FORK_ACTION_ID, arguments=arguments)

        if re.fullmatch(
            polite + r"share\s+(?:(?:this|the\s+current|current)\s+)?(?:chat|conversation)",
            normalized,
        ):
            return AppActionRequest(action_id=CONVERSATION_SHARE_ACTION_ID)

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
    def _split_mixed_clauses(submitted: str) -> list[str]:
        separators = (
            ", and then ",
            " and then ",
            ", then ",
            " then ",
            ", and ",
            " and ",
            "; ",
            ", ",
        )
        normalized = submitted.casefold()
        clauses: list[str] = []
        start = 0
        quote = ""
        index = 0
        while index < len(submitted):
            character = submitted[index]
            if character in {"'", '"'}:
                if (
                    character == "'"
                    and index > 0
                    and index + 1 < len(submitted)
                    and submitted[index - 1].isalnum()
                    and submitted[index + 1].isalnum()
                ):
                    index += 1
                    continue
                quote = "" if quote == character else (character if not quote else quote)
                index += 1
                continue
            if quote:
                index += 1
                continue
            separator = next(
                (candidate for candidate in separators if normalized.startswith(candidate, index)),
                None,
            )
            if separator is None:
                index += 1
                continue
            clause = submitted[start:index].strip(" ,;")
            if clause:
                clauses.append(clause)
            index += len(separator)
            start = index
        final_clause = submitted[start:].strip(" ,;")
        if final_clause:
            clauses.append(final_clause)
        return clauses

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
        definition = self._definition(request.action_id)
        if definition is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class="unknown",
                error_code="ACTION_UNAVAILABLE",
                message=f"{request.action_id} is unavailable.",
            )
        if not self._is_available(definition, context):
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="ACTION_UNAVAILABLE",
                message=f"{definition.title} is currently unavailable.",
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
        if request.action_id == ATTACHMENT_IMPORT_ACTION_ID:
            return self._dispatch_attachment(request, context, definition)
        if request.action_id in SESSION_CONTROL_ACTION_IDS:
            if (
                request.action_id == MEMORY_CONVERSATION_SET_ACTION_ID
                and request.arguments.get("enabled") is True
            ):
                return self._control_confirmation_receipt(request, context, definition)
            return self._dispatch_session_control(request, context, definition)
        if request.action_id in SETTINGS_RUNTIME_ACTION_IDS:
            requires_confirmation = request.action_id in CONFIRMED_SETTINGS_RUNTIME_ACTION_IDS and (
                request.action_id != PROVIDER_CREDENTIAL_CONFIGURE_ACTION_ID
                or bool(str(request.arguments.get("secret") or request.arguments.get("api_key") or "").strip())
            )
            if requires_confirmation:
                if request.action_id == MEMORY_SETTINGS_UPDATE_ACTION_ID:
                    target_kind, target_reference = "user_setting", "memory"
                    confirmation_message = "Confirm changing user-wide memory privacy settings."
                elif request.action_id == MEMORY_ENTRY_DELETE_ACTION_ID:
                    target_kind = "memory_entry"
                    target_reference = str(request.arguments.get("memory_id") or request.arguments.get("id") or "memory")
                    confirmation_message = "Confirm permanently deleting this memory."
                elif request.action_id == MEMORY_DREAMING_RUN_ACTION_ID:
                    target_kind, target_reference = "memory_runtime", "dreaming"
                    confirmation_message = "Confirm consolidating recent chats into durable memories."
                elif request.action_id == MEMORY_CONVERSATIONS_IMPORT_ACTION_ID:
                    target_kind, target_reference = "memory_runtime", "conversation-import"
                    confirmation_message = "Confirm importing existing chats into memory."
                elif request.action_id == MEMORY_OBSIDIAN_IMPORT_ACTION_ID:
                    target_kind, target_reference = "memory_runtime", "obsidian-import"
                    confirmation_message = "Confirm importing reviewed local memory notes."
                elif request.action_id == ROUTING_MODEL_POLICY_REMOVE_ACTION_ID:
                    target_kind = "llm_routing"
                    target_reference = f"model-policy:{str(request.arguments.get('model_id') or '').strip()}"
                    confirmation_message = "Confirm removing this model routing policy."
                elif request.action_id == ROUTING_CREDENTIAL_ADD_ACTION_ID:
                    target_kind, target_reference = "llm_credential", "new"
                    confirmation_message = "Confirm adding this provider credential. The secret will not appear in the receipt."
                elif request.action_id == ROUTING_CREDENTIAL_REMOVE_ACTION_ID:
                    target_kind = "llm_credential"
                    target_reference = str(request.arguments.get("credential_id") or "credential")
                    confirmation_message = "Confirm removing this provider credential."
                else:
                    target_kind = "application_credential"
                    target_reference = f"provider-credential:{str(request.arguments.get('provider') or '').strip().casefold()}"
                    confirmation_message = "Confirm saving this provider credential. The secret will not appear in the receipt."
                return self._domain_confirmation_receipt(
                    request,
                    context,
                    definition,
                    target_kind=target_kind,
                    target_reference=target_reference,
                    message=confirmation_message,
                )
            return self._dispatch_settings_runtime(request, context, definition)
        if request.action_id in LIFECYCLE_CONTROL_ACTION_IDS:
            if definition.confirmation_rule == "operation_bound":
                return self._lifecycle_confirmation_receipt(request, context, definition)
            return self._dispatch_lifecycle_control(request, context, definition)
        if request.action_id in OBSERVABILITY_ACTION_IDS:
            return self._dispatch_observability(request, context, definition)
        if request.action_id in CODING_GITHUB_ACTION_IDS:
            if request.action_id == GITHUB_PULL_REQUEST_CREATE_ACTION_ID:
                return self._coding_github_confirmation_receipt(request, context, definition)
            return self._dispatch_coding_github(request, context, definition)
        if request.action_id in AUTOMATION_ACTION_IDS:
            if request.action_id in {AUTOMATION_RUN_ACTION_ID, AUTOMATION_REMOVE_ACTION_ID}:
                return self._automation_confirmation_receipt(request, context, definition)
            return self._dispatch_automation(request, context, definition)
        if request.action_id in KNOWLEDGE_SOURCE_ACTION_IDS:
            if request.action_id in KNOWLEDGE_SOURCE_CONFIRMED_ACTION_IDS:
                return self._domain_confirmation_receipt(
                    request,
                    context,
                    definition,
                    target_kind="knowledge_source" if request.action_id == KNOWLEDGE_SOURCE_IMPORT_ACTION_ID else "book_document",
                    target_reference=str(
                        "knowledge-source"
                        if request.action_id == KNOWLEDGE_SOURCE_IMPORT_ACTION_ID
                        else request.arguments.get("import_id")
                        or request.arguments.get("reference")
                        or request.action_id
                    ),
                    message=(
                        "Confirm importing this approved source into Knowledge."
                        if request.action_id == KNOWLEDGE_SOURCE_IMPORT_ACTION_ID
                        else "Confirm changing this Book knowledge."
                    ),
                )
            return self._dispatch_knowledge_source(request, context, definition)
        if request.action_id in PETDEX_ACTION_IDS:
            return self._dispatch_petdex_action(request, context, definition)
        if self._plugin_contributions and self._plugin_contributions.has_action(request.action_id):
            if definition.confirmation_rule == "operation_bound":
                return self._domain_confirmation_receipt(
                    request,
                    context,
                    definition,
                    target_kind="plugin",
                    target_reference=definition.plugin_id or definition.owner,
                    message=f"Confirm {definition.title.casefold()}.",
                )
            return self._dispatch_plugin_action(request, context, definition)

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

    def _dispatch_plugin_action(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
    ) -> ActionReceipt:
        try:
            raw_result = self._registry.invoke(
                request.action_id,
                {
                    "arguments": dict(request.arguments),
                    "context": context,
                    "confirmed": confirmed,
                },
                agent_name=self._agent_name(context),
            )
            if not isinstance(raw_result, dict):
                raise TypeError("Plugin App Action adapters must return an object")
            result = dict(raw_result)
        except ToolPermissionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="ACTION_NOT_AUTHORIZED",
                message=str(exc),
            )
        except PluginContributionActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        except (TypeError, ValueError) as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="PLUGIN_ACTION_FAILED",
                message=str(exc),
                authorized=True,
            )

        target_kind = str(result.pop("_target_kind", "plugin"))
        target_id = str(result.pop("_target_id", definition.plugin_id or definition.owner))
        message = str(result.pop("_message", f"{definition.title} completed."))
        result.setdefault("changed", True)
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="applied",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(kind=target_kind, id=target_id),
            result=result,
            message=message,
            audit_label=definition.audit_label,
            created_at=self._now(),
        )

    def dispatch_many(
        self,
        requests: list[AppActionRequest] | tuple[AppActionRequest, ...],
        context: AppActionContext,
    ) -> list[ActionReceipt]:
        """Dispatch one turn's actions in order against each preceding receipt."""

        receipts: list[ActionReceipt] = []
        current_context = context
        for request in requests:
            receipt = self.dispatch(request, current_context)
            receipts.append(receipt)
            current_context = self._context_after_receipt(current_context, receipt)
        return receipts

    def _dispatch_attachment(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        if self._attachment_importer is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="ATTACHMENT_IMPORT_UNAVAILABLE",
                message="Attachment import is unavailable.",
            )
        try:
            result = self._attachment_importer(dict(request.arguments), tuple(context.attachment_digests))
        except AttachmentImportError as exc:
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
        attachments = list(result.get("attachments") or [])
        target_id = str(attachments[0].get("digest") if attachments else "composer")
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="applied",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(kind="composer_attachment", id=target_id),
            result=result,
            message=str(result.get("message") or "Attachment ready."),
            audit_label=definition.audit_label,
            created_at=self._now(),
        )

    def _dispatch_session_control(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        if self._session_control_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="SESSION_CONTROLS_UNAVAILABLE",
                message="Conversation controls are unavailable.",
            )
        try:
            result = self._session_control_handler(request.action_id, dict(request.arguments), context)
        except SessionControlError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        target_kind = str(result.pop("target_kind", "conversation_runtime"))
        target_id = str(result.pop("target_id", context.invocation_conversation_id or request.action_id))
        message = str(result.pop("message", "Chat setting updated."))
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="applied",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(kind=target_kind, id=target_id),
            result=result,
            message=message,
            audit_label=definition.audit_label,
            created_at=self._now(),
        )

    def _dispatch_settings_runtime(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
    ) -> ActionReceipt:
        if self._settings_runtime_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="SETTINGS_RUNTIME_UNAVAILABLE",
                message="Settings and runtime controls are unavailable.",
            )
        try:
            result = self._registry.invoke(
                request.action_id,
                {
                    "arguments": dict(request.arguments),
                    "context": context,
                    "confirmed": confirmed,
                },
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
        except SettingsRuntimeActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _invoke_settings_runtime(
        self,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._settings_runtime_handler is None:
            raise SettingsRuntimeActionError(
                "SETTINGS_RUNTIME_UNAVAILABLE",
                "Settings and runtime controls are unavailable.",
                unavailable=True,
            )
        return self._settings_runtime_handler(
            action_id,
            dict(payload.get("arguments") or {}),
            payload["context"],
            confirmed=payload.get("confirmed") is True,
        )

    def _dispatch_lifecycle_control(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
    ) -> ActionReceipt:
        if self._lifecycle_control_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="LIFECYCLE_CONTROLS_UNAVAILABLE",
                message="Plugin and skill controls are unavailable.",
            )
        try:
            result = self._registry.invoke(
                request.action_id,
                {
                    "arguments": dict(request.arguments),
                    "context": context,
                    "confirmed": confirmed,
                },
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
        except LifecycleControlError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _invoke_lifecycle_control(
        self,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._lifecycle_control_handler is None:
            raise LifecycleControlError(
                "LIFECYCLE_CONTROLS_UNAVAILABLE",
                "Plugin and skill controls are unavailable.",
                unavailable=True,
            )
        return self._lifecycle_control_handler(
            action_id,
            dict(payload.get("arguments") or {}),
            payload["context"],
            payload.get("confirmed") is True,
        )

    def _dispatch_observability(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        if self._observability_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="OBSERVABILITY_UNAVAILABLE",
                message="Observability controls are unavailable.",
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
        except ObservabilityActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _invoke_observability(
        self,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._observability_handler is None:
            raise ObservabilityActionError(
                "OBSERVABILITY_UNAVAILABLE",
                "Observability controls are unavailable.",
                unavailable=True,
            )
        return self._observability_handler(
            action_id,
            dict(payload.get("arguments") or {}),
            payload["context"],
        )

    def _coding_github_confirmation_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        if self._coding_github_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="CODING_GITHUB_UNAVAILABLE",
                message="Coding and GitHub controls are unavailable.",
            )
        try:
            result = self._coding_github_handler(
                request.action_id,
                dict(request.arguments),
                context,
                confirmed=False,
                confirmation_binding=None,
            )
        except CodingGitHubActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )

        binding = result.pop("_confirmation_binding", None)
        target_kind = str(result.pop("_target_kind", "github_repository"))
        target_id = str(result.pop("_target_id", request.action_id))
        message = str(result.pop("_message", "Confirm creating this pull request."))
        if not isinstance(binding, dict) or not binding:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="CONFIRMATION_BINDING_UNAVAILABLE",
                message="Pull-request confirmation could not be prepared.",
                authorized=True,
            )
        token = self._confirmation_token_factory()
        expires_at = self._now() + _UNDO_TTL
        self._receipt_store.put_confirmation(_ConfirmationRecord(
            token=token,
            action_id=request.action_id,
            action_version=request.action_version,
            arguments=dict(request.arguments),
            target_kind=target_kind,
            target_reference=target_id,
            expected_revision=0,
            expires_at=expires_at,
            binding=dict(binding),
        ))
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
            target=ActionTarget(kind=target_kind, id=target_id),
            result=result,
            confirmation=ActionConfirmation(token=token, expires_at=expires_at, target_revision=0),
            message=message,
            audit_label=f"{definition.audit_label}.confirmation_requested",
            created_at=self._now(),
        )

    def _dispatch_coding_github(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
        confirmation_binding: dict[str, Any] | None = None,
    ) -> ActionReceipt:
        if self._coding_github_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="CODING_GITHUB_UNAVAILABLE",
                message="Coding and GitHub controls are unavailable.",
            )
        try:
            result = self._registry.invoke(
                request.action_id,
                {
                    "arguments": dict(request.arguments),
                    "context": context,
                    "confirmed": confirmed,
                    "confirmation_binding": confirmation_binding,
                    "confirm": confirmed,
                },
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
        except CodingGitHubActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _invoke_coding_github(
        self,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._coding_github_handler is None:
            raise CodingGitHubActionError(
                "CODING_GITHUB_UNAVAILABLE",
                "Coding and GitHub controls are unavailable.",
                unavailable=True,
            )
        return self._coding_github_handler(
            action_id,
            dict(payload.get("arguments") or {}),
            payload["context"],
            confirmed=payload.get("confirmed") is True,
            confirmation_binding=payload.get("confirmation_binding"),
        )

    def _automation_confirmation_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        if self._automation_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="AUTOMATIONS_UNAVAILABLE",
                message="Automation controls are unavailable.",
            )
        try:
            result = self._automation_handler(
                request.action_id,
                dict(request.arguments),
                context,
                confirmed=False,
                confirmation_binding=None,
            )
        except AutomationActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        binding = result.pop("_confirmation_binding", None)
        target_kind = str(result.pop("_target_kind", "automation"))
        target_id = str(result.pop("_target_id", request.action_id))
        message = str(result.pop("_message", f"Confirm {definition.title.casefold()}."))
        if not isinstance(binding, dict) or not binding:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="CONFIRMATION_BINDING_UNAVAILABLE",
                message="Automation confirmation could not be prepared.",
                authorized=True,
            )
        token = self._confirmation_token_factory()
        expires_at = self._now() + _UNDO_TTL
        self._receipt_store.put_confirmation(_ConfirmationRecord(
            token=token,
            action_id=request.action_id,
            action_version=request.action_version,
            arguments=dict(request.arguments),
            target_kind=target_kind,
            target_reference=target_id,
            expected_revision=0,
            expires_at=expires_at,
            binding=dict(binding),
        ))
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
            target=ActionTarget(kind=target_kind, id=target_id),
            result=result,
            confirmation=ActionConfirmation(token=token, expires_at=expires_at, target_revision=0),
            message=message,
            audit_label=f"{definition.audit_label}.confirmation_requested",
            created_at=self._now(),
        )

    def _dispatch_automation(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
        confirmation_binding: dict[str, Any] | None = None,
    ) -> ActionReceipt:
        if self._automation_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="AUTOMATIONS_UNAVAILABLE",
                message="Automation controls are unavailable.",
            )
        try:
            result = self._registry.invoke(
                request.action_id,
                {
                    "arguments": dict(request.arguments),
                    "context": context,
                    "confirmed": confirmed,
                    "confirmation_binding": confirmation_binding,
                    "confirm": confirmed,
                },
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
        except AutomationActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _invoke_automation(
        self,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._automation_handler is None:
            raise AutomationActionError(
                "AUTOMATIONS_UNAVAILABLE",
                "Automation controls are unavailable.",
                unavailable=True,
            )
        return self._automation_handler(
            action_id,
            dict(payload.get("arguments") or {}),
            payload["context"],
            confirmed=payload.get("confirmed") is True,
            confirmation_binding=payload.get("confirmation_binding"),
        )

    def _dispatch_knowledge_source(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        confirmed: bool = False,
    ) -> ActionReceipt:
        if self._knowledge_source_handler is None:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class=definition.access_class,
                error_code="KNOWLEDGE_CONTROLS_UNAVAILABLE",
                message="Knowledge and source controls are unavailable.",
            )
        try:
            result = self._registry.invoke(
                request.action_id,
                {
                    "arguments": dict(request.arguments),
                    "context": context,
                    "confirmed": confirmed,
                },
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
        except KnowledgeSourceActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _invoke_knowledge_source(
        self,
        action_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self._knowledge_source_handler is None:
            raise KnowledgeSourceActionError(
                "KNOWLEDGE_CONTROLS_UNAVAILABLE",
                "Knowledge and source controls are unavailable.",
                unavailable=True,
            )
        return self._knowledge_source_handler(
            action_id,
            dict(payload.get("arguments") or {}),
            payload["context"],
            confirmed=payload.get("confirmed") is True,
        )

    def _dispatch_petdex_action(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        try:
            result = execute_petdex_action(request.action_id, dict(request.arguments), context)
        except PetdexActionError as exc:
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable" if exc.unavailable else "failed",
                access_class=definition.access_class,
                error_code=exc.code,
                message=str(exc),
                authorized=not exc.unavailable,
            )
        return self._domain_action_receipt(request, context, definition, result)

    def _domain_action_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        raw_result: dict[str, Any],
    ) -> ActionReceipt:
        result = dict(raw_result)
        target_kind = str(result.pop("_target_kind", definition.owner))
        target_id = str(result.pop("_target_id", definition.ui_reference or definition.owner))
        message = str(result.pop("_message", f"{definition.title} completed."))
        result.setdefault("changed", True)
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="applied",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(kind=target_kind, id=target_id),
            result=result,
            message=message,
            audit_label=definition.audit_label,
            created_at=self._now(),
        )

    def _lifecycle_confirmation_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        target_kind = "skill" if request.action_id == SKILL_UNINSTALL_ACTION_ID else definition.owner
        target_id = str(request.arguments.get("name") or request.arguments.get("plugin_id") or request.action_id)
        token = self._confirmation_token_factory()
        expires_at = self._now() + _UNDO_TTL
        self._receipt_store.put_confirmation(_ConfirmationRecord(
            token=token,
            action_id=request.action_id,
            action_version=request.action_version,
            arguments=dict(request.arguments),
            target_kind=target_kind,
            target_reference=target_id,
            expected_revision=0,
            expires_at=expires_at,
        ))
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=request.action_id,
            action_version=definition.version,
            source=context.source,
            status="confirmation_required",
            authorization=self._authorization(definition.access_class, context, allowed=True, confirmation_required=True),
            target=ActionTarget(kind=target_kind, id=target_id),
            result={"operation": request.action_id, "target": target_id},
            confirmation=ActionConfirmation(token=token, expires_at=expires_at, target_revision=0),
            message=f"Confirm removing {target_id}.",
            audit_label=f"{definition.audit_label}.confirmation_requested",
            created_at=self._now(),
        )

    def _domain_confirmation_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
        *,
        target_kind: str,
        target_reference: str,
        message: str,
    ) -> ActionReceipt:
        token = self._confirmation_token_factory()
        expires_at = self._now() + _UNDO_TTL
        self._receipt_store.put_confirmation(_ConfirmationRecord(
            token=token,
            action_id=request.action_id,
            action_version=request.action_version,
            arguments=dict(request.arguments),
            target_kind=target_kind,
            target_reference=target_reference,
            expected_revision=0,
            expires_at=expires_at,
        ))
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
            target=ActionTarget(kind=target_kind, id=target_reference),
            result={"operation": request.action_id},
            confirmation=ActionConfirmation(token=token, expires_at=expires_at, target_revision=0),
            message=message,
            audit_label=f"{definition.audit_label}.confirmation_requested",
            created_at=self._now(),
        )

    def _control_confirmation_receipt(
        self,
        request: AppActionRequest,
        context: AppActionContext,
        definition: AppActionDefinition,
    ) -> ActionReceipt:
        target_id = str(context.invocation_conversation_id or "").strip()
        if not target_id:
            return self._error_receipt(
                request=request,
                context=context,
                status="failed",
                access_class=definition.access_class,
                error_code="CONVERSATION_CONTEXT_REQUIRED",
                message="Choose or start a chat before changing this setting.",
                authorized=True,
            )
        token = self._confirmation_token_factory()
        expires_at = self._now() + _UNDO_TTL
        self._receipt_store.put_confirmation(_ConfirmationRecord(
            token=token,
            action_id=request.action_id,
            action_version=request.action_version,
            arguments=dict(request.arguments),
            target_kind="conversation_runtime",
            target_reference=target_id,
            expected_revision=0,
            expires_at=expires_at,
        ))
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
            target=ActionTarget(kind="conversation_runtime", id=target_id),
            result={"requested_store_to_memory": True},
            confirmation=ActionConfirmation(token=token, expires_at=expires_at, target_revision=0),
            message="Confirm turning memory on for this chat.",
            audit_label=f"{definition.audit_label}.confirmation_requested",
            created_at=self._now(),
        )

    @staticmethod
    def _context_after_receipt(
        context: AppActionContext,
        receipt: ActionReceipt,
    ) -> AppActionContext:
        if receipt.status != "applied":
            return context
        control_patch = receipt.result.get("session_control_patch")
        if isinstance(control_patch, dict):
            updates = {}
            if "agent_id" in control_patch:
                updates["active_agent"] = str(control_patch["agent_id"] or "")
            if "model_id" in control_patch:
                updates["selected_model"] = str(control_patch["model_id"] or "")
            if "reasoning_mode" in control_patch:
                updates["reasoning_mode"] = str(control_patch["reasoning_mode"] or "")
            if "store_to_memory" in control_patch:
                updates["store_to_memory"] = bool(control_patch["store_to_memory"])
            if updates:
                context = context.model_copy(update=updates)
        device_patch = receipt.result.get("device_settings_patch")
        if isinstance(device_patch, dict) and isinstance(device_patch.get("values"), dict):
            snapshot = DeviceSettingsSnapshot.model_validate(context.device_settings).model_dump(
                exclude_none=True,
                exclude_defaults=True,
            )
            values = dict(snapshot.get("values") or {})
            for key, value in device_patch["values"].items():
                if key == "personalization" and isinstance(value, dict):
                    values[key] = {**dict(values.get(key) or {}), **value}
                else:
                    values[key] = value
            context = context.model_copy(update={
                "device_settings": {
                    "version": int(device_patch.get("version") or snapshot.get("version") or 1),
                    "revision": int(device_patch.get("revision") or snapshot.get("revision") or 0),
                    "values": values,
                }
            })
        patch = receipt.result.get("workspace_layout_patch")
        if not isinstance(patch, dict) or not isinstance(patch.get("surfaces"), dict):
            return context
        surfaces = {} if patch.get("replace") else {
            reference: presentation.model_copy(deep=True)
            for reference, presentation in context.workspace_layout.surfaces.items()
        }
        for reference, presentation in patch["surfaces"].items():
            surfaces[str(reference)] = SurfacePresentation.model_validate(presentation)
        layout = WorkspaceLayoutSnapshot(
            version=int(patch.get("version", context.workspace_layout.version)),
            revision=int(patch.get("revision", context.workspace_layout.revision)),
            surfaces=surfaces,
        )
        return context.model_copy(update={"workspace_layout": layout})

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
            message=f"{self._surface_map(context)[record.target_reference].title} change undone.",
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
            except (ConversationLifecycleError, ConversationShareError) as exc:
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
                {"arguments": dict(request.arguments), "context": context, "confirm": confirmed},
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
        except (ConversationLifecycleError, ConversationShareError) as exc:
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
        result = {
            "conversation": {
                "id": conversation_id,
                "title": conversation.get("title"),
                "revision": revision,
            },
        }
        if request.action_id == CONVERSATION_SHARE_ACTION_ID:
            review = self._sharing_service().review(
                conversation,
                provider_id=str(request.arguments.get("provider_id") or ""),
            )
            result["share_review"] = review
            message = (
                f"Confirm local export of {conversation.get('title') or 'this chat'}."
                if not review["external_disclosure"]
                else f"Confirm sharing {conversation.get('title') or 'this chat'} with {review['destination']}."
            )
        else:
            message = f"Confirm deletion of {conversation.get('title') or 'this chat'}."
        self._receipt_store.put_confirmation(
            _ConfirmationRecord(
                token=token,
                action_id=request.action_id,
                action_version=request.action_version,
                arguments=dict(request.arguments),
                target_kind="conversation",
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
            result=result,
            confirmation=ActionConfirmation(
                token=token,
                expires_at=expires_at,
                target_revision=revision,
            ),
            message=message,
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
        definition = self._definition(request.action_id)
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
        if request.action_id in SESSION_CONTROL_ACTION_IDS:
            if context.invocation_conversation_id != record.target_reference:
                return self._error_receipt(
                    request=request,
                    context=context,
                    status="failed",
                    access_class=access_class,
                    error_code="CONFIRMATION_MISMATCH",
                    message="Confirmation does not match the current chat.",
                    authorized=True,
                )
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_session_control(request, context, definition)
        if request.action_id in CONFIRMED_SETTINGS_RUNTIME_ACTION_IDS:
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_settings_runtime(request, context, definition, confirmed=True)
        if request.action_id in LIFECYCLE_CONTROL_ACTION_IDS:
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_lifecycle_control(request, context, definition, confirmed=True)
        if request.action_id == GITHUB_PULL_REQUEST_CREATE_ACTION_ID:
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_coding_github(
                request,
                context,
                definition,
                confirmed=True,
                confirmation_binding=record.binding,
            )
        if request.action_id in {AUTOMATION_RUN_ACTION_ID, AUTOMATION_REMOVE_ACTION_ID}:
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_automation(
                request,
                context,
                definition,
                confirmed=True,
                confirmation_binding=record.binding,
            )
        if request.action_id in KNOWLEDGE_SOURCE_CONFIRMED_ACTION_IDS:
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_knowledge_source(request, context, definition, confirmed=True)
        if self._plugin_contributions and self._plugin_contributions.has_action(request.action_id):
            self._receipt_store.remove_confirmation(token)
            return self._dispatch_plugin_action(request, context, definition, confirmed=True)
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
                message="The conversation changed before this operation was confirmed.",
                authorized=True,
            )
        self._receipt_store.remove_confirmation(token)
        bound_request = request.model_copy(update={
            "arguments": {
                **request.arguments,
                "conversation_id": record.target_reference,
                "target_revision": record.expected_revision,
            },
        })
        return self._dispatch_conversation(bound_request, context, definition, confirmed=True)

    def cancel(self, token: str, context: AppActionContext) -> ActionReceipt:
        record = self._receipt_store.get_confirmation(token)
        if record is None:
            request = AppActionRequest(action_id="confirmation.cancel")
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class="unknown",
                error_code="CONFIRMATION_UNAVAILABLE",
                message="Confirmation is unavailable.",
            )
        definition = self._definition(record.action_id)
        if definition is None:
            request = AppActionRequest(action_id=record.action_id)
            self._receipt_store.remove_confirmation(token)
            return self._error_receipt(
                request=request,
                context=context,
                status="unavailable",
                access_class="unknown",
                error_code="ACTION_UNAVAILABLE",
                message="The action is no longer available.",
            )
        request = AppActionRequest(
            action_id=record.action_id,
            action_version=record.action_version,
            arguments=dict(record.arguments),
        )
        self._receipt_store.remove_confirmation(token)
        return ActionReceipt(
            receipt_id=self._receipt_id_factory(),
            request_id=request.request_id,
            action_id=record.action_id,
            action_version=record.action_version,
            source=context.source,
            status="cancelled",
            authorization=self._authorization(definition.access_class, context, allowed=True),
            target=ActionTarget(kind=record.target_kind, id=record.target_reference, revision=record.expected_revision),
            result={"cancelled": True},
            message="Operation cancelled.",
            audit_label=f"{definition.audit_label}.cancelled",
            created_at=self._now(),
        )

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
        self._register(CONVERSATION_FORK_ACTION_ID, "Fork conversation", self._fork_conversation)
        self._register(CONVERSATION_WINDOW_OPEN_ACTION_ID, "Open conversation window", self._open_conversation_window)
        self._register(
            CONVERSATION_SHARE_ACTION_ID,
            "Share conversation",
            self._share_conversation,
            access=CapabilityAccess.EXTERNAL_WRITE,
        )
        self._register(
            CONVERSATION_DELETE_ACTION_ID,
            "Delete conversation",
            self._delete_conversation,
            access=CapabilityAccess.DESTRUCTIVE,
        )
        self._conversation_actions_registered = True

    def set_conversation_sharing_provider(
        self,
        provider: ConversationShareService | Callable[[], ConversationShareService],
    ) -> None:
        self._conversation_sharing = provider

    def _conversation_service(self) -> ConversationLifecycle:
        provider = self._conversation_lifecycle
        if provider is None:
            raise ConversationLifecycleError(
                "CONVERSATION_ACTIONS_UNAVAILABLE",
                "Conversation actions are unavailable.",
            )
        return provider() if callable(provider) else provider

    def _sharing_service(self) -> ConversationShareService:
        provider = self._conversation_sharing
        if provider is None:
            raise ConversationShareError(
                "CONVERSATION_SHARING_UNAVAILABLE",
                "Conversation sharing is unavailable.",
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

    def _fork_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        boundary = str(arguments.get("through_message_id") or "").strip()
        if not boundary and arguments.get("from_selected"):
            selected = str(context.selected_ui_reference or "")
            if selected.startswith("message:"):
                boundary = selected.partition(":")[2].strip()
            if not boundary:
                conversation = self._conversation_service().get(conversation_id)
                messages = conversation.get("messages") if isinstance(conversation.get("messages"), list) else []
                boundary = next(
                    (
                        str(message.get("id") or "").strip()
                        for message in reversed(messages)
                        if isinstance(message, dict) and str(message.get("id") or "").strip()
                    ),
                    "",
                )
                if not boundary:
                    raise ConversationLifecycleError(
                        "FORK_BOUNDARY_REQUIRED",
                        "This chat has no message to fork from.",
                    )
        mutation = self._conversation_service().fork(
            conversation_id,
            through_message_id=boundary,
            title=str(arguments.get("title") or ""),
            expected_revision=self._expected_target_revision(arguments),
        )
        conversation = mutation["conversation"]
        return {
            "changed": True,
            "target_kind": "conversation",
            "target_id": str(conversation["id"]),
            "target_revision": int(conversation.get("revision", 0)),
            "conversation": conversation,
            "fork_boundary": mutation.get("fork_boundary"),
            "copied_context_refs": mutation.get("copied_context_refs", 0),
            "navigation": {"view": "chat", "conversation_id": conversation["id"]},
            "message": f"Forked {conversation.get('title') or 'chat'}.",
        }

    def _open_conversation_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        conversation = self._conversation_service().get(conversation_id)
        return {
            "changed": False,
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": int(conversation.get("revision", 0)),
            "native_window": {"conversation_id": conversation_id},
            "message": f"Opening {conversation.get('title') or 'chat'} in a new window.",
        }

    def _share_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        arguments = dict(payload.get("arguments") or {})
        context = AppActionContext.model_validate(payload.get("context"))
        conversation_id = self._conversation_target(arguments, context)
        conversation = self._conversation_service().get(conversation_id)
        shared = self._sharing_service().share(
            conversation,
            provider_id=str(arguments.get("provider_id") or ""),
        )
        return {
            "changed": True,
            "target_kind": "conversation",
            "target_id": conversation_id,
            "target_revision": int(conversation.get("revision", 0)),
            "share": shared,
            "message": (
                "Local conversation export ready."
                if shared.get("provider_id") == "local_export"
                else "Conversation shared."
            ),
        }

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
        surfaces = self._surface_map(context)
        defaults = {
            reference: surface.default_presentation.model_dump(mode="json")
            for reference, surface in surfaces.items()
        }
        current = {
            reference: self._current_presentation(reference, context).model_dump(mode="json")
            for reference in surfaces
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
        surfaces = self._surface_map(context)
        if normalized in {"this", "this button", "this control", "selected control"}:
            contextual = [context.selected_ui_reference, context.focused_ui_reference]
            matches = [
                surfaces[item]
                for item in contextual
                if item in surfaces
                and (
                    normalized not in {"this button"}
                    or "label" in surfaces[item].configurable_properties
                )
            ]
            unique = {item.reference: item for item in matches}
            if len(unique) == 1:
                return next(iter(unique.values()))
            raise SurfaceActionError(
                "UI_CONTEXT_REQUIRED",
                "Select or name the control you want to change.",
            )
        direct = surfaces.get(normalized)
        if direct:
            return direct
        matches = [
            surface
            for surface in surfaces.values()
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
        surfaces = self._surface_map(context)
        if reference not in surfaces:
            raise SurfaceActionError(
                "UI_REFERENCE_UNAVAILABLE",
                f"{reference or 'That interface surface'} is unavailable.",
            )
        current = context.workspace_layout.surfaces.get(reference)
        if current is not None:
            default = surfaces[reference].default_presentation
            return SurfacePresentation(
                visible=current.visible,
                location=current.location or default.location,
                properties={**default.properties, **current.properties},
            )
        return surfaces[reference].default_presentation.model_copy(deep=True)

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
    def _attachment_definition() -> AppActionDefinition:
        return AppActionDefinition(
            id=ATTACHMENT_IMPORT_ACTION_ID,
            version="1",
            owner="conversation-attachments",
            title="Attach local content",
            description="Attach an explicit file, current clipboard content, or recent attachment.",
            scope="conversation",
            access_class=CapabilityAccess.WRITE.value,
            confirmation_rule="current_user_intent",
            executor_location="server_or_client",
            supports_undo=False,
            idempotent=False,
            argument_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["source"],
                "properties": {
                    "source": {"enum": ["path", "clipboard", "recent", "picker"]},
                    "path": {"type": "string"},
                    "reference": {"type": "string"},
                },
            },
            result_schema={"type": "object", "required": ["attachments"]},
            ui_reference="composer",
            audit_label="conversation.attachment.import",
        )

    @staticmethod
    def _session_control_definitions() -> list[AppActionDefinition]:
        specs = [
            (
                AGENT_SELECT_ACTION_ID,
                "Select an agent",
                "Select the specialist that handles future turns in this chat.",
                {"agent": {"type": "string"}, "agent_id": {"type": "string"}},
                "none",
            ),
            (
                MODEL_SELECT_ACTION_ID,
                "Select a model",
                "Select an available model for this chat without changing the process default.",
                {"model": {"type": "string"}, "model_id": {"type": "string"}},
                "none",
            ),
            (
                REASONING_SET_ACTION_ID,
                "Set reasoning level",
                "Set or reset reasoning effort for this chat.",
                {"mode": {"type": "string"}},
                "none",
            ),
            (
                MEMORY_CONVERSATION_SET_ACTION_ID,
                "Set chat memory",
                "Choose whether future turns in this chat may be stored as memory.",
                {"enabled": {"type": "boolean"}},
                "operation_bound",
            ),
        ]
        return [
            AppActionDefinition(
                id=action_id,
                version="1",
                owner="master-thread-state",
                title=title,
                description=description,
                scope="conversation",
                access_class=CapabilityAccess.WRITE.value,
                confirmation_rule=confirmation_rule,
                executor_location="server_and_client",
                supports_undo=False,
                idempotent=True,
                argument_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                },
                result_schema={"type": "object", "required": ["session_control_patch", "changed"]},
                ui_reference="conversation-runtime",
                audit_label=action_id,
            )
            for action_id, title, description, properties, confirmation_rule in specs
        ]

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
            (CONVERSATION_FORK_ACTION_ID, "Fork a chat", "Create a new canonical conversation through an optional message boundary.", False, False, "none", {"conversation_id": {"type": "string"}, "through_message_id": {"type": "string"}, "from_selected": {"type": "boolean"}, "title": {"type": "string", "maxLength": 160}, "target_revision": {"type": "integer"}, **reference}),
            (CONVERSATION_WINDOW_OPEN_ACTION_ID, "Open a chat in a new window", "Open the canonical conversation in a native Vellum window.", False, True, "none", {"conversation_id": {"type": "string"}, **reference}),
            (CONVERSATION_SHARE_ACTION_ID, "Share a chat", "Prepare a reviewable local JSON export after confirmation.", False, False, "operation_bound", {"conversation_id": {"type": "string"}, "provider_id": {"type": "string"}, "target_revision": {"type": "integer"}, **reference}),
        ]
        return [
            AppActionDefinition(
                id=action_id,
                version="1",
                owner="conversation-lifecycle",
                title=title,
                description=description,
                scope="conversation",
                access_class=(
                    CapabilityAccess.DESTRUCTIVE.value
                    if action_id == CONVERSATION_DELETE_ACTION_ID
                    else CapabilityAccess.EXTERNAL_WRITE.value
                    if action_id == CONVERSATION_SHARE_ACTION_ID
                    else CapabilityAccess.WRITE.value
                ),
                confirmation_rule=confirmation_rule,
                executor_location="client" if action_id in {CONVERSATION_NEW_ACTION_ID, CONVERSATION_OPEN_ACTION_ID, CONVERSATION_WINDOW_OPEN_ACTION_ID} else "server",
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
        from agent.plugins.registry import get_plugin_registry

        _runtime = AppActionRuntime(plugin_registry=get_plugin_registry())
    return _runtime


def reset_app_action_runtime() -> None:
    global _runtime
    _runtime = None
