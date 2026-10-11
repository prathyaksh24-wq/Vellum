"""Spotify browser-player contracts and contribution to the existing App Actions."""

import json
import re
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.app_actions.models import AppActionDefinition, AppActionRequest
import secrets
import time
from collections.abc import Callable
from typing import Any
from agent.tools.registry import CapabilityAccess
from agent.plugins.registry import get_plugin_registry
from agent.plugins.spotify_runtime import (
    SpotifyAuthError, spotify_authorization_url, spotify_is_authenticated,
    spotify_pkce_pair, spotify_store,
)
from agent.contracts.music import match_music_control
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError
from agent.plugins.spotify_runtime import SpotifyError, spotify_client, spotify_playback, spotify_devices, spotify_catalog_query_gate, _spotify_module


class SpotifyPlayerActionRequest(BaseModel):
    action: Literal["play", "pause", "next", "previous", "seek", "set_volume", "set_shuffle", "set_repeat", "transfer"]
    device_id: str | None = None
    position_ms: int | None = Field(default=None, ge=0)
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    shuffle: bool | None = None
    state: Literal["track", "context", "off"] | None = None
    play: bool = False


class SpotifyPlaybackControlRequest(SpotifyPlayerActionRequest):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=500)
    context_uri: str | None = Field(default=None, pattern=r'^spotify:(?:album|playlist):[A-Za-z0-9]+$')
    uris: list[str] | None = Field(default=None, min_length=1, max_length=50)
    offset_position: int | None = Field(default=None, ge=0, le=100000)

    @model_validator(mode='after')
    def playback_source(self):
        sources = [self.query is not None, self.context_uri is not None, self.uris is not None]
        if sum(sources) > 1 or (any(sources) and self.action != 'play'):
            raise ValueError('Choose a single source for play')
        if self.uris and any(not re.fullmatch(r'spotify:(?:track|episode):[A-Za-z0-9]+', uri) for uri in self.uris):
            raise ValueError('Choose valid Spotify track or episode URIs')
        if self.offset_position is not None and not self.context_uri:
            raise ValueError('A track position requires an album or playlist context')
        return self


def match_spotify_command(message: str) -> AppActionRequest | None:
    """Complete playback instructions only; discussion stays with the agent."""
    text = " ".join(message.split()).rstrip(".!?")
    polite = r"(?:please )?(?:(?:can|could|would) you )?(?:please )?"
    command = re.sub("^" + polite, "", text, flags=re.I)
    # Literal suffix checks avoid scanning/backtracking over unbounded whitespace.
    for suffix in (" on spotify", " spotify"):
        if command.casefold().endswith(suffix):
            command = command[:-len(suffix)]
            break
    playlist_action = match_spotify_playlist_command(command)
    if playlist_action:
        return playlist_action
    control = match_music_control(command)
    if control:
        # A bare 'pause' has a music meaning only while this Vellum device is selected.
        if not re.search(r"\b(?:spotify|song|track|music|episode|podcast)\b", text, re.I) and spotify_client().web_playback_status()["status"] == "disabled":
            return None
        action = "play" if control == "resume" else control
        return AppActionRequest(action_id="spotify.playback.control", arguments={"action": action})
    # Song and playlist interpretation belongs to MusicAgent, not a UI matcher.
    return None


SPOTIFY_PLAYLIST_EDIT_ACTION_ID = 'spotify.playlist.edit'


class SpotifyPlaylistEditRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['update_details', 'remove', 'add_items', 'remove_items']
    playlist_id: str = Field(default='', max_length=100, pattern=r'^[A-Za-z0-9]*$')
    playlist_name: str = Field(default='', max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=300)
    uris: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def validate_operation(self):
        if self.name is not None and not self.name.strip():
            raise ValueError('Enter a playlist name')
        if self.operation == 'update_details':
            if self.name is None and self.description is None:
                raise ValueError('Supply a name or description')
        elif self.name is not None or self.description is not None:
            raise ValueError('Details are only valid with update_details')
        if self.operation in {'add_items', 'remove_items'}:
            if not self.uris or any(not re.fullmatch(r'spotify:track:[A-Za-z0-9]+', uri) for uri in self.uris):
                raise ValueError('Choose valid Spotify songs')
        elif self.uris:
            raise ValueError('Songs are only valid with add_items or remove_items')
        return self


def match_spotify_playlist_command(command: str) -> AppActionRequest | None:
    """Exact editing intent; ambiguous names are resolved from the saved library."""
    def target(value):
        value = value.strip().strip('\"\'')
        if value.casefold() in {'this playlist', 'that playlist', 'the playlist', 'my playlist'}:
            return ''
        value = re.sub(r'^(?:my|the)\s+', '', value, flags=re.I)
        value = re.sub(r'^playlist\s+|\s+playlist$', '', value, flags=re.I)
        return value.strip().strip('\"\'')

    rename = re.fullmatch(r'(?:rename|change\s+(?:the\s+)?name\s+of)\s+(.+?)\s+to\s+(.+)', command, re.I)
    if not rename:
        rename = re.fullmatch(r'(?:change|set)\s+(.+?playlist)(?:[’\']s)?\s+name\s+to\s+(.+)', command, re.I)
    if rename and 'playlist' in rename[1].casefold():
        return AppActionRequest(action_id=SPOTIFY_PLAYLIST_EDIT_ACTION_ID,
            arguments={'operation':'update_details', 'playlist_name':target(rename[1]), 'name':rename[2].strip().strip('\"\'')})
    description = re.fullmatch(r'(?:change|set|edit)\s+(?:the\s+)?description\s+of\s+(.+?)\s+to\s+(.+)', command, re.I)
    if description and 'playlist' in description[1].casefold():
        return AppActionRequest(action_id=SPOTIFY_PLAYLIST_EDIT_ACTION_ID,
            arguments={'operation':'update_details', 'playlist_name':target(description[1]), 'description':description[2].strip().strip('\"\'')})
    remove = re.fullmatch(r'(?:remove|delete|unsave|unfollow)\s+(.+?\bplaylist|playlist\s+.+?)(?:\s+from\s+(?:my|the)\s+(?:spotify\s+)?library)?', command, re.I)
    if remove:
        return AppActionRequest(action_id=SPOTIFY_PLAYLIST_EDIT_ACTION_ID,
            arguments={'operation':'remove', 'playlist_name':target(remove[1])})
    return None


def prepare_spotify_playlist_edit(arguments: dict, context) -> dict:
    """Pin account, playlist and revision into the existing confirmation record."""
    from agent.tools.capabilities.spotify_service import SpotifyCapabilityService, playlist_key
    args = SpotifyPlaylistEditRequest.model_validate(arguments)
    service = spotify_client()
    playlist_id = args.playlist_id
    if not playlist_id and args.playlist_name:
        rows = SpotifyCapabilityService.saved_playlists(lambda name, body: _result(_spotify_module.tools.HANDLERS[name](body, service=service)))
        matches = [row for row in rows if playlist_key(row.get('name', '')) == playlist_key(args.playlist_name)]
        if len(matches) != 1:
            raise PluginContributionActionError('PLAYLIST_TARGET_REQUIRED', 'Give the exact playlist name or open it on the Music page; no playlist was changed.')
        playlist_id = matches[0]['id']
    if not playlist_id:
        uri = context.music_collection_uri
        if not re.fullmatch(r'spotify:playlist:[A-Za-z0-9]+', uri):
            raise PluginContributionActionError('PLAYLIST_TARGET_REQUIRED', 'Open a playlist on the Music page or give its exact name; no playlist was changed.')
        playlist_id = uri.split(':')[-1]
    profile = _result(_spotify_module.tools._result(service.get_profile))
    playlist = _result(_spotify_module.tools.spotify_playlists({'action':'get', 'playlist_id':playlist_id}, service=service))
    if playlist.get('id') != playlist_id or not profile.get('id'):
        raise PluginContributionActionError('PLAYLIST_UNVERIFIED', 'Spotify could not verify the playlist and account.')
    if args.operation != 'remove' and (playlist.get('owner') or {}).get('id') != profile['id']:
        raise PluginContributionActionError('PLAYLIST_NOT_OWNED', 'You can edit playlists you own. This playlist can only be removed from your library.')
    label = playlist.get('name') or 'Untitled playlist'
    if args.operation == 'remove':
        message = f'Remove {label} from your Spotify library?'
    elif args.operation == 'update_details':
        changes = []
        if args.name is not None:
            changes.append(f'Rename {label} to {args.name}')
        if args.description is not None:
            changes.append(f'Set its description to “{args.description}”' if args.description else 'Clear its description')
        message = '; '.join(changes) + '?'
    else:
        titles = []
        for uri in args.uris:
            track = _result(_spotify_module.tools._result(lambda uri=uri: service.request('GET', '/tracks/' + uri.split(':')[-1])))
            if track.get('uri') != uri or not track.get('name'):
                raise PluginContributionActionError('PLAYLIST_SONG_UNVERIFIED', 'Spotify could not verify the selected song; no change was made.')
            titles.append(track['name'] + (' by ' + ', '.join(a['name'] for a in track.get('artists',[]) if a.get('name')) if track.get('artists') else ''))
        message = f"{'Add' if args.operation == 'add_items' else 'Remove all occurrences of'} {', '.join(titles)} {'to' if args.operation == 'add_items' else 'from'} {label}?"
    return {'playlist_id':playlist_id, 'playlist_name':label, 'account_id':profile['id'],
            'snapshot_id':playlist.get('snapshot_id') or '', 'message':message}


def execute_spotify_playlist_edit(payload: dict) -> dict:
    args = SpotifyPlaylistEditRequest.model_validate(payload.get('arguments') or {})
    binding = payload.get('confirmation_binding') or {}
    if payload.get('confirmed') is not True or not binding.get('playlist_id'):
        raise PluginContributionActionError('CONFIRMATION_REQUIRED', 'Confirm the exact playlist change first.')
    service = spotify_client()
    playlist_id, label = binding['playlist_id'], binding['playlist_name']
    profile = _result(_spotify_module.tools._result(service.get_profile))
    if profile.get('id') != binding.get('account_id'):
        raise PluginContributionActionError('SPOTIFY_ACCOUNT_CHANGED', 'Spotify account changed; request the edit again.')
    call = lambda body: _result(_spotify_module.tools.spotify_playlists(body, service=service))
    playlist = call({'action':'get', 'playlist_id':playlist_id})
    if playlist.get('id') != playlist_id or playlist.get('name') != label or (binding.get('snapshot_id') and playlist.get('snapshot_id') != binding['snapshot_id']):
        raise PluginContributionActionError('PLAYLIST_CHANGED', 'The playlist changed before confirmation. Refresh it and request the edit again.')
    if args.operation != 'remove' and (playlist.get('owner') or {}).get('id') != profile['id']:
        raise PluginContributionActionError('PLAYLIST_NOT_OWNED', 'You no longer own this playlist; no edit was made.')
    if args.operation == 'remove':
        uri = 'spotify:playlist:' + playlist_id
        _result(_spotify_module.tools.spotify_library({'action':'remove', 'kind':'playlists', 'uris':[uri], 'confirm':True}, service=service))
        contains = _result(_spotify_module.tools.spotify_library({'action':'contains', 'kind':'playlists', 'uris':[uri]}, service=service))
        if contains.get('items') != [False]:
            raise PluginContributionActionError('PLAYLIST_EDIT_UNVERIFIED', 'Spotify accepted removal but has not verified it. Refresh your library before retrying.')
        message = f'Removed {label} from your Spotify library.'
    elif args.operation == 'update_details':
        updates = args.model_dump(include={'name','description'}, exclude_none=True)
        call({'action':'update_details', 'playlist_id':playlist_id, **updates, 'confirm':True})
        saved = call({'action':'get', 'playlist_id':playlist_id})
        if any(saved.get(key) != value for key, value in updates.items()):
            raise PluginContributionActionError('PLAYLIST_EDIT_UNVERIFIED', 'Spotify accepted the edit but has not verified it. Refresh before retrying.')
        message = f'Renamed {label} to {args.name}.' if args.name is not None else f'Updated the description of {label}.'
    else:
        from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
        invoke = lambda name, body: _result(_spotify_module.tools.HANDLERS[name](body, service=service))
        # Bound checks complete before writing. URI removal intentionally removes duplicates.
        for uri in args.uris:
            exists = SpotifyCapabilityService._playlist_contains(playlist_id, uri, invoke, deadline=time.monotonic()+12)
            if (args.operation == 'add_items') == exists:
                raise PluginContributionActionError('PLAYLIST_SONG_CHANGED', 'A selected song is already added or no longer present. Refresh before editing.')
        call({'action':args.operation, 'playlist_id':playlist_id, 'uris':args.uris, 'snapshot_id':binding.get('snapshot_id'), 'confirm':True})
        for uri in args.uris:
            exists = SpotifyCapabilityService._playlist_contains(playlist_id, uri, invoke, deadline=time.monotonic()+12)
            if exists != (args.operation == 'add_items'):
                raise PluginContributionActionError('PLAYLIST_EDIT_UNVERIFIED', 'Spotify accepted the song edit but has not verified it. Refresh before retrying.')
        message = f"{'Added' if args.operation == 'add_items' else 'Removed'} {len(args.uris)} song(s) {'to' if args.operation == 'add_items' else 'from'} {label}."
    return {'changed':True, 'playlist_id':playlist_id, 'removed':args.operation == 'remove',
            'name':args.name or label, 'operation':args.operation,
            '_target_kind':'spotify_playlist', '_target_id':playlist_id, '_message':message}


def _result(text: str) -> dict:
    result = json.loads(text)
    if not result.get("ok"):
        error = result.get("error") or {}
        raise PluginContributionActionError(str(error.get("code") or "SPOTIFY_FAILED"), str(error.get("message") or "Spotify could not complete this action."))
    return result.get("data") or {}


def execute_spotify_control(payload: dict) -> dict:
    args = SpotifyPlaybackControlRequest.model_validate(payload.get("arguments") or {})
    service = spotify_client()
    body = args.model_dump(exclude_none=True, exclude={"query"})
    if args.offset_position is not None:
        body.pop('offset_position')
        body['offset'] = {'position':args.offset_position}
    message = {"play": "Spotify playback requested.", "pause": "Spotify paused.", "next": "Skipped to the next track.", "previous": "Previous track requested."}.get(args.action, "Spotify control applied.")
    if args.query:
        if args.action != "play":
            raise PluginContributionActionError("INVALID_ARGUMENTS", "A song title is only valid with play.")
        # Resolve the selected device before searching, and retain the canonical privacy gate.
        try:
            service.preferred_device_id()
        except SpotifyError as exc:
            raise PluginContributionActionError(exc.code, str(exc)) from exc
        found = _result(_spotify_module.tools.spotify_search({"query": args.query, "types": ["track"], "limit": 10}, service=service, privacy_gate=spotify_catalog_query_gate))
        tracks = [t for t in found.get("tracks", {}).get("items", []) if t.get("uri") and t.get("is_playable") is not False]
        if not tracks:
            raise PluginContributionActionError("TRACK_NOT_FOUND", "No playable song matched that title.")
        def normalized(value):
            return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)).strip()
        track = next((t for t in tracks if normalized(t.get("name", "")) == normalized(args.query)), tracks[0])
        body["uris"] = [track["uri"]]
        artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
        message = f"Playing {track.get('name', args.query)}" + (f" by {artists}." if artists else ".")
    handler = spotify_devices if args.action == "transfer" else spotify_playback
    result = _result(handler(body, service=service))
    return {"changed": True, **result, "_message": message}


class SpotifyPlaybackSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: UUID
    operation: Literal["enable", "disable"]


class SpotifyPlaybackDeviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: UUID
    device_id: str = Field(default="", max_length=256, pattern=r"^[A-Za-z0-9_-]*$")
    diagnostics: list["SpotifyPlaybackDiagnostic"] = Field(default_factory=list, max_length=32)
    observation: "SpotifyPlaybackObservation | None" = None
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    volume_ack: str = Field(default='', max_length=80)


class SpotifyObservedTrack(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(default='', max_length=100)
    uri: str = Field(pattern=r'^spotify:(?:track|episode):[A-Za-z0-9]+$')
    name: str = Field(max_length=500)


class SpotifyPlaybackObservation(BaseModel):
    """Transient SDK state from the currently leased, trusted playback window."""
    model_config = ConfigDict(extra='forbid')
    track: SpotifyObservedTrack | None = None
    artists: list[str] = Field(default_factory=list, max_length=20)
    is_playing: bool = False
    progress_ms: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    artwork_url: str = Field(default='', max_length=2048)
    album: str = Field(default='', max_length=500)
    shuffle: bool = False
    repeat: Literal['off','context','track'] = 'off'


class SpotifyVolumeRequest(BaseModel):
    id: str
    percent: int = Field(ge=0, le=100)


class SpotifyPlaybackDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["connecting", "ready", "not_ready", "authentication_error", "autoplay_failed", "initialization_error", "account_error", "playback_error", "state", "connect_timeout"]
    at_ms: int = Field(ge=0)
    paused: bool | None = None
    position_ms: int | None = Field(default=None, ge=0)
    volume_percent: int | None = Field(default=None, ge=0, le=100)


class SpotifyPlaybackSessionResponse(BaseModel):
    status: Literal["connecting", "ready", "reconnecting", "disabled"]
    volume_request: SpotifyVolumeRequest | None = None


class SpotifyPlaybackTokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    expires_at: float


class SpotifyPlaybackTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force_refresh: bool = False


def execute_spotify_session(payload: dict) -> dict:
    args = SpotifyPlaybackSessionRequest.model_validate(payload.get("arguments") or {})
    try:
        service = spotify_client()
        result = (service.claim_web_player(str(args.owner_id)) if args.operation == "enable"
                  else service.release_web_player(str(args.owner_id)))
        return {"changed": True, **result, "_message": "Vellum Spotify playback " + args.operation + "d."}
    except Exception as exc:
        if getattr(exc, "code", "") == "no_active_device":
            raise PluginContributionActionError("SPOTIFY_PLAYER_BUSY", str(exc)) from exc
        raise


def _spotify_playback_actions() -> tuple[PluginActionContribution, ...]:
    control = PluginActionContribution(
        definition=AppActionDefinition(
            id="spotify.playback.control", version="1", owner="spotify", plugin_id="spotify",
            title="Control Spotify playback", description="Play a song by title or control the selected Spotify device.",
            # Transient playback has the same write permission as existing portable
            # playback tools; explicit click/chat intent authorizes this control.
            scope="user", access_class="write", executor_location="server",
            supports_undo=False, idempotent=False, confirmation_rule="current_user_intent",
            argument_schema=SpotifyPlaybackControlRequest.model_json_schema(),
            result_schema={"type": "object", "required": ["changed"]},
            ui_reference="spotify.player", audit_label="spotify.playback.control",
            required_permissions=["spotify.playback", "spotify.search"],
        ), adapter=execute_spotify_control,
    )
    return (control, PluginActionContribution(
        definition=AppActionDefinition(
            id="spotify.playback.session", version="1", owner="spotify", plugin_id="spotify",
            title="Play Spotify inside Vellum", description="Enable or disable this window's Spotify Connect player.",
            scope="session", access_class="write", executor_location="server",
            supports_undo=False, idempotent=False, confirmation_rule="none",
            argument_schema=SpotifyPlaybackSessionRequest.model_json_schema(),
            result_schema={"type": "object", "required": ["changed", "status"]},
            ui_reference="spotify.player", audit_label="spotify.playback.session",
            required_permissions=["spotify.playback"],
        ), adapter=execute_spotify_session, allowed_agents=frozenset({"VellumUI"}),
    ),)


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
            if not client_id and arguments.get("reuse_existing_client") is True:
                try:
                    client_id = str(self._store_provider().load_tokens().get("client_id") or "").strip()
                except SpotifyAuthError:
                    pass
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
                    "properties": {
                        "client_id": {"type": "string", "writeOnly": True},
                        "reuse_existing_client": {"type": "boolean"},
                    },
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
        PluginActionContribution(
            definition=AppActionDefinition(
                id=SPOTIFY_PLAYLIST_EDIT_ACTION_ID, title='Edit a Spotify playlist',
                description='Rename, edit description, add/remove songs, or remove an exact playlist from your library after review.',
                access_class=CapabilityAccess.EXTERNAL_WRITE.value, confirmation_rule='operation_bound',
                argument_schema=SpotifyPlaylistEditRequest.model_json_schema(),
                ui_reference='music.playlist', audit_label=SPOTIFY_PLAYLIST_EDIT_ACTION_ID,
                required_permissions=['spotify.playlists', 'spotify.library'], **common,
            ), adapter=execute_spotify_playlist_edit, availability=connected,
        ),
        *_spotify_playback_actions(),
    ))
