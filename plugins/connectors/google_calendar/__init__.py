"""Portable Google Calendar connector registration."""

from __future__ import annotations

from . import auth, client, errors


GoogleCalendarAuthStore = auth.GoogleCalendarAuthStore
GoogleCalendarClient = client.GoogleCalendarClient
CAPABILITIES = [
    "calendar.account",
    "calendar.calendars",
    "calendar.events",
    "calendar.event",
    "calendar.free_busy",
    "calendar.create_event",
    "calendar.update_event",
    "calendar.delete_event",
]


def register(ctx) -> None:
    ctx.register_connector(
        id="google-calendar",
        name="Google Calendar",
        category="Connectors",
        status_factory=lambda: {
            "id": "google-calendar",
            "name": "Google Calendar",
            "type": "connector",
            "category": "Connectors",
            "status": "backend_managed",
            "capabilities": list(CAPABILITIES),
        },
        service_factory=GoogleCalendarClient,
        capabilities=list(CAPABILITIES),
    )


__all__ = ["GoogleCalendarAuthStore", "GoogleCalendarClient", "auth", "client", "errors", "register"]
