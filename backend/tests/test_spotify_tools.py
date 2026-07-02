import json
from pathlib import Path

import pytest

from agent.plugins.portable import PortablePluginContext, load_portable_plugin
from agent.plugins.spotify_runtime import spotify_catalog_query_gate
from plugins.connectors.spotify.errors import SpotifyNoActiveDevice
from plugins.connectors.spotify.tools import (
    spotify_albums,
    spotify_devices,
    spotify_library,
    spotify_playback,
    spotify_playlists,
    spotify_queue,
    spotify_search,
)


class FakeService:
    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"method": method, "path": path}

    def get_player(self):
        self.calls.append(("GET", "/me/player", {}))
        return {"is_playing": True}

    def get_devices(self):
        self.calls.append(("GET", "/me/player/devices", {}))
        return {"devices": []}

    def get_queue(self):
        self.calls.append(("GET", "/me/player/queue", {}))
        return {"queue": []}

    def get_profile(self):
        self.calls.append(("GET", "/me", {}))
        return {"id": "user-1"}


@pytest.mark.parametrize(
    ("handler", "args", "method", "path"),
    [
        (spotify_playback, {"action": "pause"}, "PUT", "/me/player/pause"),
        (spotify_playback, {"action": "next"}, "POST", "/me/player/next"),
        (spotify_devices, {"action": "list"}, "GET", "/me/player/devices"),
        (spotify_queue, {"action": "get"}, "GET", "/me/player/queue"),
        (spotify_search, {"query": "Kind of Blue"}, "GET", "/search"),
        (spotify_playlists, {"action": "list"}, "GET", "/me/playlists"),
        (spotify_albums, {"action": "get", "album_id": "a1"}, "GET", "/albums/a1"),
        (spotify_library, {"kind": "tracks", "action": "list"}, "GET", "/me/tracks"),
    ],
)
def test_handler_routes(handler, args, method, path):
    service = FakeService()

    result = json.loads(handler(args, service=service))

    assert result["ok"] is True
    assert service.calls[-1][:2] == (method, path)


@pytest.mark.parametrize(
    ("args", "method", "path", "expected"),
    [
        ({"action": "play", "uris": ["spotify:track:1"]}, "PUT", "/me/player/play", {"json_body": {"uris": ["spotify:track:1"]}}),
        ({"action": "seek", "position_ms": 9000}, "PUT", "/me/player/seek", {"params": {"position_ms": 9000}}),
        ({"action": "set_repeat", "state": "track"}, "PUT", "/me/player/repeat", {"params": {"state": "track"}}),
        ({"action": "set_shuffle", "shuffle": True}, "PUT", "/me/player/shuffle", {"params": {"state": True}}),
        ({"action": "set_volume", "volume_percent": 40}, "PUT", "/me/player/volume", {"params": {"volume_percent": 40}}),
    ],
)
def test_playback_mutations_map_arguments(args, method, path, expected):
    service = FakeService()

    result = json.loads(spotify_playback(args, service=service))

    assert result["ok"] is True
    call_method, call_path, kwargs = service.calls[-1]
    assert (call_method, call_path) == (method, path)
    for key, value in expected.items():
        assert kwargs[key] == value


def test_playlist_create_uses_current_user():
    service = FakeService()

    result = json.loads(
        spotify_playlists(
            {"action": "create", "name": "Focus", "public": False},
            service=service,
        )
    )

    assert result["ok"] is True
    assert service.calls == [
        ("GET", "/me", {}),
        ("POST", "/users/user-1/playlists", {"json_body": {"name": "Focus", "public": False}}),
    ]


@pytest.mark.parametrize(
    ("action", "method"),
    [("add_items", "POST"), ("remove_items", "DELETE")],
)
def test_playlist_mutations_use_current_items_endpoint(action, method):
    service = FakeService()

    result = json.loads(
        spotify_playlists(
            {"action": action, "playlist_id": "playlist-1", "uris": ["spotify:track:1"]},
            service=service,
        )
    )

    assert result["ok"] is True
    assert service.calls[-1][0:2] == (method, "/playlists/playlist-1/items")


@pytest.mark.parametrize(
    ("kind", "action", "values", "method", "expected_uris"),
    [
        ("tracks", "save", {"ids": ["track-1"]}, "PUT", "spotify:track:track-1"),
        ("albums", "remove", {"uris": ["spotify:album:album-1"]}, "DELETE", "spotify:album:album-1"),
    ],
)
def test_library_mutations_use_unified_library_endpoint(kind, action, values, method, expected_uris):
    service = FakeService()

    result = json.loads(spotify_library({"kind": kind, "action": action, **values}, service=service))

    assert result["ok"] is True
    assert service.calls == [
        (method, "/me/library", {"params": {"uris": expected_uris}}),
    ]


def test_library_can_save_the_currently_playing_track_in_one_action():
    class CurrentlyPlayingService(FakeService):
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if (method, path) == ("GET", "/me/player/currently-playing"):
                return {"item": {"type": "track", "uri": "spotify:track:current-1"}}
            return {"method": method, "path": path}

    service = CurrentlyPlayingService()

    result = json.loads(spotify_library({"kind": "tracks", "action": "save_current"}, service=service))

    assert result["ok"] is True
    assert service.calls == [
        ("GET", "/me/player/currently-playing", {}),
        ("PUT", "/me/library", {"params": {"uris": "spotify:track:current-1"}}),
    ]


@pytest.mark.parametrize(
    ("handler", "args"),
    [
        (spotify_playback, {"action": "seek"}),
        (spotify_devices, {"action": "transfer"}),
        (spotify_queue, {"action": "add"}),
        (spotify_search, {"query": ""}),
        (spotify_playlists, {"action": "get"}),
        (spotify_albums, {"action": "get"}),
        (spotify_library, {"kind": "tracks", "action": "save"}),
    ],
)
def test_missing_action_arguments_return_json_error(handler, args):
    result = json.loads(handler(args, service=FakeService()))

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


def test_domain_errors_do_not_escape_or_leak_details():
    class FailingService(FakeService):
        def request(self, method, path, **kwargs):
            raise SpotifyNoActiveDevice("No active Spotify device found")

    result = json.loads(
        spotify_playback(
            {"action": "set_volume", "volume_percent": 50},
            service=FailingService(),
        )
    )

    assert result == {
        "ok": False,
        "error": {"code": "no_active_device", "message": "No active Spotify device found"},
    }


def test_next_activates_available_device_and_retries():
    class InactiveDeviceService(FakeService):
        def __init__(self):
            super().__init__()
            self.next_attempts = 0

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if (method, path) == ("POST", "/me/player/next"):
                self.next_attempts += 1
                if self.next_attempts == 1:
                    raise SpotifyNoActiveDevice("No active Spotify device found")
            return {"method": method, "path": path}

        def get_devices(self):
            self.calls.append(("GET", "/me/player/devices", {}))
            return {
                "devices": [
                    {"id": "desktop-1", "name": "Desktop", "is_active": False, "is_restricted": False}
                ]
            }

    service = InactiveDeviceService()

    result = json.loads(spotify_playback({"action": "next"}, service=service))

    assert result["ok"] is True
    assert service.calls == [
        ("POST", "/me/player/next", {"params": None}),
        ("GET", "/me/player/devices", {}),
        ("PUT", "/me/player", {"json_body": {"device_ids": ["desktop-1"], "play": True}}),
        ("POST", "/me/player/next", {"params": {"device_id": "desktop-1"}}),
    ]


def test_pause_without_active_device_is_idempotent():
    class InactiveDeviceService(FakeService):
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            raise SpotifyNoActiveDevice("No active Spotify device found")

    service = InactiveDeviceService()

    result = json.loads(spotify_playback({"action": "pause"}, service=service))

    assert result == {"ok": True, "data": {"status": "already_paused"}}


def test_spotify_search_allows_public_artist_names():
    service = FakeService()

    result = json.loads(spotify_search({"query": "Miles Davis Kind of Blue"}, service=service, privacy_gate=spotify_catalog_query_gate))

    assert result["ok"] is True
    assert service.calls[-1][2]["params"]["q"] == "Miles Davis Kind of Blue"


def test_spotify_search_blocks_secret_material_before_network_call():
    service = FakeService()

    result = json.loads(spotify_search({"query": "password=secret-value"}, service=service, privacy_gate=spotify_catalog_query_gate))

    assert result["ok"] is False
    assert result["error"]["code"] == "privacy_blocked"
    assert service.calls == []


def test_plugin_registers_all_seven_tools():
    ctx = PortablePluginContext()

    load_portable_plugin(Path("plugins/connectors/spotify")).register(ctx)

    assert set(ctx.tools) == {
        "spotify_playback",
        "spotify_devices",
        "spotify_queue",
        "spotify_search",
        "spotify_playlists",
        "spotify_albums",
        "spotify_library",
    }
    assert "spotify" in ctx.connectors
