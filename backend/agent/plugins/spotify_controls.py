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
    action: Literal["play", "pause", "next", "previous", "seek", "set_volume", "set_shuffle", "set_repeat", "transfer",
                    "seek_by", "volume_by", "mute", "unmute", "save_current", "remove_current"]
    # Relative change: milliseconds for seek_by, percentage points for volume_by.
    delta: int | None = Field(default=None, ge=-86400000, le=86400000)
    # Display name of context_uri, used only in the reply.
    context_name: str | None = Field(default=None, min_length=1, max_length=200)
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


class SpotifyPlaylistLinksRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    uris: list[str] = Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def validate_links(self):
        if any(not re.fullmatch(r'spotify:playlist:[A-Za-z0-9]{22}',uri) for uri in self.uris):
            raise ValueError('Use exact Spotify playlist links.')
        return self


def execute_spotify_playlist_links(payload):
    request=SpotifyPlaylistLinksRequest.model_validate(payload.get('arguments') or {})
    try:
        result=spotify_client().remember_playlist_links(request.uris)
    except SpotifyError as exc:
        raise PluginContributionActionError('SPOTIFY_PLAYLIST_LINK_FAILED',str(exc)) from exc
    return {'changed':True,'count':result.get('total',0),
        '_message':f'Added {result.get("total",0)} linked playlists to this Spotify connection.'}


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
    """Read syntax tokens once; preserve original spelling and spacing of values."""
    tokens = list(re.finditer(r'\S+', command))
    words = [token.group().casefold() for token in tokens]
    if not words:
        return None

    def fragment(start, stop):
        return command[tokens[start].start():tokens[stop - 1].end()]

    def target(value):
        value = value.strip().strip('\"\'')
        if tuple(value.casefold().split()) in {('this', 'playlist'), ('that', 'playlist'), ('the', 'playlist'), ('my', 'playlist')}:
            return ''
        parts = value.split(maxsplit=1)
        if len(parts) == 2 and parts[0].casefold() in {'my', 'the'}:
            value = parts[1]
        parts = value.split(maxsplit=1)
        if len(parts) == 2 and parts[0].casefold() == 'playlist':
            value = parts[1]
        parts = value.rsplit(maxsplit=1)
        if len(parts) == 2 and parts[1].casefold() == 'playlist':
            value = parts[0]
        return value.strip().strip('\"\'')

    def edit(start, separator, field, possessive=False):
        if separator <= start or separator + 1 >= len(words):
            return None
        value = fragment(start, separator)
        if 'playlist' not in value.casefold():
            return None
        if possessive and value.casefold().endswith(("playlist's", 'playlist’s')):
            value = value[:-2]
        return AppActionRequest(action_id=SPOTIFY_PLAYLIST_EDIT_ACTION_ID,
            arguments={'operation':'update_details', 'playlist_name':target(value),
                       field:fragment(separator + (2 if possessive else 1), len(words)).strip('\"\'')})

    prefixes = [('rename',), ('change', 'name', 'of'), ('change', 'the', 'name', 'of')]
    for prefix in prefixes:
        if words[:len(prefix)] == list(prefix):
            try:
                separator = words.index('to', len(prefix) + 1)
            except ValueError:
                return None
            return edit(len(prefix), separator, 'name')

    if words[0] in {'change', 'set'}:
        for index in range(2, len(words) - 2):
            if words[index:index + 2] == ['name', 'to'] and words[index - 1] in {'playlist', "playlist's", 'playlist’s'}:
                # "name to" occupies two tokens, followed by the new value.
                return edit(1, index, 'name', possessive=True)

    if words[0] in {'change', 'set', 'edit'}:
        start = 2 if words[1:2] == ['the'] else 1
        if words[start:start + 2] == ['description', 'of']:
            start += 2
            try:
                separator = words.index('to', start + 1)
            except ValueError:
                return None
            return edit(start, separator, 'description')

    if words[0] in {'remove', 'delete', 'unsave', 'unfollow'} and len(words) > 1:
        stop = len(words)
        for suffix in [('from', 'my', 'spotify', 'library'), ('from', 'the', 'spotify', 'library'),
                       ('from', 'my', 'library'), ('from', 'the', 'library')]:
            if words[-len(suffix):] == list(suffix):
                stop -= len(suffix)
                break
        if stop <= 1:
            return None
        value = fragment(1, stop).strip('\"\'')
        if not value:
            return None
        if value.split(maxsplit=1)[0].casefold() != 'playlist' and value.rsplit(maxsplit=1)[-1].casefold() != 'playlist':
            return None
        return AppActionRequest(action_id=SPOTIFY_PLAYLIST_EDIT_ACTION_ID,
            arguments={'operation':'remove', 'playlist_name':target(value)})
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


_SPOTIFY_UNMUTED: dict[str, int] = {}


def _spotify_title(state: dict) -> str:
    track = state.get("track") or {}
    if not track.get("name"):
        return ""
    artists = ", ".join(a for a in state.get("artists") or [] if a)
    return "“" + track["name"] + "”" + (" by " + artists if artists else "")


def _spotify_live(service) -> dict:
    """Vellum's own player answers without a network call; others use the Web API."""
    state = _result(_spotify_module.tools._result(service.get_player))
    return state if isinstance(state, dict) else {}


def _spotify_device_args(state: dict) -> dict:
    device_id = (state.get("device") or {}).get("id")
    return {"device_id": device_id} if device_id else {}


def _relative_spotify_control(args: SpotifyPlaybackControlRequest, service) -> dict:
    state = _spotify_live(service)
    if args.action in {"seek_by", "save_current", "remove_current"} and not (state.get("track") or {}).get("uri"):
        raise PluginContributionActionError("NOTHING_PLAYING", "Nothing is playing on Spotify right now.")
    if args.action == "seek_by":
        delta = int(args.delta or 0)
        duration = int(state.get("duration_ms") or 0)
        position = max(0, int(state.get("progress_ms") or 0) + delta)
        if duration:
            position = min(position, max(0, duration - 1000))
        _result(spotify_playback({"action": "seek", "position_ms": position, **_spotify_device_args(state)}, service=service))
        seconds = abs(delta) // 1000
        span = (f"{seconds // 60} min" + (f" {seconds % 60} s" if seconds % 60 else "")) if seconds >= 60 else f"{seconds} seconds"
        return {"changed": True, "position_ms": position,
                "_message": ("Skipped ahead " if delta >= 0 else "Went back ") + span + "."}
    if args.action in {"save_current", "remove_current"}:
        uri = state["track"]["uri"]
        if not uri.startswith("spotify:track:"):
            raise PluginContributionActionError("NOT_A_SONG", "Only songs can be added to Liked Songs.")
        save = args.action == "save_current"
        _result(_spotify_module.tools.spotify_library({"action": "save" if save else "remove", "kind": "tracks", "uris": [uri]}, service=service))
        name = _spotify_title(state) or "this song"
        return {"changed": True, "liked": save, "track_uri": uri,
                "_message": (f"Added {name} to your Liked Songs." if save else f"Removed {name} from your Liked Songs.")}
    device = state.get("device") or {}
    current = device.get("volume_percent")
    key = str(device.get("id") or "")
    if args.action == "unmute":
        target = _SPOTIFY_UNMUTED.pop(key, None) or (current if current else 50)
    elif current is None:
        raise PluginContributionActionError("VOLUME_UNAVAILABLE", "Spotify did not report this device's volume, so I left it unchanged.")
    elif args.action == "mute":
        if current:
            _SPOTIFY_UNMUTED[key] = int(current)
        target = 0
    else:
        target = max(0, min(100, int(current) + int(args.delta or 0)))
    _result(spotify_playback({"action": "set_volume", "volume_percent": int(target), **_spotify_device_args(state)}, service=service))
    message = "Muted." if args.action == "mute" else ("Unmuted. " if args.action == "unmute" else "") + f"Volume is {int(target)}%."
    return {"changed": True, "volume_percent": int(target), "_message": message}


def execute_spotify_control(payload: dict) -> dict:
    args = SpotifyPlaybackControlRequest.model_validate(payload.get("arguments") or {})
    service = spotify_client()
    if args.action in {"seek_by", "volume_by", "mute", "unmute", "save_current", "remove_current"}:
        if args.action in {"seek_by", "volume_by"} and args.delta is None:
            raise PluginContributionActionError("INVALID_ARGUMENTS", "Say how far to move.")
        try:
            return _relative_spotify_control(args, service)
        except SpotifyError as exc:
            raise PluginContributionActionError(str(getattr(exc, "code", "") or "SPOTIFY_FAILED"), str(exc)) from exc
    body = args.model_dump(exclude_none=True, exclude={"query", "delta", "context_name"})
    if args.offset_position is not None:
        body.pop('offset_position')
        body['offset'] = {'position':args.offset_position}
    message = {"play": "Resumed.", "pause": "Paused.", "next": "Skipped to the next song.", "previous": "Went back to the previous song.",
               "set_shuffle": "Shuffle is " + ("on." if args.shuffle else "off."),
               "set_repeat": {"track": "Repeating this song.", "context": "Repeating this playlist.", "off": "Repeat is off."}.get(args.state or "off", "Repeat updated."),
               "set_volume": f"Volume is {args.volume_percent}%.", "transfer": "Moved playback to that device."}.get(args.action, "Done.")
    if args.action == "play" and args.context_uri:
        message = f"Playing your “{args.context_name}” playlist." if args.context_name else "Playing that playlist."
    elif args.action == "play" and args.uris:
        message = "Playing."
    if args.action == "seek" and args.position_ms is not None:
        message = "Back to the start." if args.position_ms == 0 else f"Moved to {args.position_ms // 60000}:{args.position_ms // 1000 % 60:02d}."
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


class SpotifyPlaybackStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: Literal["song", "artist", "album", "next", "queue", "playlist", "liked"] = "song"


def _queue_title(item: dict) -> str:
    artists = [a.get("name", "") for a in item.get("artists") or [] if isinstance(a, dict)]
    show = item.get("show") if isinstance(item.get("show"), dict) else {}
    by = ", ".join(a for a in artists if a) or show.get("name", "")
    return "“" + str(item.get("name") or "Untitled") + "”" + (" by " + by if by else "")


def _spotify_context_name(service, context: dict) -> str:
    kind, uri = str(context.get("type") or ""), str(context.get("uri") or "")
    identifier = uri.rsplit(":", 1)[-1]
    if kind == "collection" or uri.endswith(":collection"):
        return "your Liked Songs"
    if kind == "playlist" and identifier:
        for link in service.get_linked_playlists() if hasattr(service, "get_linked_playlists") else []:
            if (link.get("id") == identifier or str(link.get("uri") or "").endswith(":" + identifier)) and link.get("name"):
                return "your “" + str(link["name"]) + "” playlist"
        try:
            playlist = _result(_spotify_module.tools.spotify_playlists({"action": "get", "playlist_id": identifier}, service=service))
            if playlist.get("name"):
                return "the “" + playlist["name"] + "” playlist"
        except PluginContributionActionError:
            pass
        return "a playlist Spotify did not name for Vellum"
    if kind == "album" and identifier:
        try:
            album = _result(_spotify_module.tools.spotify_albums({"action": "get", "album_id": identifier}, service=service))
            if album.get("name"):
                return "the album “" + album["name"] + "”"
        except Exception:
            pass
        return "an album"
    if kind == "artist":
        return "an artist radio or page"
    return ""


def execute_spotify_status(payload: dict) -> dict:
    """Read live Spotify playback for a direct reply; no model sees this data."""
    args = SpotifyPlaybackStatusRequest.model_validate(payload.get("arguments") or {})
    service = spotify_client()
    try:
        if args.detail in {"next", "queue"}:
            queue = _result(_spotify_module.tools.spotify_queue({"action": "get"}, service=service))
            items = [item for item in queue.get("queue") or [] if isinstance(item, dict)][:5]
            names = [_queue_title(item) for item in items]
            if not names:
                message = "Nothing is queued on Spotify after this song."
            elif args.detail == "next":
                message = "Up next: " + names[0] + "."
            else:
                message = "Up next: " + "; ".join(f"{i}. {name}" for i, name in enumerate(names, 1)) + "."
            return {"changed": False, "next": names, "_message": message}
        state = _spotify_live(service)
        track = state.get("track") or {}
        name = _spotify_title(state)
        result = {"changed": False, "playing": bool(state.get("is_playing")), "title": track.get("name", ""),
                  "artists": list(state.get("artists") or []), "album": str(state.get("album") or ""), "track_uri": track.get("uri", "")}
        if not name:
            return {**result, "_message": "Nothing is playing on Spotify right now."}
        if args.detail == "artist":
            artists = ", ".join(a for a in result["artists"] if a)
            message = f"“{track['name']}” is by {artists}." if artists else f"Spotify did not list an artist for “{track['name']}”."
        elif args.detail == "album":
            message = f"{name} is from {result['album']}." if result["album"] else f"Spotify did not list an album for {name}."
        elif args.detail == "liked":
            liked = False
            if str(track.get("uri", "")).startswith("spotify:track:"):
                contains = _result(_spotify_module.tools.spotify_library({"action": "contains", "kind": "tracks", "uris": [track["uri"]]}, service=service))
                liked = (contains.get("items") or [False])[0] is True if isinstance(contains, dict) else bool(contains and contains[0])
            result["liked"] = liked
            message = f"{name} is " + ("in" if liked else "not in") + " your Liked Songs."
        elif args.detail == "playlist":
            raw = service.request("GET", "/me/player")
            context = raw.get("context") if isinstance(raw, dict) and isinstance(raw.get("context"), dict) else {}
            source = _spotify_context_name(service, context) if context else ""
            result["context_uri"] = str(context.get("uri") or "")
            message = f"{name} is playing from {source}." if source else f"{name} is not playing from a playlist."
        else:
            message = ("Now playing " if result["playing"] else "Paused on ") + name + "."
        return {**result, "_message": message}
    except SpotifyError as exc:
        raise PluginContributionActionError(str(getattr(exc, "code", "") or "SPOTIFY_FAILED"), str(exc)) from exc


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
    status = PluginActionContribution(
        definition=AppActionDefinition(
            id="spotify.playback.status", version="1", owner="spotify", plugin_id="spotify",
            title="What is playing on Spotify", description="Read the current song, artist, album, playlist, like status or queue.",
            scope="user", access_class="read", executor_location="server",
            supports_undo=False, idempotent=True, confirmation_rule="current_user_intent",
            argument_schema=SpotifyPlaybackStatusRequest.model_json_schema(),
            result_schema={"type": "object", "required": ["changed"]},
            ui_reference="spotify.player", audit_label="spotify.playback.status",
            required_permissions=["spotify.playback"],
        ), adapter=execute_spotify_status, allowed_agents=frozenset({"VellumAgent", "VellumUI", "MusicAgent"}),
    )
    return (control, status, PluginActionContribution(
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
        PluginActionContribution(definition=AppActionDefinition(
            id='spotify.playlists.link',title='Add Spotify playlist links',
            description='Remember exact playlist references in this Spotify connection; does not change Spotify playlists.',
            access_class='write',confirmation_rule='current_user_intent',
            argument_schema=SpotifyPlaylistLinksRequest.model_json_schema(),
            ui_reference='music.playlist',audit_label='spotify.playlists.link',
            required_permissions=['spotify.playlists'],**common),adapter=execute_spotify_playlist_links,availability=connected),
        *_spotify_playback_actions(),
    ))
