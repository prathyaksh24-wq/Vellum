"""Vellum runtime adapter for the portable Google Calendar connector."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from agent.config import REPO_ROOT, get_settings
from agent.plugins.portable import load_portable_plugin


PLUGIN_DIR = REPO_ROOT / "plugins" / "connectors" / "google_calendar"
AUTH_DIR = REPO_ROOT / "data" / "plugins" / "google-calendar"


@lru_cache(maxsize=1)
def google_calendar_plugin():
    return load_portable_plugin(PLUGIN_DIR)


_calendar_module = google_calendar_plugin().module
GoogleCalendarAuthError = _calendar_module.errors.GoogleCalendarAuthError
GoogleCalendarAPIError = _calendar_module.errors.GoogleCalendarAPIError


def _credentials() -> tuple[str, str]:
    settings = get_settings()
    return (
        settings.google_calendar_oauth_client_id or settings.youtube_oauth_client_id,
        settings.google_calendar_oauth_client_secret or settings.youtube_oauth_client_secret,
    )


def google_calendar_store(*, keyring_backend: Any | None = None):
    settings = get_settings()
    return _calendar_module.auth.GoogleCalendarAuthStore(
        AUTH_DIR,
        keyring_backend=keyring_backend,
        keyring_service=settings.google_calendar_oauth_keyring_service,
        account_label=settings.google_calendar_oauth_account_label,
    )


def google_calendar_client(*, store: Any | None = None, request_backend: Any | None = None):
    client_id, client_secret = _credentials()
    return _calendar_module.client.GoogleCalendarClient(
        client_id=client_id,
        client_secret=client_secret,
        store=store or google_calendar_store(),
        request_backend=request_backend,
    )


def google_calendar_authorization_url(**kwargs: Any) -> str:
    return _calendar_module.auth.authorization_url(**kwargs)


def google_calendar_pkce_pair() -> tuple[str, str]:
    return _calendar_module.auth.new_pkce_pair()


def google_calendar_scopes() -> tuple[str, ...]:
    return tuple(_calendar_module.auth.DEFAULT_SCOPES)


def google_calendar_status(*, probe: bool = False) -> dict[str, Any]:
    settings = get_settings()
    client_id, _ = _credentials()
    store = google_calendar_store()
    try:
        connected = bool(store.load_tokens(required=False))
        metadata = store.load_metadata()
        status = "ready" if connected else "not_connected"
        if connected and probe:
            profile = google_calendar_client(store=store).primary_calendar()
            store.save_profile(profile)
            metadata = store.load_metadata()
    except GoogleCalendarAuthError:
        connected = False
        metadata = {}
        status = "keyring_unavailable"
    except GoogleCalendarAPIError:
        connected = True
        metadata = store.load_metadata()
        status = "unreachable"
    return {
        "configured": bool(client_id),
        "connected": connected,
        "status": status if client_id else "not_configured",
        "account_label": settings.google_calendar_oauth_account_label,
        "calendar_label": str(metadata.get("calendar_label") or ""),
        "time_zone": str(metadata.get("time_zone") or ""),
        "scopes": str(metadata.get("scope") or "").split(),
    }


def portable_google_calendar_status() -> dict[str, Any]:
    status = google_calendar_status()
    return {
        "id": "google-calendar",
        "name": "Google Calendar",
        "type": "connector",
        "category": "Connectors",
        "configured": bool(status["configured"]),
        "status": str(status["status"]),
        "notes": (
            "Connected to the primary Google Calendar."
            if status["connected"]
            else "Connect Google Calendar for private schedule reads and confirmed event changes."
        ),
        "capabilities": list(_calendar_module.CAPABILITIES),
    }


@lru_cache(maxsize=1)
def google_calendar_service():
    from agent.tools.capabilities.calendar_service import CalendarCapabilityService

    return CalendarCapabilityService()
