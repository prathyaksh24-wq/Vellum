import asyncio
from types import SimpleNamespace

import pytest

from agent.mcp import apify_tools, filesystem_tools
from agent.mcp.client import McpToolRequest, run_tools_async


class AsyncPairContext:
    async def __aenter__(self):
        return "read", "write"

    async def __aexit__(self, exc_type, exc, tb):
        return False


class AsyncStreamableHttpContext:
    async def __aenter__(self):
        return "read", "write", lambda: "test-session"

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, *args, tools=None, text=""):
        self.tools = tools or []
        self.text = text
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in self.tools])

    async def call_tool(self, name, params):
        self.calls.append((name, params))
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


def test_filesystem_tool_lists_vault(monkeypatch):
    fake_session = FakeSession(tools=["list_directory"], text="Sports\nBooks")
    monkeypatch.setattr(filesystem_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(filesystem_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(filesystem_tools.run_tool_async({"query": "show me files"}))

    assert result == "Sports\nBooks"
    assert fake_session.calls[0][0] == "list_directory"
    assert "vault" in fake_session.calls[0][1]["path"].casefold()


def test_filesystem_tool_rejects_paths_outside_vault():
    with pytest.raises(ValueError, match="inside the Obsidian vault"):
        filesystem_tools._resolve_vault_path(filesystem_tools.Path("/tmp/outside.md"))


def test_apify_sanitizes_urls_asins_and_pii():
    raw = "Product ASIN B0ABCDEF12 link https://amazon.com/dp/B0ABCDEF12 contact me@example.com"

    clean = apify_tools.sanitize_apify_result(raw)

    assert "https://amazon.com" not in clean
    assert "B0ABCDEF12" not in clean
    assert "me@example.com" not in clean
    assert "[URL_REDACTED]" in clean
    assert "[ASIN_REDACTED]" in clean
    assert "[EMAIL_1]" in clean


def test_apify_tool_calls_mcp_and_returns_sanitized_result(monkeypatch, tmp_path):
    fake_session = FakeSession(
        text="ASIN B0ABCDEF12 https://amazon.com/dp/B0ABCDEF12 seller@example.com"
    )
    seen = {}

    def fake_streamablehttp_client(url, headers=None, timeout=None, sse_read_timeout=None):
        seen.update(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "sse_read_timeout": sse_read_timeout,
            }
        )
        return AsyncStreamableHttpContext()

    monkeypatch.setattr(apify_tools, "streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr(apify_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(apify_tools.run_tool_async({"query": "latest amazon price", "max_items": 2}))

    assert "B0ABCDEF12" not in result
    assert "seller@example.com" not in result
    assert fake_session.calls[0][0] == apify_tools.APIFY_CALL_ACTOR_TOOL
    assert fake_session.calls[0][1]["input"]["maxItems"] == 2
    assert fake_session.calls[0][1]["callOptions"]["timeout"] == 300
    assert seen["url"] == "https://mcp.apify.com"
    assert seen["headers"]["Authorization"].startswith("Bearer ")
    assert seen["timeout"] == 300
    assert seen["sse_read_timeout"] == 300


def test_multiple_mcp_servers_can_run_concurrently(monkeypatch):
    events = []

    async def fake_filesystem(params):
        events.append("filesystem-start")
        await asyncio.sleep(0.02)
        events.append("filesystem-end")
        return "filesystem-ok"

    async def fake_apify(params):
        events.append("apify-start")
        await asyncio.sleep(0.02)
        events.append("apify-end")
        return "apify-ok"

    monkeypatch.setattr("agent.mcp.client.SERVER_RUNNERS", {
        "filesystem": fake_filesystem,
        "apify_amazon": fake_apify,
    })

    results = asyncio.run(
        run_tools_async(
            [
                McpToolRequest("filesystem", {"query": "show files"}),
                McpToolRequest("apify_amazon", {"query": "amazon notebook price"}),
            ]
        )
    )

    assert [item.result for item in results] == ["filesystem-ok", "apify-ok"]
    assert events[:2] == ["filesystem-start", "apify-start"]
