import subprocess

import pytest

from agent.tools.capabilities.agent_reach_x_provider import (
    AgentReachCommandError,
    AgentReachTimeoutError,
    AgentReachXProvider,
)


def test_agent_reach_provider_search_command_success_normalizes_results():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout='{"tweets":[{"text":"hello x","url":"https://x.com/a/status/1","author":{"username":"a"},"created_at":"2026-06-21"}]}',
            stderr="",
        )

    provider = AgentReachXProvider(runner=fake_runner)

    result = provider.search("hello", max_results=3)

    assert calls[0] == ["twitter", "search", "hello", "--max", "3", "--json"]
    assert result[0]["text"] == "hello x"
    assert result[0]["url"] == "https://x.com/a/status/1"
    assert result[0]["handle"] == "a"


def test_agent_reach_provider_normalizes_twitter_cli_schema_with_generated_url():
    def fake_runner(args, **_kwargs):
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                '{"ok":true,"data":[{"id":"2065225362544726371","text":"Codex update",'
                '"author":{"screenName":"OpenAI"},"createdAtISO":"2026-06-12T00:11:11+00:00"}]}'
            ),
            stderr="",
        )

    provider = AgentReachXProvider(runner=fake_runner)

    result = provider.search("from:OpenAI", max_results=1)

    assert result[0]["handle"] == "OpenAI"
    assert result[0]["url"] == "https://x.com/OpenAI/status/2065225362544726371"
    assert result[0]["created_at"] == "2026-06-12T00:11:11+00:00"


def test_agent_reach_provider_missing_binary_reports_setup(monkeypatch):
    monkeypatch.setattr("agent.tools.capabilities.agent_reach_x_provider.shutil.which", lambda _name: None)

    provider = AgentReachXProvider()

    status = provider.status()

    assert status.status == "missing_agent_reach"
    assert "Install Agent-Reach" in status.notes


def test_agent_reach_provider_timeout_raises_sanitized_error():
    def fake_runner(args, **_kwargs):
        raise subprocess.TimeoutExpired(args, 1)

    provider = AgentReachXProvider(runner=fake_runner, timeout_seconds=1)

    with pytest.raises(AgentReachTimeoutError, match="timed out"):
        provider.search("news")


def test_agent_reach_provider_command_error_redacts_secrets():
    def fake_runner(args, **_kwargs):
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890",
        )

    provider = AgentReachXProvider(runner=fake_runner)

    with pytest.raises(AgentReachCommandError) as exc:
        provider.search("news")

    message = str(exc.value)
    assert "Bearer" in message
    assert "abcdefghijklmnopqrstuvwxyz" not in message
    assert "[redacted]" in message


def test_agent_reach_provider_write_methods_use_agent_reach_commands():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"id":"tweet-1","text":"hello"}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner)

    result = provider.post_tweet("hello")

    assert calls[0] == ["twitter", "post", "hello", "--json"]
    assert result["id"] == "tweet-1"


def test_agent_reach_provider_read_private_and_timeline_commands():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout='{"data":[{"id":"1","text":"saved","author":{"screenName":"me"}}]}',
            stderr="",
        )

    provider = AgentReachXProvider(runner=fake_runner)

    assert provider.bookmarks(max_results=4)[0]["text"] == "saved"
    assert provider.timeline(max_results=3)[0]["text"] == "saved"
    assert provider.likes("me", max_results=2)[0]["text"] == "saved"

    assert calls[0] == ["twitter", "bookmarks", "--max", "4", "--json"]
    assert calls[1] == ["twitter", "feed", "--max", "3", "--json"]
    assert calls[2] == ["twitter", "likes", "me", "--max", "2", "--json"]


def test_agent_reach_provider_write_action_commands_use_confirmation_safe_cli_flags():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"ok":true,"id":"123"}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner)

    provider.reply("123", "reply text")
    provider.like("123")
    provider.repost("123")
    provider.delete("123")

    assert calls[0] == ["twitter", "reply", "123", "reply text", "--json"]
    assert calls[1] == ["twitter", "like", "123", "--json"]
    assert calls[2] == ["twitter", "retweet", "123", "--json"]
    assert calls[3] == ["twitter", "delete", "123", "--yes", "--json"]
