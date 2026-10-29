"""Canonical YouTube connection controls and their plugin-owned App Actions."""

from __future__ import annotations

import secrets
import time
from typing import Any, Callable
from uuid import uuid4

from agent.app_actions.models import AppActionDefinition
from agent.config import get_settings
from agent.contracts.youtube_history import YouTubeHistoryConfig
from agent.knowledge.runtime import get_knowledge_core
from agent.plugins.contributions import (
    PluginActionContribution,
    PluginContribution,
    PluginContributionActionError,
)
from agent.plugins.youtube_contract import (
    YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
    YOUTUBE_CONNECTION_START_ACTION_ID,
    YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
    YOUTUBE_HISTORY_REFRESH_ACTION_ID,
    YOUTUBE_REDIRECT_URI,
    YOUTUBE_SYNC_ACTION_ID,
)
from agent.plugins.youtube_intelligence import YouTubeIntelligenceService
from agent.plugins.youtube_runtime import (
    YouTubeAPIError,
    YouTubeAuthError,
    YouTubeKnowledgeSync,
    youtube_authorization_url,
    youtube_client,
    youtube_pkce_pair,
    youtube_status,
    youtube_store,
)
from agent.tools.registry import CapabilityAccess
from agent.contracts.youtube_tracking import CreatorTrackingConfig


class YouTubeControlService:
    """One interface over existing YouTube auth, sync, and Knowledge projection owners."""

    def __init__(
        self,
        *,
        settings_provider=get_settings,
        status_provider=youtube_status,
        store_provider=youtube_store,
        client_provider=youtube_client,
        sync_factory=YouTubeKnowledgeSync,
        pkce_provider=youtube_pkce_pair,
        authorization_url_provider=youtube_authorization_url,
        state_factory=lambda: secrets.token_urlsafe(32),
        knowledge_core_provider=get_knowledge_core,
        intelligence_factory=YouTubeIntelligenceService,
        history_factory=None,
    ) -> None:
        self._settings_provider = settings_provider
        self._status_provider = status_provider
        self._store_provider = store_provider
        self._client_provider = client_provider
        self._sync_factory = sync_factory
        self._pkce_provider = pkce_provider
        self._authorization_url_provider = authorization_url_provider
        self._state_factory = state_factory
        self._knowledge_core_provider = knowledge_core_provider
        self._intelligence_factory = intelligence_factory
        self._history_factory = history_factory

    def start_connection(self) -> dict[str, Any]:
        settings = self._settings_provider()
        if not settings.youtube_oauth_client_id:
            raise PluginContributionActionError(
                "YOUTUBE_NOT_CONFIGURED",
                "Set YOUTUBE_OAUTH_CLIENT_ID before connecting YouTube.",
                unavailable=True,
            )
        verifier, challenge = self._pkce_provider()
        state = self._state_factory()
        self._store_provider().save_flow({
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "created_at": time.time(),
        })
        url = self._authorization_url_provider(
            client_id=settings.youtube_oauth_client_id,
            redirect_uri=YOUTUBE_REDIRECT_URI,
            state=state,
            code_challenge=challenge,
        )
        return {
            "authorization_url": url,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
        }

    def sync(self, *, idempotency_key: str = "") -> dict[str, Any]:
        if not self._status_provider().get("connected"):
            raise PluginContributionActionError(
                "YOUTUBE_NOT_CONNECTED",
                "Connect YouTube before synchronizing account data.",
                unavailable=True,
            )
        try:
            return self._sync_factory().run(
                idempotency_key=idempotency_key.strip() or f"manual:{uuid4().hex}",
                requested_by="user",
            )
        except YouTubeAuthError as exc:
            raise PluginContributionActionError(
                "YOUTUBE_REAUTH_REQUIRED",
                "YouTube authorization must be renewed.",
                unavailable=True,
            ) from exc
        except YouTubeAPIError as exc:
            raise PluginContributionActionError(
                "YOUTUBE_SYNC_UNAVAILABLE",
                "YouTube synchronization is unavailable.",
                unavailable=True,
            ) from exc

    def disconnect(self) -> dict[str, Any]:
        try:
            self._client_provider().disconnect()
        except YouTubeAuthError as exc:
            raise PluginContributionActionError(
                "YOUTUBE_DISCONNECT_FAILED",
                "YouTube disconnection could not be completed.",
            ) from exc
        return {"disconnected": True}

    def rebuild_intelligence(self, *, mode: str = "") -> dict[str, Any]:
        intelligence = self._intelligence_factory(self._knowledge_core_provider().store)
        try:
            if mode:
                return intelligence.rebuild(mode=mode)
            return intelligence.rebuild()
        except Exception as exc:  # noqa: BLE001
            raise PluginContributionActionError(
                "YOUTUBE_INTELLIGENCE_REBUILD_FAILED",
                "YouTube intelligence rebuild failed.",
            ) from exc

    def execute(self, action_id: str, arguments: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        if action_id in {"youtube.creators.configure", "youtube.creators.refresh"}:
            from agent.plugins.youtube_creator_tracking import YouTubeCreatorTracking
            tracking = YouTubeCreatorTracking(store=self._knowledge_core_provider().store)
            result = tracking.configure(arguments) if action_id.endswith("configure") else tracking.refresh()
            return {"changed": True, "tracking": result, "_target_kind": "knowledge_projection",
                "_target_id": "youtube-creators", "_message": "Creator tracking settings saved." if action_id.endswith("configure") else "Creator feeds checked; queued uploads will be delivered by the creator automation."}
        if action_id == "youtube.history.configure":
            from agent.plugins.youtube_browser_history import YouTubeBrowserHistory
            history = YouTubeBrowserHistory(store=self._knowledge_core_provider().store)
            result = history.configure(arguments)
            return {"changed": True, "history": result, "_target_kind": "knowledge_projection",
                "_target_id": "youtube_history", "_message": "History settings saved."}
        if action_id == YOUTUBE_CONNECTION_START_ACTION_ID:
            connection = self.start_connection()
            return {
                "changed": True,
                "connection": connection,
                "client_effect": {"type": "youtube.oauth.open", "authorization_url": connection["authorization_url"]},
                "_target_kind": "connector_connection",
                "_target_id": "youtube",
                "_message": "YouTube authorization is ready.",
            }
        if action_id == YOUTUBE_SYNC_ACTION_ID:
            sync = self.sync(idempotency_key=str(arguments.get("idempotency_key") or ""))
            return {
                "changed": True,
                "sync": _safe_sync_result(sync),
                "_target_kind": "knowledge_projection",
                "_target_id": "youtube",
                "_message": "Synchronized YouTube subscriptions into local Knowledge.",
            }
        if action_id == YOUTUBE_HISTORY_REFRESH_ACTION_ID:
            from agent.plugins.youtube_browser_history import YouTubeBrowserHistoryService, HistoryReadError
            try:
                reader = self._history_factory() if self._history_factory else YouTubeBrowserHistoryService(store=self._knowledge_core_provider().store)
                history = reader.refresh()
            except HistoryReadError as exc:
                raise PluginContributionActionError('YOUTUBE_HISTORY_UNAVAILABLE', str(exc)) from None
            from agent.plugins.youtube_browser_history import YouTubeBrowserHistory
            receipt = YouTubeBrowserHistory(store=reader.store).status()
            return {'changed':True, 'history':{**receipt, **{key:history[key] for key in
                ('total','refreshed_at','account_id','source_id','local_only','truncated')}},
                '_target_kind':'knowledge_projection', '_target_id':history['source_id'],
                '_message':f"Refreshed {history['total']} recent YouTube history entries from Vellum’s Browser."}
        if action_id == YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID:
            if not confirmed:
                raise PluginContributionActionError("CONFIRMATION_REQUIRED", "Confirm disconnecting YouTube.")
            result = self.disconnect()
            return {
                "changed": True,
                **result,
                "_target_kind": "connector_connection",
                "_target_id": "youtube",
                "_message": "YouTube disconnected.",
            }
        if action_id == YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID:
            result = self.rebuild_intelligence(mode=str(arguments.get("mode") or ""))
            return {
                "changed": True,
                "intelligence": _safe_intelligence_result(result),
                "_target_kind": "knowledge_projection",
                "_target_id": "youtube-intelligence",
                "_message": "Rebuilt local YouTube intelligence.",
            }
        raise PluginContributionActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)


def youtube_plugin_contribution(
    service: YouTubeControlService | None = None,
    *,
    status_provider: Callable[[], dict[str, Any]] = youtube_status,
) -> PluginContribution:
    controls = service or YouTubeControlService()

    def contribution(action_id: str, definition: AppActionDefinition, availability=None) -> PluginActionContribution:
        return PluginActionContribution(
            definition=definition,
            availability=availability,
            adapter=lambda payload, registered=action_id: controls.execute(
                registered,
                dict(payload.get("arguments") or {}),
                confirmed=payload.get("confirmed") is True,
            ),
        )

    def configured(_context) -> bool:
        return bool(status_provider().get("configured"))

    def connected(_context) -> bool:
        return bool(status_provider().get("connected"))

    common = {
        "version": "1",
        "owner": "youtube",
        "plugin_id": "youtube",
        "scope": "user",
        "executor_location": "server",
        "supports_undo": False,
        "idempotent": False,
        "result_schema": {"type": "object", "required": ["changed"]},
    }
    return PluginContribution(owner="youtube", actions=(
        contribution("youtube.creators.configure", AppActionDefinition(
            id="youtube.creators.configure", title="Configure creator tracking",
            description="Save account-scoped creator relationships, hard exclusions, and public-feed request limits locally. Enabled tracking resolves missing ownership using public video IDs and can fall back to public uploads playlists through the connected YouTube API.",
            access_class=CapabilityAccess.WRITE.value, confirmation_rule="none",
            argument_schema=CreatorTrackingConfig.model_json_schema(),
            ui_reference="youtube.connection", audit_label="youtube.creators.configure",
            required_permissions=["youtube.creators.configure"], **common)),
        contribution("youtube.creators.refresh", AppActionDefinition(
            id="youtube.creators.refresh", title="Check creator uploads",
            description="Assess saved watches locally and read bounded public channel feeds; queue new uploads for automation delivery.",
            access_class=CapabilityAccess.WRITE.value, confirmation_rule="none",
            argument_schema={"type": "object", "additionalProperties": False},
            ui_reference="youtube.connection", audit_label="youtube.creators.refresh",
            required_permissions=["youtube.creators.refresh"], **common)),
        contribution(YOUTUBE_HISTORY_REFRESH_ACTION_ID, AppActionDefinition(
            id=YOUTUBE_HISTORY_REFRESH_ACTION_ID, title='Refresh history',
            description='Read recent watch history from the YouTube account signed into Vellum’s Browser and save it locally.',
            access_class=CapabilityAccess.WRITE.value, confirmation_rule='none',
            argument_schema={'type':'object', 'additionalProperties':False}, ui_reference='youtube.history',
            audit_label='youtube.history.refresh', required_permissions=[YOUTUBE_HISTORY_REFRESH_ACTION_ID], **common)),
        contribution(
            "youtube.history.configure",
            AppActionDefinition(id="youtube.history.configure", title="Configure YouTube history",
                description="Set the supported History URL and timezone used to interpret date headings.",
                access_class=CapabilityAccess.WRITE.value, confirmation_rule="none",
                argument_schema=YouTubeHistoryConfig.model_json_schema(),
                ui_reference="youtube.connection", audit_label="youtube.history.configure",
                required_permissions=["youtube.history.configure"], **common),
        ),
        contribution(
            YOUTUBE_CONNECTION_START_ACTION_ID,
            AppActionDefinition(
                id=YOUTUBE_CONNECTION_START_ACTION_ID,
                title="Connect YouTube",
                description="Start the canonical read-only YouTube OAuth flow.",
                access_class=CapabilityAccess.EXTERNAL_WRITE.value,
                confirmation_rule="oauth_consent",
                argument_schema={"type": "object", "additionalProperties": False},
                ui_reference="youtube.connection",
                audit_label="youtube.connection.start",
                required_permissions=[YOUTUBE_CONNECTION_START_ACTION_ID],
                **common,
            ),
            configured,
        ),
        contribution(
            YOUTUBE_SYNC_ACTION_ID,
            AppActionDefinition(
                id=YOUTUBE_SYNC_ACTION_ID,
                title="Synchronize YouTube",
                description="Import subscriptions through the canonical local Knowledge projection.",
                access_class=CapabilityAccess.WRITE.value,
                confirmation_rule="none",
                argument_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"idempotency_key": {"type": "string"}},
                },
                ui_reference="youtube.connection",
                audit_label="youtube.sync",
                required_permissions=[YOUTUBE_SYNC_ACTION_ID],
                **common,
            ),
            connected,
        ),
        contribution(
            YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
            AppActionDefinition(
                id=YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
                title="Disconnect YouTube",
                description="Remove the canonical local YouTube OAuth connection after confirmation.",
                access_class=CapabilityAccess.DESTRUCTIVE.value,
                confirmation_rule="operation_bound",
                argument_schema={"type": "object", "additionalProperties": False},
                ui_reference="youtube.connection",
                audit_label="youtube.connection.disconnect",
                required_permissions=[YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID],
                **common,
            ),
            connected,
        ),
        contribution(
            YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
            AppActionDefinition(
                id=YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
                title="Rebuild YouTube intelligence",
                description="Rebuild the derived local YouTube Knowledge projection.",
                access_class=CapabilityAccess.WRITE.value,
                confirmation_rule="none",
                argument_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"mode": {"enum": ["backfill", "incremental"]}},
                },
                ui_reference="youtube.intelligence",
                audit_label="youtube.intelligence.rebuild",
                required_permissions=[YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID],
                **common,
            ),
        ),
    ))


def _safe_sync_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = ("status", "job_id", "connector", "processed", "created", "updated", "unchanged")
    return {key: result[key] for key in allowed if key in result}


def _safe_intelligence_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = ("status", "mode", "phase", "local_only", "counts", "readiness")
    return {key: result[key] for key in allowed if key in result}
