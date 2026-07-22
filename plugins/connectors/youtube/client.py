"""Bounded YouTube Data API client with OAuth refresh handling."""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from .auth import DEFAULT_SCOPES, REVOKE_URL, TOKEN_URL, YouTubeAuthStore
from .errors import YouTubeAPIError, YouTubeAuthError


API_ROOT = "https://www.googleapis.com/youtube/v3"
RequestBackend = Callable[..., Any]


class YouTubeClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        store: YouTubeAuthStore,
        request_backend: RequestBackend | None = None,
        timeout_seconds: float = 20.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.store = store
        self.request_backend = request_backend or httpx.request
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
        if not self.client_id or not code or not redirect_uri or not code_verifier:
            raise YouTubeAuthError("YouTube token exchange configuration is incomplete")
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret
        tokens = self._request_json("POST", TOKEN_URL, data=payload, auth_error=True)
        granted_scopes = set(str(tokens.get("scope") or "").split())
        if not set(DEFAULT_SCOPES).issubset(granted_scopes):
            raise YouTubeAuthError("YouTube read-only permission was not granted")
        tokens["expires_at"] = self.clock() + max(0, int(tokens.get("expires_in") or 0))
        return self.store.save_tokens(tokens)

    def refresh(self) -> dict[str, Any]:
        current = self.store.load_tokens()
        refresh_token = str(current.get("refresh_token") or "")
        if not refresh_token:
            raise YouTubeAuthError("YouTube authorization must be renewed")
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        if self.client_secret:
            payload["client_secret"] = self.client_secret
        refreshed = self._request_json("POST", TOKEN_URL, data=payload, auth_error=True)
        refreshed.setdefault("refresh_token", refresh_token)
        refreshed["expires_at"] = self.clock() + max(0, int(refreshed.get("expires_in") or 0))
        return self.store.save_tokens(refreshed)

    def get_my_channel(self) -> dict[str, Any]:
        payload = self._api_get(
            "/channels",
            params={"part": "id,snippet,contentDetails", "mine": "true", "maxResults": 1},
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if not items:
            raise YouTubeAPIError("YouTube account has no accessible channel")
        item = items[0] if isinstance(items[0], dict) else {}
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        content = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
        playlists = content.get("relatedPlaylists") if isinstance(content.get("relatedPlaylists"), dict) else {}
        channel_id = str(item.get("id") or "")
        if not channel_id:
            raise YouTubeAPIError("YouTube channel response is incomplete")
        return {
            "channel_id": channel_id,
            "title": str(snippet.get("title") or ""),
            "description": str(snippet.get("description") or ""),
            "custom_url": str(snippet.get("customUrl") or ""),
            "published_at": str(snippet.get("publishedAt") or ""),
            "uploads_playlist_id": str(playlists.get("uploads") or ""),
            "likes_playlist_id": str(playlists.get("likes") or ""),
        }

    def list_subscriptions(self, *, max_pages: int = 100) -> list[dict[str, Any]]:
        subscriptions: list[dict[str, Any]] = []
        page_token = ""
        for _page in range(max(1, min(max_pages, 100))):
            params = {
                "part": "snippet",
                "mine": "true",
                "maxResults": 50,
                "order": "alphabetical",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._api_get("/subscriptions", params=params)
            items = payload.get("items") if isinstance(payload.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
                resource = snippet.get("resourceId") if isinstance(snippet.get("resourceId"), dict) else {}
                channel_id = str(resource.get("channelId") or "")
                if not channel_id:
                    continue
                subscriptions.append(
                    {
                        "subscription_id": str(item.get("id") or ""),
                        "channel_id": channel_id,
                        "title": str(snippet.get("title") or ""),
                        "description": str(snippet.get("description") or ""),
                        "published_at": str(snippet.get("publishedAt") or ""),
                        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                    }
                )
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        else:
            raise YouTubeAPIError("YouTube subscription pagination exceeded its safety limit")
        return subscriptions

    def list_liked_videos(self, *, max_results: int = 20) -> list[dict[str, Any]]:
        profile = self.get_my_channel()
        playlist_id = str(profile.get("likes_playlist_id") or "")
        if not playlist_id:
            return []
        return self.list_playlist_videos(playlist_id, max_results=max_results)

    def list_playlist_videos(self, playlist_id: str, *, max_results: int = 20) -> list[dict[str, Any]]:
        clean_playlist_id = playlist_id.strip()
        if not clean_playlist_id:
            return []
        limit = max(1, min(int(max_results), 50))
        payload = self._api_get(
            "/playlistItems",
            params={
                "part": "snippet,contentDetails",
                "playlistId": clean_playlist_id,
                "maxResults": limit,
            },
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        videos: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            content = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
            resource = snippet.get("resourceId") if isinstance(snippet.get("resourceId"), dict) else {}
            video_id = str(content.get("videoId") or resource.get("videoId") or "")
            if not video_id:
                continue
            videos.append(
                {
                    "playlist_item_id": str(item.get("id") or ""),
                    "video_id": video_id,
                    "title": str(snippet.get("title") or ""),
                    "description": str(snippet.get("description") or ""),
                    "channel_id": str(snippet.get("videoOwnerChannelId") or ""),
                    "channel_title": str(snippet.get("videoOwnerChannelTitle") or ""),
                    "published_at": str(content.get("videoPublishedAt") or ""),
                    "added_at": str(snippet.get("publishedAt") or ""),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
        return videos

    def disconnect(self) -> None:
        tokens = self.store.load_tokens(required=False)
        token = str(tokens.get("refresh_token") or tokens.get("access_token") or "")
        if token:
            try:
                response = self.request_backend(
                    "POST",
                    REVOKE_URL,
                    data={"token": token},
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:
                raise YouTubeAuthError("YouTube token revocation is unreachable") from exc
            if int(getattr(response, "status_code", 0)) not in {200, 400}:
                raise YouTubeAuthError("YouTube token revocation failed")
        self.store.clear()

    def _api_get(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        tokens = self._valid_tokens()
        try:
            response = self.request_backend(
                "GET",
                f"{API_ROOT}{path}",
                params=params,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise YouTubeAPIError("YouTube request is unreachable") from exc
        if int(getattr(response, "status_code", 0)) == 401:
            tokens = self.refresh()
            try:
                response = self.request_backend(
                    "GET",
                    f"{API_ROOT}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {tokens['access_token']}"},
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:
                raise YouTubeAPIError("YouTube request is unreachable") from exc
        return self._decode_response(response, auth_error=False)

    def _valid_tokens(self) -> dict[str, Any]:
        tokens = self.store.load_tokens()
        if float(tokens.get("expires_at") or 0) <= self.clock() + 60:
            return self.refresh()
        return tokens

    def _request_json(self, method: str, url: str, *, auth_error: bool, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.request_backend(method, url, timeout=self.timeout_seconds, **kwargs)
        except Exception as exc:
            error = YouTubeAuthError if auth_error else YouTubeAPIError
            raise error("YouTube request is unreachable") from exc
        return self._decode_response(response, auth_error=auth_error)

    @staticmethod
    def _decode_response(response: Any, *, auth_error: bool) -> dict[str, Any]:
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            error = YouTubeAuthError if auth_error else YouTubeAPIError
            if status in {401, 403}:
                raise error("YouTube authorization is invalid or insufficient")
            if status == 429:
                raise error("YouTube quota is temporarily exhausted")
            raise error("YouTube request failed")
        try:
            payload = response.json()
        except Exception as exc:
            error = YouTubeAuthError if auth_error else YouTubeAPIError
            raise error("YouTube returned an invalid response") from exc
        if not isinstance(payload, dict):
            error = YouTubeAuthError if auth_error else YouTubeAPIError
            raise error("YouTube returned an invalid response")
        return payload
