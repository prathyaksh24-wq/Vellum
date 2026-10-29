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


def test_available_uses_configured_credentials_without_network_status_preflight(monkeypatch):
    monkeypatch.setattr(
        "agent.tools.capabilities.agent_reach_x_provider.shutil.which",
        lambda name: f"C:/bin/{name}.exe",
    )
    provider = AgentReachXProvider()
    monkeypatch.setattr(
        provider,
        "_twitter_subprocess_env",
        lambda: {"TWITTER_AUTH_TOKEN": "configured", "TWITTER_CT0": "configured"},
    )
    monkeypatch.setattr(
        provider,
        "_twitter_status",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("network preflight must not run")),
    )

    assert provider.available() is True
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
        return subprocess.CompletedProcess(args, 0, stdout='{"id":"123","text":"hello"}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner)

    result = provider.post_tweet("hello")

    assert calls[0] == ["twitter", "post", "hello", "--json"]
    assert result["id"] == "123"
    assert result["verification"] == "read_back"
    assert calls[1] == ["twitter", "tweet", "123", "--json"]


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
        return subprocess.CompletedProcess(args, 0, stdout='{"ok":true,"id":"123","text":"reply text"}', stderr="")

    provider = AgentReachXProvider(runner=fake_runner)

    provider.reply("123", "reply text")
    provider.like("123")
    provider.repost("123")
    provider.delete("123")

    assert calls[0] == ["twitter", "reply", "123", "reply text", "--json"]
    assert calls[1] == ["twitter", "tweet", "123", "--json"]
    assert calls[2] == ["twitter", "like", "123", "--json"]
    assert calls[3] == ["twitter", "retweet", "123", "--json"]
    assert calls[4] == ["twitter", "delete", "123", "--yes", "--json"]


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
    monkeypatch.setattr(provider, "_twitter_version", lambda: "0.8.5")
    monkeypatch.setattr(
        provider,
        "search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AgentReachCommandError("HTTP 404")),
    )

    health = provider.health(probe_search=True)

    assert health["status"] == "degraded"
    assert health["twitter_cli"]["version"] == "0.8.5"
    assert health["capabilities"]["search"]["status"] == "degraded"
    assert health["capabilities"]["edit"]["status"] == "unsupported"
    assert health["capabilities"]["post"]["automatic_retries"] == 0


def test_agent_reach_provider_exposes_supported_confirmation_safe_commands():
    calls = []

    def fake_runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"ok":true,"id":"456","text":"comment"}', stderr="")

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
        ["twitter", "tweet", "456", "--json"],
        ["twitter", "follow", "openai", "--json"],
        ["twitter", "unfollow", "openai", "--json"],
    ]


def test_agent_reach_provider_configures_explicit_cookie_export_through_stdin():
    calls = []

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs.get("input")))
        if args[0] == "agent-reach":
            return subprocess.CompletedProcess(args, 0, stdout="saved", stderr="")
        if "--json" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"data":{"authenticated":true,"user":{"username":"vellum"}}}',
                stderr="",
            )
        return subprocess.CompletedProcess(args, 0, stdout="authenticated: true", stderr="")

    provider = AgentReachXProvider(runner=fake_runner)
    result = provider.configure_cookie_export("auth_token=secret; ct0=csrf")

    assert result["configured"] is True
    assert result["account"]["username"] == "vellum"
    assert calls[0] == (
        [
            "agent-reach",
            "configure",
            "twitter-cookies",
            "--stdin",
            "--sync-legacy-twitter",
        ],
        "secret csrf",
    )


def test_agent_reach_provider_passes_saved_agent_reach_credentials_to_twitter_child(monkeypatch):
    calls = []

    class FakeConfig:
        def __init__(self, *, read_only):
            assert read_only is True

        def get(self, key):
            return {"twitter_auth_token": "saved-auth", "twitter_ct0": "saved-ct0"}.get(key)

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout='{"data":[]}', stderr="")

    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    monkeypatch.setattr(
        "agent.tools.capabilities.agent_reach_x_provider.AgentReachConfig",
        FakeConfig,
    )
    provider = AgentReachXProvider(runner=fake_runner)

    provider.timeline(max_results=1)

    child_env = calls[0][1]["env"]
    assert child_env["TWITTER_AUTH_TOKEN"] == "saved-auth"
    assert child_env["TWITTER_CT0"] == "saved-ct0"


def test_agent_reach_provider_normalizes_cookie_editor_json_before_subprocess():
    calls = []

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs.get("input")))
        if args[0] == "agent-reach":
            return subprocess.CompletedProcess(args, 0, stdout="saved", stderr="")
        if "--json" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='{"data":{"authenticated":true,"user":{"username":"vellum"}}}',
                stderr="",
            )
        return subprocess.CompletedProcess(args, 0, stdout="authenticated: true", stderr="")

    cookie_json = """[
        {"domain": ".x.com", "name": "guest_id", "value": "unused"},
        {"domain": ".x.com", "name": "auth_token", "value": "auth-value"},
        {"domain": ".x.com", "name": "ct0", "value": "csrf-value"}
    ]"""
    provider = AgentReachXProvider(runner=fake_runner)

    result = provider.configure_cookie_export(cookie_json)

    assert result["configured"] is True
    assert calls[0][1] == "auth-value csrf-value"
    assert "guest_id" not in calls[0][1]
    assert cookie_json != calls[0][1]


def test_agent_reach_provider_rejects_cookie_editor_json_missing_required_cookie():
    calls = []
    provider = AgentReachXProvider(runner=lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(AgentReachCommandError, match="auth_token and ct0") as exc:
        provider.configure_cookie_export(
            '[{"domain":".x.com","name":"auth_token","value":"secret-value"}]'
        )

    assert "secret-value" not in str(exc.value)
    assert calls == []


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
    monkeypatch.setattr(provider, "_twitter_version", lambda: "0.8.4")

    def fail_if_searched(*_args, **_kwargs):
        raise AssertionError("outdated twitter-cli should fail health before live search")

    monkeypatch.setattr(provider, "search", fail_if_searched)

    health = provider.health(probe_search=True)

    assert health["status"] == "degraded"
    assert health["twitter_cli"] == {
        "version": "0.8.4",
            "minimum_version": "0.8.6",
        "version_supported": False,
    }
    assert health["capabilities"]["search"]["status"] == "degraded"


def test_write_error_uses_structured_api_failure_instead_of_startup_warning():
    calls = []
    def fake_runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout='{"error":{"message":"Repost rejected by X (code 123)."}}', stderr="WARNING: ClientTransaction unavailable")
    provider = AgentReachXProvider(runner=fake_runner)
    with pytest.raises(AgentReachCommandError, match="Repost rejected by X"):
        provider.repost("1234567890123456789")
    assert len(calls) == 1
