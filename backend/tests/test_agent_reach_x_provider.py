from concurrent.futures import ThreadPoolExecutor
import subprocess
import threading
import time

import pytest

from agent.tools.capabilities.agent_reach_x_provider import (
    AgentReachCommandError,
    AgentReachTimeoutError,
    AgentReachXProvider,
)
from agent.plugins.models import PluginStatus


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
    assert provider.likes("vellum-user", max_results=2)[0]["text"] == "saved"

    assert calls[0] == ["twitter", "bookmarks", "--max", "4", "--json"]
    assert calls[1] == ["twitter", "feed", "--max", "3", "--json"]
    assert calls[2] == ["twitter", "likes", "vellum-user", "--max", "2", "--json"]


def test_agent_reach_provider_resolves_self_before_reading_likes():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        if args[1] == "status":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"ok":true,"data":{"authenticated":true,"user":{"username":"vellum-user"}}}',
                stderr="",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            stdout='{"ok":true,"data":[{"id":"1","text":"saved","author":{"screenName":"me"}}]}',
            stderr="",
        )

    provider = AgentReachXProvider(runner=fake_runner)

    result = provider.likes("me", max_results=2)

    assert result[0]["text"] == "saved"
    assert calls == [
        ["twitter", "status", "--json"],
        ["twitter", "likes", "vellum-user", "--max", "2", "--json"],
    ]


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


def test_agent_reach_provider_normalizes_status_urls_for_write_commands():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"ok":true,"id":"1234567890123456789"}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner)

    provider.repost("https://x.com/openai/status/1234567890123456789?s=20")
    provider.delete("https://twitter.com/openai/status/1234567890123456789")

    assert calls[0] == ["twitter", "retweet", "1234567890123456789", "--json"]
    assert calls[1] == ["twitter", "delete", "1234567890123456789", "--yes", "--json"]


def test_agent_reach_provider_retries_retryable_reads_once():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="HTTP 404 not_found")
        return subprocess.CompletedProcess(args, 0, stdout='{"data":[{"id":"1","text":"found"}]}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner, retry_delay_seconds=0)

    result = provider.search("vellum", max_results=1)

    assert result[0]["text"] == "found"
    assert len(calls) == 2


def test_agent_reach_provider_never_retries_mutations():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="HTTP 429 rate limited")

    provider = AgentReachXProvider(runner=fake_runner, retry_delay_seconds=0)

    with pytest.raises(AgentReachCommandError, match="429"):
        provider.post_tweet("one post only")

    assert len(calls) == 1


def test_agent_reach_provider_serializes_cli_processes_across_instances():
    active = 0
    max_active = 0
    guard = threading.Lock()

    def fake_runner(args, **_kwargs):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with guard:
            active -= 1
        return subprocess.CompletedProcess(args, 0, stdout='{"data":[]}', stderr="")

    first = AgentReachXProvider(runner=fake_runner)
    second = AgentReachXProvider(runner=fake_runner)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda provider: provider.timeline(1), (first, second)))

    assert max_active == 1


def test_agent_reach_provider_reports_capability_health_without_claiming_edit_support(monkeypatch):
    provider = AgentReachXProvider(runner=lambda *_args, **_kwargs: None, retry_delay_seconds=0)
    monkeypatch.setattr(
        provider,
        "status",
        lambda: PluginStatus(
            id="agent-reach",
            name="Agent-Reach",
            type="connector",
            category="Connectors",
            configured=True,
            status="ready",
        ),
    )
    monkeypatch.setattr(provider, "_twitter_version", lambda: "0.8.6")
    monkeypatch.setattr(
        provider,
        "search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AgentReachCommandError("HTTP 404")),
    )

    health = provider.health(probe_search=True)

    assert health["status"] == "degraded"
    assert health["twitter_cli"]["version"] == "0.8.6"
    assert health["capabilities"]["search"]["status"] == "degraded"
    assert health["capabilities"]["edit"]["status"] == "unsupported"
    assert health["capabilities"]["post"]["automatic_retries"] == 0


def test_agent_reach_provider_exposes_supported_confirmation_safe_commands():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"ok":true}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner)
    provider.bookmark("123")
    provider.unbookmark("123")
    provider.unlike("123")
    provider.unrepost("123")
    provider.quote("123", "comment")
    provider.follow("@openai")
    provider.unfollow("openai")

    assert calls == [
        ["twitter", "bookmark", "123", "--json"],
        ["twitter", "unbookmark", "123", "--json"],
        ["twitter", "unlike", "123", "--json"],
        ["twitter", "unretweet", "123", "--json"],
        ["twitter", "quote", "123", "comment", "--json"],
        ["twitter", "follow", "openai", "--json"],
        ["twitter", "unfollow", "openai", "--json"],
    ]


def test_agent_reach_provider_marks_outdated_twitter_cli_search_degraded(monkeypatch):
    provider = AgentReachXProvider(runner=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        provider,
        "status",
        lambda: PluginStatus(
            id="agent-reach",
            name="Agent-Reach",
            type="connector",
            category="Connectors",
            configured=True,
            status="ready",
        ),
    )
    monkeypatch.setattr(provider, "_twitter_version", lambda: "0.8.5")

    def fail_if_searched(*_args, **_kwargs):
        raise AssertionError("outdated twitter-cli should fail health before live search")

    monkeypatch.setattr(provider, "search", fail_if_searched)

    health = provider.health(probe_search=True)

    assert health["status"] == "degraded"
    assert health["twitter_cli"] == {
        "version": "0.8.5",
        "minimum_version": "0.8.6",
        "version_supported": False,
    }
    assert health["capabilities"]["search"]["status"] == "degraded"
