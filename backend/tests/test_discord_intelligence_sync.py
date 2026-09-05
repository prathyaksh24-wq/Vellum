from __future__ import annotations

from types import SimpleNamespace

from agent.scheduler import discord_intelligence


def test_sync_reads_only_allowlisted_channels_through_observed_registry(monkeypatch) -> None:
    calls = []

    class FakeRegistry:
        def invoke(self, name, payload, *, agent_name):
            calls.append((name, payload, agent_name))
            return {"items": [{"id": "message-1"}, {"id": "message-2"}]}

    monkeypatch.setattr(
        discord_intelligence,
        "get_settings",
        lambda: SimpleNamespace(
            discord_bot_token="token",
            discord_allowed_channel_ids="channel-1,channel-2",
            discord_intelligence_sync_enabled=True,
            obsidian_vault_path="D:/Vault",
        ),
    )
    monkeypatch.setattr(discord_intelligence, "_registry", lambda: FakeRegistry())

    result = discord_intelligence.run_sync()

    assert result == {"channels": 2, "messages": 4}
    assert calls == [
        ("discord.messages", {"channel_id": "channel-1", "limit": 100}, "DiscordAgent"),
        ("discord.messages", {"channel_id": "channel-2", "limit": 100}, "DiscordAgent"),
    ]


def test_sync_is_a_noop_when_discord_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        discord_intelligence,
        "get_settings",
        lambda: SimpleNamespace(
            discord_bot_token="",
            discord_allowed_channel_ids="channel-1",
            discord_intelligence_sync_enabled=True,
            obsidian_vault_path="D:/Vault",
        ),
    )

    assert discord_intelligence.run_sync() == {"channels": 0, "messages": 0}
