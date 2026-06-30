"""Hermes-compatible Spotify tool schemas exposed to the model."""

from __future__ import annotations


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


SPOTIFY_PLAYBACK = _tool(
    "spotify_playback",
    "Inspect or control Spotify playback. Use direct actions without a state preflight when the user clearly asks to play, pause, skip, seek, change repeat/shuffle, or set volume.",
    {
        "action": {
            "type": "string",
            "enum": [
                "get_state",
                "get_currently_playing",
                "play",
                "pause",
                "next",
                "previous",
                "seek",
                "set_repeat",
                "set_shuffle",
                "set_volume",
                "recently_played",
            ],
        },
        "device_id": {"type": "string", "description": "Optional Spotify Connect device ID."},
        "context_uri": {"type": "string", "description": "Album, artist, or playlist Spotify URI."},
        "uris": {"type": "array", "items": {"type": "string"}, "description": "Track or episode Spotify URIs."},
        "offset": {"description": "Playback offset object accepted by Spotify."},
        "position_ms": {"type": "integer", "minimum": 0},
        "state": {"type": "string", "enum": ["track", "context", "off"]},
        "shuffle": {"type": "boolean"},
        "volume_percent": {"type": "integer", "minimum": 0, "maximum": 100},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "before": {"type": "integer", "minimum": 0},
        "after": {"type": "integer", "minimum": 0},
    },
    ["action"],
)

SPOTIFY_DEVICES = _tool(
    "spotify_devices",
    "List Spotify Connect devices or transfer playback to one device.",
    {
        "action": {"type": "string", "enum": ["list", "transfer"]},
        "device_id": {"type": "string"},
        "play": {"type": "boolean", "default": False},
    },
    ["action"],
)

SPOTIFY_QUEUE = _tool(
    "spotify_queue",
    "Inspect the Spotify queue or append one track or episode URI.",
    {
        "action": {"type": "string", "enum": ["get", "add"]},
        "uri": {"type": "string"},
        "device_id": {"type": "string"},
    },
    ["action"],
)

SPOTIFY_SEARCH = _tool(
    "spotify_search",
    "Search Spotify for tracks, albums, artists, playlists, shows, or episodes. Search once, select the strongest exact match, then pass its URI to playback.",
    {
        "query": {"type": "string", "minLength": 1},
        "types": {
            "type": "array",
            "items": {"type": "string", "enum": ["track", "album", "artist", "playlist", "show", "episode"]},
            "default": ["track"],
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "market": {"type": "string", "description": "Optional ISO 3166-1 alpha-2 market."},
    },
    ["query"],
)

SPOTIFY_PLAYLISTS = _tool(
    "spotify_playlists",
    "List, read, create, or update the user's Spotify playlists and their items.",
    {
        "action": {"type": "string", "enum": ["list", "get", "create", "add_items", "remove_items", "update_details"]},
        "playlist_id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "public": {"type": "boolean"},
        "collaborative": {"type": "boolean"},
        "uris": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
        "position": {"type": "integer", "minimum": 0},
        "snapshot_id": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "offset": {"type": "integer", "minimum": 0},
    },
    ["action"],
)

SPOTIFY_ALBUMS = _tool(
    "spotify_albums",
    "Get Spotify album metadata or list an album's tracks.",
    {
        "action": {"type": "string", "enum": ["get", "tracks"]},
        "album_id": {"type": "string"},
        "market": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "offset": {"type": "integer", "minimum": 0},
    },
    ["action", "album_id"],
)

SPOTIFY_LIBRARY = _tool(
    "spotify_library",
    "List, save, or remove tracks or albums in the user's Spotify library.",
    {
        "kind": {"type": "string", "enum": ["tracks", "albums"]},
        "action": {"type": "string", "enum": ["list", "save", "remove"]},
        "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
        "uris": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
        "market": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "offset": {"type": "integer", "minimum": 0},
    },
    ["kind", "action"],
)

ALL_SCHEMAS = [
    SPOTIFY_PLAYBACK,
    SPOTIFY_DEVICES,
    SPOTIFY_QUEUE,
    SPOTIFY_SEARCH,
    SPOTIFY_PLAYLISTS,
    SPOTIFY_ALBUMS,
    SPOTIFY_LIBRARY,
]
