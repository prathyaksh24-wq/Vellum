"""Spotify Web API client with refresh and sanitized errors."""

from __future__ import annotations

import time
import threading
from typing import Any

import httpx

from .auth import SpotifyAuthStore
from .errors import (
    SpotifyAPIError,
    SpotifyAuthError,
    SpotifyNoActiveDevice,
    SpotifyPremiumRequired,
    SpotifyRateLimited,
)


class SpotifyClient:
    API_BASE = "https://api.spotify.com/v1"
    TOKEN_URL = "https://accounts.spotify.com/api/token"

    def __init__(
        self,
        auth_store: SpotifyAuthStore,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 20.0,
    ):
        self.auth_store = auth_store
        self.transport = transport
        self.timeout = timeout
        self._device_lock = threading.RLock()
        self._web_player = None
        self._sdk_refresh_at = float("-inf")

    def playback_token(self, *, force_refresh: bool = False) -> dict:
        """Only the trusted playback view consumes this; never expose as a tool."""
        with self.auth_store.token_lock:
            token = self._get_access_token()
            if force_refresh and time.monotonic() - self._sdk_refresh_at >= 60:
                token = self._get_access_token(rejected_token=token)
                self._sdk_refresh_at = time.monotonic()
            saved = self.auth_store.load_tokens()
            required = {"streaming", "user-read-email", "user-read-private"}
            if not required.issubset(set(str(saved.get("scope") or "").split())):
                raise SpotifyAuthError("Reconnect Spotify to allow playback inside Vellum")
            return {"access_token": token, "expires_at": float(saved.get("expires_at") or 0)}

    def claim_web_player(self, owner_id: str) -> dict:
        with self._device_lock:
            current = self._web_player
            if current and current["owner_id"] != owner_id and current["expires_at"] > time.monotonic():
                raise SpotifyNoActiveDevice("Vellum playback is already running in another window")
            self._web_player = {"owner_id": owner_id, "device_id": "", "expires_at": time.monotonic() + 90}
            return {"status": "connecting"}

    def update_web_player(self, owner_id: str, device_id: str, diagnostics: list[dict] | None = None) -> dict:
        with self._device_lock:
            if not self._web_player or self._web_player["owner_id"] != owner_id:
                raise SpotifyNoActiveDevice("This window no longer owns Vellum playback. Enable playback again.")
            self._web_player.update(device_id=device_id, expires_at=time.monotonic() + 90)
            if diagnostics:
                self._web_player["diagnostics"] = [*self._web_player.get("diagnostics", []), *diagnostics][-32:]
            return {"status": "ready" if device_id else "reconnecting"}

    def release_web_player(self, owner_id: str | None = None) -> dict:
        with self._device_lock:
            if owner_id is None or (self._web_player and self._web_player["owner_id"] == owner_id):
                self._web_player = None
            return {"status": "disabled"}

    def preferred_device_id(self) -> str:
        with self._device_lock:
            if self._web_player is None:
                return ""
            if not self._web_player["device_id"] or self._web_player["expires_at"] <= time.monotonic():
                raise SpotifyNoActiveDevice("Vellum player is not ready. Enable playback in Vellum's Spotify player.")
            return self._web_player["device_id"]

    def web_playback_status(self) -> dict:
        with self._device_lock:
            if self._web_player is None:
                return {"status": "disabled"}
            current = self._web_player
            live = current["expires_at"] > time.monotonic()
            return {"status": "ready" if live and current["device_id"] else "reconnecting",
                    "diagnostics": list(current.get("diagnostics", [])),
                    "commands": dict(current.get("commands", {}))}

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        content: Any = None,
    ) -> dict:
        if method.upper() != "GET" and path.startswith("/me/player"):
            with self._device_lock:
                if self._web_player is not None:
                    commands = self._web_player.setdefault("commands", {})
                    key = method.upper() + " " + path
                    commands[key] = commands.get(key, 0) + 1
        return self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            content=content,
            retried=False,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json_body: Any,
        content: Any,
        retried: bool,
    ) -> dict:
        token = self._get_access_token()
        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            response = client.request(
                method.upper(),
                self.API_BASE + "/" + path.lstrip("/"),
                params=params,
                json=json_body,
                content=content,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code == 401 and not retried:
            self._get_access_token(rejected_token=token)
            return self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                content=content,
                retried=True,
            )
        if response.status_code == 204:
            if method.upper() == "GET" and "/" + path.strip("/") in {"/me/player", "/me/player/currently-playing"}:
                return {"is_playing": False, "item": None}
            return {}
        self._raise_for_status(response)
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code < 300 and method.upper() in {"POST", "PUT", "DELETE"}:
                return {}
            raise SpotifyAPIError("Spotify returned an invalid response") from exc
        return payload if isinstance(payload, dict) else {"items": payload}

    def exchange_code(
        self,
        *,
        client_id: str,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict:
        tokens = self._token_request(
            {
                "client_id": client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        saved = self._normalized_tokens(tokens, client_id=client_id)
        self.auth_store.save_tokens(saved)
        return saved

    def refresh(self) -> dict:
        with self.auth_store.token_lock:
            return self._refresh_tokens(self.auth_store.load_tokens())

    def _get_access_token(self, *, rejected_token: str | None = None) -> str:
        with self.auth_store.token_lock:
            saved = self.auth_store.load_tokens()
            token = str(saved.get("access_token") or "")
            if not token:
                raise SpotifyAuthError("Spotify access token is missing")
            expires_at = saved.get("expires_at")
            try:
                expiring = expires_at is not None and float(expires_at) <= time.time() + 60
            except (TypeError, ValueError) as exc:
                raise SpotifyAuthError("Spotify token expiry is invalid") from exc
            # A concurrent client may have already replaced the rejected token.
            if expiring or (rejected_token is not None and rejected_token == token):
                saved = self._refresh_tokens(saved)
                token = str(saved["access_token"])
            return token

    def _refresh_tokens(self, saved: dict) -> dict:
        client_id = str(saved.get("client_id") or "")
        refresh_token = str(saved.get("refresh_token") or "")
        if not client_id or not refresh_token:
            raise SpotifyAuthError("Spotify refresh credentials are missing")
        refreshed = self._token_request(
            {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
        refreshed.setdefault("refresh_token", refresh_token)
        merged = {**saved, **self._normalized_tokens(refreshed, client_id=client_id)}
        self.auth_store.save_tokens(merged)
        return merged

    def _token_request(self, data: dict[str, str]) -> dict:
        with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
            response = client.post(
                self.TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code >= 400:
            raise SpotifyAuthError("Spotify authorization failed")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpotifyAuthError("Spotify authorization returned an invalid response") from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise SpotifyAuthError("Spotify authorization did not return an access token")
        return payload

    @staticmethod
    def _normalized_tokens(payload: dict, *, client_id: str) -> dict:
        expires_in = int(payload.get("expires_in") or 3600)
        normalized = dict(payload)
        normalized["client_id"] = client_id
        normalized["expires_at"] = time.time() + expires_in
        return normalized

    @staticmethod
    def _safe_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return ""
        if not isinstance(payload, dict):
            return ""
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or "")[:240]
        return str(error or "")[:240]

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 429:
            raw = response.headers.get("Retry-After", "1")
            try:
                retry_after = max(1, int(raw))
            except ValueError:
                retry_after = 1
            raise SpotifyRateLimited(retry_after)
        message = self._safe_error_message(response).lower()
        if response.status_code in {403, 404} and "no active device" in message:
            raise SpotifyNoActiveDevice("No active Spotify device found")
        if response.status_code == 403 and ("premium" in message or "premium_required" in message):
            raise SpotifyPremiumRequired("Spotify Premium is required for this action")
        if response.status_code == 401:
            raise SpotifyAuthError("Spotify authorization expired")
        raise SpotifyAPIError(f"Spotify request failed with status {response.status_code}")

    def get_profile(self) -> dict:
        return self.request("GET", "/me")

    def get_devices(self) -> dict:
        return self.request("GET", "/me/player/devices")

    def get_queue(self) -> dict:
        return self.request("GET", "/me/player/queue")

    def get_player(self) -> dict:
        payload = self.request("GET", "/me/player", params={"additional_types":"track,episode"})
        item = payload.get("item") if isinstance(payload.get("item"), dict) else None
        if not item:
            return {
                "is_playing": False,
                "progress_ms": 0,
                "duration_ms": 0,
                "track": None,
                "artists": [],
                "album": "",
                "artwork_url": "",
                "device": payload.get("device"),
                "shuffle": bool(payload.get("shuffle_state")),
                "repeat": str(payload.get("repeat_state") or "off"),
            }
        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        show = item.get("show") if isinstance(item.get("show"), dict) else {}
        images = item.get("images") or album.get("images") or show.get("images") or []
        artwork = images[0].get("url", "") if images and isinstance(images[0], dict) else ""
        artists = item.get("artists") if isinstance(item.get("artists"), list) else []
        if not artists and show.get("name"):
            artists = [{"name":show["name"]}]
        return {
            "is_playing": bool(payload.get("is_playing")),
            "progress_ms": int(payload.get("progress_ms") or 0),
            "duration_ms": int(item.get("duration_ms") or 0),
            "track": {
                "id": str(item.get("id") or ""),
                "uri": str(item.get("uri") or ""),
                "name": str(item.get("name") or ""),
            },
            "artists": [str(artist.get("name") or "") for artist in artists if isinstance(artist, dict)],
            "album": str(album.get("name") or show.get("name") or ""),
            "artwork_url": str(artwork),
            "device": payload.get("device"),
            "shuffle": bool(payload.get("shuffle_state")),
            "repeat": str(payload.get("repeat_state") or "off"),
        }
