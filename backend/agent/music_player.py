"""Route a short player instruction to whichever player is actually live.

The words are the same for Local Music and Spotify ("what song is this",
"skip 30 secs", "like this song"); this module reads each player's live
state (no network for Local Music or Vellum's own Spotify player) and builds
the plugin App Action for the one that is playing. Requests that are not a
complete player instruction return None and go to the model as usual.
"""
from __future__ import annotations

import json
import re
import time

from agent.app_actions.models import AppActionRequest
from agent.contracts.music import _PLAYER_POLITE, _PLAYER_PROVIDER, PlayerCommand, fix_music_spelling, match_player_request

# Without one of these words a phrase such as "like it" or "louder" is only a
# player instruction while one of Vellum's players has something loaded.
_MUSIC_WORDS = re.compile(
    r"\b(?:songs?|tracks?|tunes?|music|spotify|local|playlists?|album|volume|sound|queue|artist|singer|"
    r"playing|listening|shuffle|repeat|loop|mute|unmute|secs?|seconds?|mins?|minutes?|liked|next)\b", re.I)

SPOTIFY_REPEAT = {'one': 'track', 'all': 'context', 'off': 'off'}


def _local_state(available: bool):
    if not available:
        return None
    try:
        from agent.music_library import get_music_library
        return get_music_library().player_state()
    except Exception:
        return None


def _spotify_state(available: bool) -> tuple[bool, str, bool, float, float]:
    """(authenticated, web-player status, playing, playing since, last playing at)."""
    if not available:
        return False, 'disabled', False, 0.0, 0.0
    try:
        from agent.plugins.spotify_runtime import spotify_client, spotify_is_authenticated
        if not spotify_is_authenticated():
            return False, 'disabled', False, 0.0, 0.0
        service = spotify_client()
        web = service.web_playback_status()
        observed = service.local_player_state() if hasattr(service, 'local_player_state') else None
        return (True, str(web.get('status') or 'disabled'), bool(observed and observed.get('is_playing')),
                float(web.get('playing_since') or 0), float(web.get('last_playing_at') or 0))
    except Exception:
        return False, 'disabled', False, 0.0, 0.0


def choose_player(command: PlayerCommand, *, local_available: bool, spotify_available: bool,
                  require_present: bool) -> str | None:
    local = _local_state(local_available)
    spotify_auth, spotify_status, spotify_live, spotify_since, spotify_last = _spotify_state(spotify_available)
    if command.provider == 'local':
        return 'local' if local is not None else None
    if command.provider == 'spotify':
        return 'spotify' if spotify_auth else None
    observed = (local.observed or {}) if local is not None else {}
    local_live = bool(local and local.owner_available and observed.get('playing'))
    local_present = bool(local and local.owner_available and local.queue)
    spotify_present = spotify_auth and spotify_status == 'ready'
    if local_live and spotify_live:
        # Both playing: the one started last is the one being listened to.
        return 'local' if float(observed.get('playing_since') or 0) >= spotify_since else 'spotify'
    if local_live:
        return 'local'
    if spotify_live:
        return 'spotify'
    if local_present and spotify_present:
        # Both paused: the one that played most recently.
        return 'local' if float(observed.get('last_playing_at') or 0) >= spotify_last else 'spotify'
    if local_present:
        return 'local'
    if spotify_present:
        return 'spotify'
    if require_present:
        return None
    if spotify_auth:
        return 'spotify'
    if local is not None and local.queue:
        return 'local'
    return None


def player_action(command: PlayerCommand, provider: str) -> AppActionRequest:
    op = command.op
    if provider == 'local':
        if op == 'info':
            return AppActionRequest(action_id='local_music.now_playing', arguments={'detail': command.detail})
        arguments = {
            'pause': {'action': 'pause'}, 'resume': {'action': 'resume'},
            'next': {'action': 'next'}, 'previous': {'action': 'previous'},
            'seek_by': {'action': 'seek_by', 'delta': command.seconds},
            'restart': {'action': 'seek', 'seconds': 0},
            'volume_set': {'action': 'volume', 'volume': command.volume / 100},
            'volume_by': {'action': 'volume_by', 'delta': command.volume / 100},
            'mute': {'action': 'mute'}, 'unmute': {'action': 'unmute'},
            'like': {'action': 'like'}, 'unlike': {'action': 'unlike'},
            'shuffle': {'action': 'shuffle', 'enabled': command.enabled},
            'repeat': {'action': 'repeat', 'repeat': command.repeat},
        }[op]
        return AppActionRequest(action_id='local_music.playback', arguments=arguments)
    if op == 'info':
        return AppActionRequest(action_id='spotify.playback.status', arguments={'detail': command.detail})
    arguments = {
        'pause': {'action': 'pause'}, 'resume': {'action': 'play'},
        'next': {'action': 'next'}, 'previous': {'action': 'previous'},
        'seek_by': {'action': 'seek_by', 'delta': command.seconds * 1000},
        'restart': {'action': 'seek', 'position_ms': 0},
        'volume_set': {'action': 'set_volume', 'volume_percent': command.volume},
        'volume_by': {'action': 'volume_by', 'delta': command.volume},
        'mute': {'action': 'mute'}, 'unmute': {'action': 'unmute'},
        'like': {'action': 'save_current'}, 'unlike': {'action': 'remove_current'},
        'shuffle': {'action': 'set_shuffle', 'shuffle': command.enabled},
        'repeat': {'action': 'set_repeat', 'state': SPOTIFY_REPEAT[command.repeat]},
    }[op]
    return AppActionRequest(action_id='spotify.playback.control', arguments=arguments)


_PLAY_PLAYLIST = re.compile(r"(?:play|put\s+on|start|shuffle)\s+(?:my\s+|the\s+)?(?:playlists?\s+(?:called\s+|named\s+)?(?P<a>.+)|(?P<b>.+?)\s+playlists?)")
_NOT_A_NAME = {'local', 'my local', 'a', 'any', 'some', 'random', 'a random', 'one of my', 'liked', 'my liked', 'the liked'}
_SPOTIFY_PLAYLISTS: dict = {'at': 0.0, 'rows': []}


def _singular_key(value: str) -> str:
    from agent.tools.capabilities.spotify_service import playlist_key
    return ' '.join(w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w
                    for w in playlist_key(value).split())


def _spotify_saved_playlists() -> list[dict]:
    # Saved playlists change rarely; a short cache keeps "play my X playlist" instant.
    if time.monotonic() - _SPOTIFY_PLAYLISTS['at'] < 300:
        return _SPOTIFY_PLAYLISTS['rows']
    from agent.plugins.spotify_runtime import _spotify_module, spotify_client
    from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
    service = spotify_client()

    def invoke(name, body):
        result = json.loads(_spotify_module.tools.HANDLERS[name](body, service=service))
        if not result.get('ok'):
            raise ValueError('Spotify playlists unavailable')
        return result.get('data') or {}
    rows = [{'name': str(row.get('name') or ''), 'uri': row.get('uri') or 'spotify:playlist:' + row['id']}
            for row in SpotifyCapabilityService.saved_playlists(invoke) if row.get('id')]
    _SPOTIFY_PLAYLISTS.update(at=time.monotonic(), rows=rows)
    return rows


def match_playlist_action(text: str, *, spotify_available: bool) -> AppActionRequest | None:
    """'play my classics playlist' on Spotify, when exactly one saved playlist matches.

    Local playlists are matched earlier by the Local Music matcher.
    """
    if not spotify_available:
        return None
    raw = ' '.join(str(text or '').split()).casefold().replace('’', "'").rstrip(' .!?')
    for candidate in dict.fromkeys((raw, fix_music_spelling(raw))):
        t = _PLAYER_POLITE.sub('', candidate).strip()
        suffix = _PLAYER_PROVIDER.search(t)
        if suffix:
            if 'spotify' not in (suffix[1] or suffix[2] or ''):
                return None
            t = t[:suffix.start()].strip()
        found = _PLAY_PLAYLIST.fullmatch(t)
        if not found:
            continue
        name = (found['a'] or found['b'] or '').strip(' "\'“”')
        if not name or name in _NOT_A_NAME:
            return None
        try:
            from agent.plugins.spotify_runtime import spotify_is_authenticated
            if not spotify_is_authenticated():
                return None
            rows = _spotify_saved_playlists()
        except Exception:
            return None
        wanted = _singular_key(name)
        matches = [row for row in rows if _singular_key(row['name']) == wanted]
        if len(matches) == 1:
            return AppActionRequest(action_id='spotify.playback.control', arguments={
                'action': 'play', 'context_uri': matches[0]['uri'], 'context_name': matches[0]['name'][:200]})
    return None


def match_player_action(text: str, *, local_available: bool, spotify_available: bool) -> AppActionRequest | None:
    command = match_player_request(text)
    if command is None:
        return match_playlist_action(text, spotify_available=spotify_available)
    require_present = not command.provider and not _MUSIC_WORDS.search(text)
    provider = choose_player(command, local_available=local_available, spotify_available=spotify_available,
                             require_present=require_present)
    return player_action(command, provider) if provider else None
