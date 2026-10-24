import asyncio
import base64
from types import SimpleNamespace

import pytest
from agent.mcp import github_cli as cli, github_tools as github


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def command(monkeypatch):
    calls, responses = [], []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "gh.exe")
    async def process(executable, args, **kwargs):
        calls.append((executable, args, kwargs))
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(cli, "_process", process)
    return calls, responses


def test_cli_success_uses_fixed_host_and_returns_only_response_body(command):
    calls, responses = command
    responses.append((0, 'HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"id":1}'))
    assert run(cli.run("get_issue", {"owner": "org", "repo": "project", "issue_number": 1}, token="test", timeout=5)) == '{"id":1}'
    assert calls[0][1][0:4] == ["api", "--hostname", "github.com", "--include"]


@pytest.mark.parametrize("failure", [(1, ""), TimeoutError()])
def test_read_failure_can_fall_back(command, failure):
    command[1].append(failure)
    assert run(cli.run("list_issues", {"owner": "org", "repo": "project"}, token="test", timeout=5)) is None


@pytest.mark.parametrize("failure", [(1, ""), (1, "HTTP/2.0 502 Bad Gateway\n\n{}"), TimeoutError(), BrokenPipeError()])
def test_ambiguous_write_is_never_replayed(command, failure):
    command[1].append(failure)
    result = run(cli.run("create_issue", {"owner": "org", "repo": "project", "title": "Test"}, token="test", timeout=5))
    assert "outcome is unknown" in result and "MCP was not called" in result


def test_definite_rejected_write_can_fall_back(command):
    command[1].append((1, "HTTP/2.0 403 Forbidden\n\n{}"))
    assert run(cli.run("create_issue", {"owner": "org", "repo": "project", "title": "Test"}, token="test", timeout=5)) is None


def test_secret_is_read_from_local_cli_without_remote_auth_probe(command):
    command[1].append((0, "credential-value\n"))
    assert run(cli.credential("", timeout=5)) == "credential-value"
    assert command[0][0][1] == ["auth", "token", "--hostname", "github.com"]


def test_existing_credential_is_reused_without_cli_probe(command):
    assert run(cli.credential("configured", timeout=5)) == "configured"
    assert command[0] == []


def test_file_content_matches_cli_rest_contract():
    method, path, body = cli.request_plan("create_or_update_file", {"owner": "org", "repo": "project", "path": "notes/a.md", "message": "Update", "content": "Hi"})
    assert method == "PUT" and path.endswith("/contents/notes/a.md")
    assert base64.b64decode(body["content"]) == b"Hi"


def test_permissions_are_checked_before_either_transport(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Transport executed before write authorization")
    monkeypatch.setattr(github, "cli_run", forbidden)
    monkeypatch.setattr(github, "_writes_allowed", lambda: False)
    assert "requires GITHUB_MCP_ALLOW_WRITES" in run(github.run_tool_async({"action": "create_issue", "title": "No"}))


def test_successful_cli_never_starts_mcp(monkeypatch):
    monkeypatch.setattr(github, "get_settings", lambda: SimpleNamespace(mcp_timeout_seconds=5))
    monkeypatch.setattr(github, "_github_token", lambda: "test")
    async def success(*args, **kwargs):
        return '{"id":1}'
    monkeypatch.setattr(github, "cli_run", success)
    monkeypatch.setattr(github, "streamablehttp_client", lambda *args, **kwargs: pytest.fail("MCP started"))
    assert run(github.run_tool_async({"action": "get_issue", "owner": "org", "repo": "project", "issue_number": 1})) == '{"id":1}'


def test_disabled_plugin_blocks_both_transports(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(github, "get_plugin_registry", lambda: SimpleNamespace(read_snapshot=nullcontext, contains=lambda _: True, is_enabled=lambda _: False))
    async def forbidden(*args, **kwargs):
        raise AssertionError("Disabled GitHub reached a transport")
    monkeypatch.setattr(github, "cli_run", forbidden)
    assert "disabled" in run(github.run_tool_async({"action": "search_repositories", "query": "test"}))
