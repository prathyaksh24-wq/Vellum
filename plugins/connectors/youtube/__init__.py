"""Portable YouTube connector registration."""

from __future__ import annotations

from . import auth, client, errors


YouTubeAuthStore = auth.YouTubeAuthStore
YouTubeClient = client.YouTubeClient


def register(ctx) -> None:
    ctx.register_connector(
        id="youtube",
        name="YouTube",
        category="Connectors",
        status_factory=lambda: {
            "id": "youtube",
            "name": "YouTube",
            "type": "connector",
            "category": "Connectors",
            "status": "backend_managed",
            "capabilities": ["youtube.account", "youtube.subscriptions", "youtube.liked_videos"],
        },
        service_factory=YouTubeClient,
        capabilities=["youtube.account", "youtube.subscriptions", "youtube.liked_videos"],
    )


__all__ = ["YouTubeAuthStore", "YouTubeClient", "auth", "client", "errors", "register"]
