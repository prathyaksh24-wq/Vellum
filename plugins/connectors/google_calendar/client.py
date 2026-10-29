"""Bounded Google Calendar REST client with OAuth refresh handling."""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .auth import DEFAULT_SCOPES, TOKEN_URL, GoogleCalendarAuthStore
from .errors import GoogleCalendarAPIError, GoogleCalendarAuthError


API_ROOT = "https://www.googleapis.com/calendar/v3"
RequestBackend = Callable[..., Any]


class GoogleCalendarClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        store: GoogleCalendarAuthStore,
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
            raise GoogleCalendarAuthError("Google Calendar token exchange configuration is incomplete")
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        tokens = self._request_json("POST", TOKEN_URL, data=data, auth_error=True)
        if not set(DEFAULT_SCOPES).issubset(set(str(tokens.get("scope") or "").split())):
            raise GoogleCalendarAuthError("Required Google Calendar permissions were not granted")
        tokens["expires_at"] = self.clock() + max(0, int(tokens.get("expires_in") or 0))
        return self.store.save_tokens(tokens)

    def refresh(self) -> dict[str, Any]:
        current = self.store.load_tokens()
        refresh_token = str(current.get("refresh_token") or "")
        if not refresh_token:
            raise GoogleCalendarAuthError("Google Calendar authorization must be renewed")
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        refreshed = self._request_json("POST", TOKEN_URL, data=data, auth_error=True)
        refreshed.setdefault("refresh_token", refresh_token)
        refreshed.setdefault("scope", current.get("scope") or " ".join(DEFAULT_SCOPES))
        refreshed["expires_at"] = self.clock() + max(0, int(refreshed.get("expires_in") or 0))
        return self.store.save_tokens(refreshed)

    def primary_calendar(self) -> dict[str, Any]:
        primary = next((item for item in self.list_calendars() if item.get("primary") is True), None)
        if primary is None:
            raise GoogleCalendarAPIError("Google Calendar primary calendar is unavailable")
        return primary

    def calendar_settings(self) -> dict[str, str]:
        payload = self._api_request("GET", "/users/me/settings")
        settings: dict[str, str] = {}
        for item in payload.get("items", []):
            if isinstance(item, dict) and item.get("id"):
                settings[str(item["id"])] = str(item.get("value") or "")
        return settings

    def list_calendars(self) -> list[dict[str, Any]]:
        payload = self._api_request("GET", "/users/me/calendarList", params={"maxResults": 250})
        return [dict(item) for item in payload.get("items", []) if isinstance(item, dict)]

    def list_events(
        self,
        *,
        calendar_id: str = "primary",
        time_min: str,
        time_max: str,
        query: str = "",
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max(1, min(int(max_results), 250)),
        }
        if query.strip():
            params["q"] = query.strip()
        payload = self._api_request("GET", self._events_path(calendar_id), params=params)
        return [dict(item) for item in payload.get("items", []) if isinstance(item, dict)]

    def get_event(self, *, calendar_id: str, event_id: str) -> dict[str, Any]:
        return self._api_request("GET", f"{self._events_path(calendar_id)}/{quote(event_id, safe='')}")

    def free_busy(self, *, time_min: str, time_max: str, calendar_ids: list[str]) -> dict[str, Any]:
        return self._api_request(
            "POST",
            "/freeBusy",
            json={"timeMin": time_min, "timeMax": time_max, "items": [{"id": item} for item in calendar_ids[:50]]},
        )

    def create_event(self, *, calendar_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return self._api_request("POST", self._events_path(calendar_id), json=event)

    def update_event(self, *, calendar_id: str, event_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self._api_request(
            "PATCH",
            f"{self._events_path(calendar_id)}/{quote(event_id, safe='')}",
            json=patch,
        )

    def delete_event(self, *, calendar_id: str, event_id: str) -> dict[str, Any]:
        self._api_request(
            "DELETE",
            f"{self._events_path(calendar_id)}/{quote(event_id, safe='')}",
            expect_empty=True,
        )
        return {"deleted": True, "event_id": event_id, "calendar_id": calendar_id}

    def disconnect(self) -> None:
        # A local disconnect avoids revoking other grants from the same Google project.
        self.store.clear()

    @staticmethod
    def _events_path(calendar_id: str) -> str:
        return f"/calendars/{quote(calendar_id.strip() or 'primary', safe='')}/events"

    def _valid_tokens(self) -> dict[str, Any]:
        tokens = self.store.load_tokens()
        if float(tokens.get("expires_at") or 0) <= self.clock() + 60:
            return self.refresh()
        return tokens

    def _api_request(self, method: str, path: str, *, expect_empty: bool = False, **kwargs: Any) -> dict[str, Any]:
        tokens = self._valid_tokens()
        response = self._send(method, f"{API_ROOT}{path}", tokens=tokens, **kwargs)
        if int(getattr(response, "status_code", 0)) == 401:
            tokens = self.refresh()
            response = self._send(method, f"{API_ROOT}{path}", tokens=tokens, **kwargs)
        if expect_empty and 200 <= int(getattr(response, "status_code", 0)) < 300:
            return {}
        return self._decode_response(response, auth_error=False)

    def _send(self, method: str, url: str, *, tokens: dict[str, Any], **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {tokens['access_token']}"
        try:
            return self.request_backend(method, url, headers=headers, timeout=self.timeout_seconds, **kwargs)
        except Exception as exc:
            raise GoogleCalendarAPIError("Google Calendar request is unreachable") from exc

    def _request_json(self, method: str, url: str, *, auth_error: bool, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.request_backend(method, url, timeout=self.timeout_seconds, **kwargs)
        except Exception as exc:
            error = GoogleCalendarAuthError if auth_error else GoogleCalendarAPIError
            raise error("Google Calendar request is unreachable") from exc
        return self._decode_response(response, auth_error=auth_error)

    @staticmethod
    def _decode_response(response: Any, *, auth_error: bool) -> dict[str, Any]:
        status = int(getattr(response, "status_code", 0))
        error = GoogleCalendarAuthError if auth_error else GoogleCalendarAPIError
        if status < 200 or status >= 300:
            if status in {401, 403}:
                raise error("Google Calendar authorization is invalid or insufficient")
            if status == 404:
                raise error("Google Calendar item was not found")
            if status == 409:
                raise error("Google Calendar item conflicts with an existing item")
            if status == 429:
                raise error("Google Calendar quota is temporarily exhausted")
            raise error("Google Calendar request failed")
        try:
            payload = response.json()
        except Exception as exc:
            raise error("Google Calendar response is invalid") from exc
        if not isinstance(payload, dict):
            raise error("Google Calendar response is invalid")
        return payload
