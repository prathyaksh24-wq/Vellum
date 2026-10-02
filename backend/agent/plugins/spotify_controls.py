"""Spotify browser-player contracts and contribution to the existing App Actions."""

import json
import re
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent.app_actions.models import AppActionDefinition, AppActionRequest
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
    control = match_music_control(command)
    if control:
        # A bare 'pause' has a music meaning only while this Vellum device is selected.
        if "spotify" not in text.casefold() and spotify_client().web_playback_status()["status"] == "disabled":
            return None
        action = "play" if control == "resume" else control
        return AppActionRequest(action_id="spotify.playback.control", arguments={"action": action})
    # Song and playlist interpretation belongs to MusicAgent, not a UI matcher.
    return None


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


class SpotifyPlaybackDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["connecting", "ready", "not_ready", "authentication_error", "autoplay_failed", "initialization_error", "account_error", "playback_error", "state", "connect_timeout"]
    at_ms: int = Field(ge=0)
    paused: bool | None = None
    position_ms: int | None = Field(default=None, ge=0)
    volume_percent: int | None = Field(default=None, ge=0, le=100)


class SpotifyPlaybackSessionResponse(BaseModel):
    status: Literal["connecting", "ready", "reconnecting", "disabled"]


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


def spotify_plugin_contribution() -> PluginContribution:
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
    return PluginContribution(owner="spotify", actions=(control, PluginActionContribution(
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
    ),))
