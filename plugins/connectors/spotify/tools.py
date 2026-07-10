"""Hermes-compatible Spotify tool handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .auth import SpotifyAuthStore
from .client import SpotifyClient
from .errors import SpotifyError, SpotifyNoActiveDevice, SpotifyRateLimited


REPO_ROOT = Path(__file__).resolve().parents[3]


def get_spotify_service() -> SpotifyClient:
    return SpotifyClient(SpotifyAuthStore(REPO_ROOT / "data" / "plugins" / "spotify"))


def _service(kwargs: dict[str, Any]) -> SpotifyClient:
    return kwargs.get("service") or get_spotify_service()


def _result(call: Callable[[], dict]) -> str:
    try:
        return json.dumps({"ok": True, "data": call()}, ensure_ascii=False)
    except SpotifyRateLimited as exc:
        return json.dumps(
            {"ok": False, "error": {"code": exc.code, "message": str(exc), "retry_after": exc.retry_after}}
        )
    except SpotifyError as exc:
        return json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
    except Exception:
        return json.dumps({"ok": False, "error": {"code": "unreachable", "message": "Unreachable."}})


def _invalid(*names: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "error": {
                "code": "invalid_arguments",
                "message": "Missing or invalid: " + ", ".join(names),
            },
        }
    )


def _missing(args: dict, *names: str) -> list[str]:
    return [name for name in names if args.get(name) in (None, "", [])]


def _params(args: dict, *names: str) -> dict:
    return {name: args[name] for name in names if args.get(name) is not None}


def _available_device_id(service: SpotifyClient) -> str:
    payload = service.get_devices()
    devices = payload.get("devices") if isinstance(payload, dict) else []
    candidates = [
        device
        for device in (devices or [])
        if isinstance(device, dict) and device.get("id") and not device.get("is_restricted")
    ]
    active = next((device for device in candidates if device.get("is_active")), None)
    selected = active or (candidates[0] if candidates else None)
    if not selected:
        raise SpotifyNoActiveDevice("No available Spotify device found")
    return str(selected["id"])


def _player_request(
    service: SpotifyClient,
    *,
    action: str,
    method: str,
    path: str,
    device_id: str = "",
    json_body: dict | None = None,
) -> dict:
    params = {"device_id": device_id} if device_id else None
    request_kwargs: dict[str, Any] = {"params": params}
    if json_body is not None:
        request_kwargs["json_body"] = json_body
    try:
        return service.request(method, path, **request_kwargs)
    except SpotifyNoActiveDevice:
        if action == "pause":
            return {"status": "already_paused"}
        if device_id:
            raise
        selected_device = _available_device_id(service)
        if action in {"next", "previous"}:
            service.request(
                "PUT",
                "/me/player",
                json_body={"device_ids": [selected_device], "play": True},
            )
        retry_kwargs: dict[str, Any] = {"params": {"device_id": selected_device}}
        if json_body is not None:
            retry_kwargs["json_body"] = json_body
        return service.request(method, path, **retry_kwargs)


def spotify_playback(args: dict, **kwargs) -> str:
    service = _service(kwargs)
    action = args.get("action")
    device = _params(args, "device_id")
    if action == "get_state":
        return _result(service.get_player)
    if action == "get_currently_playing":
        return _result(lambda: service.request("GET", "/me/player/currently-playing"))
    if action == "play":
        body = _params(args, "context_uri", "uris", "offset", "position_ms")
        return _result(
            lambda: _player_request(
                service,
                action="play",
                method="PUT",
                path="/me/player/play",
                device_id=str(args.get("device_id") or ""),
                json_body=body or None,
            )
        )
    if action == "pause":
        return _result(
            lambda: _player_request(
                service,
                action="pause",
                method="PUT",
                path="/me/player/pause",
                device_id=str(args.get("device_id") or ""),
            )
        )
    if action == "next":
        return _result(
            lambda: _player_request(
                service,
                action="next",
                method="POST",
                path="/me/player/next",
                device_id=str(args.get("device_id") or ""),
            )
        )
    if action == "previous":
        return _result(
            lambda: _player_request(
                service,
                action="previous",
                method="POST",
                path="/me/player/previous",
                device_id=str(args.get("device_id") or ""),
            )
        )
    if action == "seek":
        missing = _missing(args, "position_ms")
        if missing:
            return _invalid(*missing)
        return _result(
            lambda: service.request(
                "PUT", "/me/player/seek", params={**_params(args, "position_ms"), **device}
            )
        )
    if action == "set_repeat":
        missing = _missing(args, "state")
        if missing:
            return _invalid(*missing)
        return _result(
            lambda: service.request("PUT", "/me/player/repeat", params={"state": args["state"], **device})
        )
    if action == "set_shuffle":
        missing = _missing(args, "shuffle")
        if missing:
            return _invalid(*missing)
        return _result(
            lambda: service.request("PUT", "/me/player/shuffle", params={"state": args["shuffle"], **device})
        )
    if action == "set_volume":
        missing = _missing(args, "volume_percent")
        if missing:
            return _invalid(*missing)
        return _result(
            lambda: service.request(
                "PUT", "/me/player/volume", params={"volume_percent": args["volume_percent"], **device}
            )
        )
    if action == "recently_played":
        return _result(
            lambda: service.request(
                "GET", "/me/player/recently-played", params=_params(args, "limit", "before", "after") or None
            )
        )
    return _invalid("action")


def spotify_devices(args: dict, **kwargs) -> str:
    service = _service(kwargs)
    action = args.get("action")
    if action == "list":
        return _result(service.get_devices)
    if action == "transfer":
        missing = _missing(args, "device_id")
        if missing:
            return _invalid(*missing)
        body = {"device_ids": [args["device_id"]], "play": bool(args.get("play", False))}
        return _result(lambda: service.request("PUT", "/me/player", json_body=body))
    return _invalid("action")


def spotify_queue(args: dict, **kwargs) -> str:
    service = _service(kwargs)
    action = args.get("action")
    if action == "get":
        return _result(service.get_queue)
    if action == "add":
        missing = _missing(args, "uri")
        if missing:
            return _invalid(*missing)
        params = {"uri": args["uri"], **_params(args, "device_id")}
        return _result(lambda: service.request("POST", "/me/player/queue", params=params))
    return _invalid("action")


def spotify_search(args: dict, **kwargs) -> str:
    missing = _missing(args, "query")
    if missing:
        return _invalid(*missing)
    service = _service(kwargs)
    query = str(args["query"])
    privacy_gate = kwargs.get("privacy_gate")
    privacy_error = None
    if callable(privacy_gate):
        query, privacy_error = privacy_gate(query)
    if privacy_error:
        return json.dumps(
            {"ok": False, "error": {"code": "privacy_blocked", "message": privacy_error}}
        )
    types = args.get("types") or ["track"]
    params = {
        "q": query,
        "type": ",".join(types),
        "limit": int(args.get("limit") or 10),
        "offset": int(args.get("offset") or 0),
        **_params(args, "market"),
    }
    return _result(lambda: service.request("GET", "/search", params=params))


def spotify_playlists(args: dict, **kwargs) -> str:
    service = _service(kwargs)
    action = args.get("action")
    if action == "list":
        return _result(
            lambda: service.request("GET", "/me/playlists", params=_params(args, "limit", "offset") or None)
        )
    if action == "get":
        missing = _missing(args, "playlist_id")
        if missing:
            return _invalid(*missing)
        return _result(lambda: service.request("GET", f"/playlists/{args['playlist_id']}"))
    if action == "create":
        missing = _missing(args, "name")
        if missing:
            return _invalid(*missing)

        def create() -> dict:
            profile = service.get_profile()
            user_id = profile.get("id")
            if not user_id:
                raise ValueError("Spotify profile has no user ID")
            body = _params(args, "name", "description", "public", "collaborative")
            return service.request("POST", f"/users/{user_id}/playlists", json_body=body)

        return _result(create)
    if action in {"add_items", "remove_items"}:
        missing = _missing(args, "playlist_id", "uris")
        if missing:
            return _invalid(*missing)
        path = f"/playlists/{args['playlist_id']}/items"
        if action == "add_items":
            body = {"uris": args["uris"], **_params(args, "position")}
            return _result(lambda: service.request("POST", path, json_body=body))
        body = {
            "items": [{"uri": uri} for uri in args["uris"]],
            **_params(args, "snapshot_id"),
        }
        return _result(lambda: service.request("DELETE", path, json_body=body))
    if action == "update_details":
        missing = _missing(args, "playlist_id")
        if missing:
            return _invalid(*missing)
        body = _params(args, "name", "description", "public", "collaborative")
        if not body:
            return _invalid("name, description, public, or collaborative")
        return _result(
            lambda: service.request("PUT", f"/playlists/{args['playlist_id']}", json_body=body)
        )
    return _invalid("action")


def spotify_albums(args: dict, **kwargs) -> str:
    missing = _missing(args, "album_id")
    if missing:
        return _invalid(*missing)
    service = _service(kwargs)
    action = args.get("action")
    if action == "get":
        return _result(
            lambda: service.request(
                "GET", f"/albums/{args['album_id']}", params=_params(args, "market") or None
            )
        )
    if action == "tracks":
        return _result(
            lambda: service.request(
                "GET",
                f"/albums/{args['album_id']}/tracks",
                params=_params(args, "market", "limit", "offset") or None,
            )
        )
    return _invalid("action")


def spotify_library(args: dict, **kwargs) -> str:
    service = _service(kwargs)
    kind = args.get("kind")
    action = args.get("action")
    if kind not in {"tracks", "albums"}:
        return _invalid("kind")
    path = f"/me/{kind}"
    if action == "list":
        return _result(
            lambda: service.request(
                "GET", path, params=_params(args, "market", "limit", "offset") or None
            )
        )
    if action in {"save", "remove", "save_current", "remove_current"}:
        def mutate() -> dict:
            uris = list(args.get("uris") or [])
            if action in {"save_current", "remove_current"}:
                current = service.request("GET", "/me/player/currently-playing")
                item = current.get("item") if isinstance(current, dict) else None
                uri = item.get("uri") if isinstance(item, dict) else None
                if not uri or not str(uri).startswith("spotify:track:"):
                    raise SpotifyNoActiveDevice("No Spotify track is currently playing")
                uris = [str(uri)]
            if not uris:
                singular = "track" if kind == "tracks" else "album"
                uris = [f"spotify:{singular}:{item_id}" for item_id in (args.get("ids") or [])]
            if not uris:
                raise ValueError("ids or uris")
            method = "PUT" if action in {"save", "save_current"} else "DELETE"
            return service.request(method, "/me/library", params={"uris": ",".join(uris)})

        if action in {"save", "remove"} and not (args.get("ids") or args.get("uris")):
            return _invalid("ids or uris")
        return _result(mutate)
    return _invalid("action")


HANDLERS = {
    "spotify_playback": spotify_playback,
    "spotify_devices": spotify_devices,
    "spotify_queue": spotify_queue,
    "spotify_search": spotify_search,
    "spotify_playlists": spotify_playlists,
    "spotify_albums": spotify_albums,
    "spotify_library": spotify_library,
}
