"""Canonical Spotify connection controls and their plugin-owned App Actions."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from typing import Any

from agent.app_actions.models import AppActionDefinition
from agent.plugins.contributions import (
    PluginActionContribution,
    PluginContribution,
    PluginContributionActionError,
)
from agent.plugins.registry import get_plugin_registry
from agent.plugins.spotify_runtime import (
    spotify_authorization_url,
    spotify_is_authenticated,
    spotify_pkce_pair,
    spotify_store,
)
from agent.tools.registry import CapabilityAccess


SPOTIFY_CONNECTION_START_ACTION_ID = "spotify.connection.start"
SPOTIFY_CONNECTION_DISCONNECT_ACTION_ID = "spotify.connection.disconnect"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8000/api/plugins/spotify/oauth/callback"


class SpotifyConnectionService:
    """Delegate Spotify connection mutations to the existing local auth store."""

    def __init__(
        self,
        *,
        store_provider=spotify_store,
        pkce_provider=spotify_pkce_pair,
        authorization_url_provider=spotify_authorization_url,
        state_factory=lambda: secrets.token_urlsafe(32),
        invalidator: Callable[[], None] = lambda: None,
    ) -> None:
        self._store_provider = store_provider
        self._pkce_provider = pkce_provider
        self._authorization_url_provider = authorization_url_provider
        self._state_factory = state_factory
        self._invalidator = invalidator

    def execute(self, action_id: str, arguments: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        if action_id == SPOTIFY_CONNECTION_START_ACTION_ID:
            client_id = str(arguments.get("client_id") or "").strip()
            if not client_id:
                return {
                    "changed": False,
                    "client_effect": {"type": "spotify.connection.modal.open"},
                    "_target_kind": "connector_connection",
                    "_target_id": "spotify",
                    "_message": "Open Spotify connection settings to continue.",
                }
            if len(client_id) > 128 or re.fullmatch(r"[A-Za-z0-9]+", client_id) is None:
                raise PluginContributionActionError(
                    "INVALID_ACTION_ARGUMENTS",
                    "Spotify Client ID is invalid.",
                )
            verifier, challenge = self._pkce_provider()
            state = self._state_factory()
            self._store_provider().save_flow({
                "state": state,
                "code_verifier": verifier,
                "client_id": client_id,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
                "created_at": time.time(),
            })
            url = self._authorization_url_provider(
                client_id=client_id,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                state=state,
                code_challenge=challenge,
            )
            return {
                "changed": True,
                "connection": {"authorization_url": url, "redirect_uri": SPOTIFY_REDIRECT_URI},
                "client_effect": {"type": "spotify.oauth.open", "authorization_url": url},
                "_target_kind": "connector_connection",
                "_target_id": "spotify",
                "_message": "Spotify authorization is ready.",
            }
        if action_id == SPOTIFY_CONNECTION_DISCONNECT_ACTION_ID:
            if not confirmed:
                raise PluginContributionActionError("CONFIRMATION_REQUIRED", "Confirm disconnecting Spotify.")
            self._store_provider().logout()
            self._invalidator()
            return {
                "changed": True,
                "disconnected": True,
                "_target_kind": "connector_connection",
                "_target_id": "spotify",
                "_message": "Spotify disconnected.",
            }
        raise PluginContributionActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)


def spotify_plugin_contribution(
    service: SpotifyConnectionService | None = None,
    *,
    invalidator: Callable[[], None] = lambda: None,
    authenticated: Callable[[], bool] = spotify_is_authenticated,
) -> PluginContribution:
    controls = service or SpotifyConnectionService(invalidator=invalidator)

    def contribution(
        action_id: str,
        definition: AppActionDefinition,
        availability=None,
    ) -> PluginActionContribution:
        return PluginActionContribution(
            definition=definition,
            availability=availability,
            adapter=lambda payload, registered=action_id: controls.execute(
                registered,
                dict(payload.get("arguments") or {}),
                confirmed=payload.get("confirmed") is True,
            ),
        )

    def plugin_enabled(_context) -> bool:
        return get_plugin_registry().is_enabled("spotify")

    def connected(context) -> bool:
        return plugin_enabled(context) and authenticated()

    common = {
        "version": "1",
        "owner": "spotify",
        "plugin_id": "spotify",
        "scope": "user",
        "executor_location": "server",
        "supports_undo": False,
        "idempotent": False,
        "result_schema": {"type": "object", "required": ["changed"]},
    }
    return PluginContribution(owner="spotify", actions=(
        contribution(
            SPOTIFY_CONNECTION_START_ACTION_ID,
            AppActionDefinition(
                id=SPOTIFY_CONNECTION_START_ACTION_ID,
                title="Connect Spotify",
                description="Open Spotify setup or start the canonical PKCE authorization flow.",
                access_class=CapabilityAccess.EXTERNAL_WRITE.value,
                confirmation_rule="oauth_consent",
                argument_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"client_id": {"type": "string", "writeOnly": True}},
                },
                ui_reference="spotify.connection",
                audit_label="spotify.connection.start",
                required_permissions=[SPOTIFY_CONNECTION_START_ACTION_ID],
                **common,
            ),
            plugin_enabled,
        ),
        contribution(
            SPOTIFY_CONNECTION_DISCONNECT_ACTION_ID,
            AppActionDefinition(
                id=SPOTIFY_CONNECTION_DISCONNECT_ACTION_ID,
                title="Disconnect Spotify",
                description="Remove the canonical local Spotify connection after confirmation.",
                access_class=CapabilityAccess.DESTRUCTIVE.value,
                confirmation_rule="operation_bound",
                argument_schema={"type": "object", "additionalProperties": False},
                ui_reference="spotify.connection",
                audit_label="spotify.connection.disconnect",
                required_permissions=[SPOTIFY_CONNECTION_DISCONNECT_ACTION_ID],
                **common,
            ),
            connected,
        ),
    ))
