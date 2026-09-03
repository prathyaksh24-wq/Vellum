"""Bounded Discord REST client for an installed Vellum bot."""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from .errors import DiscordAPIError, DiscordAuthError
from .policy import DiscordAccessPolicy


API_ROOT = "https://discord.com/api/v10"
RequestBackend = Callable[..., Any]
SleepBackend = Callable[[float], None]


class DiscordClient:
    def __init__(
        self,
        *,
        bot_token: str,
        policy: DiscordAccessPolicy,
        request_backend: RequestBackend | None = None,
        sleep_backend: SleepBackend | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.bot_token = str(bot_token or "").strip()
        self.policy = policy
        self.request_backend = request_backend or httpx.request
        self.sleep_backend = sleep_backend or time.sleep
        self.timeout_seconds = timeout_seconds

    def get_current_user(self) -> dict[str, Any]:
        payload = self._request_json("GET", "/users/@me", auth_error=True)
        if not isinstance(payload, dict):
            raise DiscordAPIError("Discord returned an invalid response")
        return payload

    def list_guilds(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/users/@me/guilds", auth_error=True)
        items = payload if isinstance(payload, list) else []
        return [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "icon": str(item.get("icon") or ""),
                "allowed": str(item.get("id") or "") in self.policy.allowed_guild_ids,
            }
            for item in items
            if isinstance(item, dict) and str(item.get("id") or "")
        ]

    def list_channels(self, guild_id: str) -> list[dict[str, Any]]:
        clean_guild_id = self.policy.require_guild(guild_id)
        payload = self._request_json("GET", f"/guilds/{clean_guild_id}/channels")
        items = payload if isinstance(payload, list) else []
        return [
            {
                "id": str(item.get("id") or ""),
                "guild_id": clean_guild_id,
                "name": str(item.get("name") or ""),
                "type": int(item.get("type") or 0),
                "parent_id": str(item.get("parent_id") or ""),
                "position": int(item.get("position") or 0),
                "allowed": str(item.get("id") or "") in self.policy.allowed_channel_ids,
                "autonomous": str(item.get("id") or "") in self.policy.autonomous_channel_ids,
            }
            for item in items
            if isinstance(item, dict) and str(item.get("id") or "")
        ]

    def list_messages(self, channel_id: str, *, limit: int = 20, before: str = "") -> list[dict[str, Any]]:
        clean_channel_id = self.policy.require_channel(channel_id)
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 100))}
        if before:
            params["before"] = str(before).strip()
        payload = self._request_json("GET", f"/channels/{clean_channel_id}/messages", params=params)
        return [self._message(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def send_message(self, channel_id: str, content: str, *, confirmed: bool = False) -> dict[str, Any]:
        clean_channel_id = self.policy.authorize_send(channel_id, confirmed=confirmed)
        clean_content = str(content or "").strip()
        if not clean_content or len(clean_content) > 2000:
            raise DiscordAPIError("Discord message content must contain 1 to 2000 characters")
        payload = self._request_json(
            "POST",
            f"/channels/{clean_channel_id}/messages",
            json={"content": clean_content, "allowed_mentions": {"parse": []}},
        )
        if not isinstance(payload, dict):
            raise DiscordAPIError("Discord returned an invalid response")
        return self._message(payload)

    def _request_json(self, method: str, path: str, *, auth_error: bool = False, **kwargs: Any) -> Any:
        if not self.bot_token:
            raise DiscordAuthError("Discord bot token is not configured")
        response = None
        for attempt in range(2):
            try:
                response = self.request_backend(
                    method,
                    f"{API_ROOT}{path}",
                    headers={
                        "Authorization": f"Bot {self.bot_token}",
                        "User-Agent": "Vellum (https://github.com/prathyaksh24-wq/Vellum, 1.0)",
                    },
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
            except Exception as exc:
                if attempt == 0:
                    self.sleep_backend(0.25)
                    continue
                raise DiscordAPIError("Discord is unreachable") from exc

            status = int(getattr(response, "status_code", 0))
            if status not in {429, 502, 503, 504} or attempt > 0:
                break
            self.sleep_backend(self._retry_delay(response, status))

        status = int(getattr(response, "status_code", 0))
        if status in {401, 403}:
            error = DiscordAuthError if auth_error or status == 401 else DiscordAPIError
            raise error("Discord authorization is invalid or insufficient")
        if status == 429:
            raise DiscordAPIError("Discord rate limit was reached")
        if status < 200 or status >= 300:
            raise DiscordAPIError("Discord request failed")
        try:
            return response.json()
        except Exception as exc:
            raise DiscordAPIError("Discord returned an invalid response") from exc

    @staticmethod
    def _retry_delay(response: Any, status: int) -> float:
        if status != 429:
            return 0.25
        try:
            payload = response.json()
            retry_after = float(payload.get("retry_after", 0.25)) if isinstance(payload, dict) else 0.25
        except Exception:
            retry_after = 0.25
        return max(0.0, min(retry_after, 5.0))

    @staticmethod
    def _message(item: dict[str, Any]) -> dict[str, Any]:
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        return {
            "id": str(item.get("id") or ""),
            "channel_id": str(item.get("channel_id") or ""),
            "content": str(item.get("content") or ""),
            "timestamp": str(item.get("timestamp") or ""),
            "edited_timestamp": str(item.get("edited_timestamp") or ""),
            "author": {
                "id": str(author.get("id") or ""),
                "username": str(author.get("global_name") or author.get("username") or ""),
                "bot": bool(author.get("bot")),
            },
            "attachments": [
                {
                    "id": str(value.get("id") or ""),
                    "filename": str(value.get("filename") or ""),
                    "url": str(value.get("url") or ""),
                    "content_type": str(value.get("content_type") or ""),
                    "size": int(value.get("size") or 0),
                }
                for value in item.get("attachments", [])
                if isinstance(value, dict)
            ],
        }
