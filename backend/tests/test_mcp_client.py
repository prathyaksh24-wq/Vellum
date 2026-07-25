import asyncio

from agent.mcp import client
from agent.mcp.results import UNREACHABLE


def test_mcp_client_normalizes_and_bounds_results(monkeypatch) -> None:
    async def large_result(params):
        return "useful\x00 result\n" + ("detail\n" * 3_000)

    monkeypatch.setitem(client.SERVER_RUNNERS, "test-large", large_result)

    result = asyncio.run(
        client.run_tools_async([{"server": "test-large", "params": {}}])
    )[0]

    assert result.ok is True
    assert "\x00" not in result.result
    assert result.result.startswith("useful result")
    assert result.result.endswith("[MCP result truncated locally]")
    assert len(result.result) < 12_100


def test_mcp_client_preserves_failure_words_inside_real_content(monkeypatch) -> None:
    async def real_result(params):
        return "The build failed: missing dependency. This is source content."

    monkeypatch.setitem(client.SERVER_RUNNERS, "test-content", real_result)

    result = asyncio.run(
        client.run_tools_async([{"server": "test-content", "params": {}}])
    )[0]

    assert result.ok is True
    assert result.result.startswith("The build failed:")

def test_mcp_client_hides_adapter_failure_details(monkeypatch) -> None:
    async def failed_result(params):
        raise RuntimeError("token=secret-value")

    monkeypatch.setitem(client.SERVER_RUNNERS, "test-failure", failed_result)

    result = asyncio.run(
        client.run_tools_async([{"server": "test-failure", "params": {}}])
    )[0]

    assert result.ok is False
    assert result.result == UNREACHABLE
    assert "secret-value" not in result.result


def test_mcp_client_marks_legacy_failure_strings_unreachable(monkeypatch) -> None:
    async def legacy_failure(params):
        return "Context7 MCP failed: internal connection details"

    monkeypatch.setitem(client.SERVER_RUNNERS, "test-legacy", legacy_failure)

    result = asyncio.run(
        client.run_tools_async([{"server": "test-legacy", "params": {}}])
    )[0]

    assert result.ok is False
    assert result.result == UNREACHABLE