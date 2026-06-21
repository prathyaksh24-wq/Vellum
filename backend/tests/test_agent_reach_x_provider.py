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

    assert calls[0][:5] == ["agent-reach", "exec", "twitter", "--", "search_tweets"]
    assert result[0]["text"] == "hello x"
    assert result[0]["url"] == "https://x.com/a/status/1"
    assert result[0]["handle"] == "a"


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

    assert calls[0] == ["agent-reach", "exec", "twitter", "--", "post_tweet", "hello"]
    assert result["id"] == "tweet-1"
