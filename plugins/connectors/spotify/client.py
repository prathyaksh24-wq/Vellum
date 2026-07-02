"""Spotify Web API client with refresh and sanitized errors."""

from __future__ import annotations

import time
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

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        content: Any = None,
    ) -> dict:
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
        saved = self.auth_store.load_tokens()
        token = str(saved.get("access_token") or "")
        if not token:
            raise SpotifyAuthError("Spotify access token is missing")
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
            self.refresh()
            return self._request(
                method,
                path,
                params=params,
                json_body=json_body,
                content=content,
                retried=True,
            )
        if response.status_code == 204:
            return {"is_playing": False, "item": None}
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
        saved = self.auth_store.load_tokens()
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
        payload = self.request("GET", "/me/player")
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
        images = album.get("images") if isinstance(album.get("images"), list) else []
        artwork = images[0].get("url", "") if images and isinstance(images[0], dict) else ""
        artists = item.get("artists") if isinstance(item.get("artists"), list) else []
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
            "album": str(album.get("name") or ""),
            "artwork_url": str(artwork),
            "device": payload.get("device"),
            "shuffle": bool(payload.get("shuffle_state")),
            "repeat": str(payload.get("repeat_state") or "off"),
        }
