from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.plugins import discord_api
from agent.tools.capabilities.discord_service import DiscordCapabilityService


class FakeDiscordClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bool]] = []

    def list_guilds(self):
        return [{"id": "111111111111111111", "name": "Test Guild", "allowed": True}]

    def list_channels(self, guild_id: str):
        return [{"id": "222222222222222222", "guild_id": guild_id, "name": "general", "allowed": True}]

    def list_messages(self, channel_id: str, *, limit: int, before: str):
        return [{"id": "message-1", "channel_id": channel_id, "content": "Hello"}][:limit]

    def send_message(self, channel_id: str, content: str, *, confirmed: bool):
        self.sent.append((channel_id, content, confirmed))
        return {"id": "sent-1", "channel_id": channel_id, "content": content}


def _client(monkeypatch) -> tuple[TestClient, FakeDiscordClient]:
    fake = FakeDiscordClient()
    service = DiscordCapabilityService(
        account_backend=lambda: {"id": "bot-1", "username": "Vellum"},
        guilds_backend=fake.list_guilds,
        channels_backend=fake.list_channels,
        messages_backend=lambda channel_id, limit, before: fake.list_messages(
            channel_id, limit=limit, before=before
        ),
        send_backend=lambda channel_id, content, confirmed: fake.send_message(
            channel_id, content, confirmed=confirmed
        ),
        allowed_guild_ids={"111111111111111111"},
        allowed_channel_ids={"222222222222222222"},
    )
    monkeypatch.setattr(discord_api, "discord_service", lambda: service)
    monkeypatch.setattr(
        discord_api,
        "discord_status",
        lambda probe=False: {
            "configured": True,
            "connected": probe,
            "status": "connected" if probe else "configured",
            "application_id": "123456789012345678",
            "bot_id": "987654321098765432",
            "bot_username": "Vellum",
            "allowed_guild_count": 1,
            "allowed_channel_count": 1,
            "autonomous_channel_count": 0,
        },
    )
    app = FastAPI()
    app.include_router(discord_api.router, prefix="/api")
    return TestClient(app), fake


def test_discord_status_and_reads_do_not_expose_bot_token(monkeypatch) -> None:
    client, _fake = _client(monkeypatch)

    status = client.get("/api/plugins/discord/status")
    guilds = client.get("/api/plugins/discord/guilds")
    channels = client.get("/api/plugins/discord/guilds/111111111111111111/channels")
    messages = client.get("/api/plugins/discord/channels/222222222222222222/messages?limit=10")

    assert status.status_code == 200
    assert status.json()["bot_username"] == "Vellum"
    assert "token" not in status.text.casefold()
    assert guilds.json()["items"][0]["name"] == "Test Guild"
    assert channels.json()["items"][0]["name"] == "general"
    assert messages.json()["items"][0]["content"] == "Hello"


def test_discord_http_send_passes_explicit_confirmation(monkeypatch) -> None:
    client, fake = _client(monkeypatch)

    response = client.post(
        "/api/plugins/discord/channels/222222222222222222/messages",
        json={"content": "Ship the update", "confirm": True},
    )

    assert response.status_code == 200
    assert response.json()["message"]["id"] == "sent-1"
    assert fake.sent == [("222222222222222222", "Ship the update", True)]


def test_discord_http_send_rejects_untyped_confirmation(monkeypatch) -> None:
    client, _fake = _client(monkeypatch)

    response = client.post(
        "/api/plugins/discord/channels/222222222222222222/messages",
        json={"content": "Ship the update", "confirm": "yes"},
    )

    assert response.status_code == 422


def test_discord_http_reads_fail_closed_outside_channel_allowlist(monkeypatch) -> None:
    client, _fake = _client(monkeypatch)

    response = client.get("/api/plugins/discord/channels/333333333333333333/messages")

    assert response.status_code == 403
    assert response.json() == {"detail": "Discord channel is not allowlisted"}
