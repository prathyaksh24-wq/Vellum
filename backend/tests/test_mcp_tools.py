import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest

from agent.tools import browser as browser_tools
from agent.mcp import apify_tools, filesystem_tools, github_tools, obsidian_tools, playwright_tools
from agent.mcp.client import McpToolRequest, run_tools_async


@pytest.fixture(autouse=True)
def close_playwright_client_after_test():
    yield
    asyncio.run(playwright_tools.shutdown_async())


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


def test_playwright_navigate_calls_core_mcp_tool(monkeypatch):
    fake_session = FakeSession(tools=["browser_navigate"], text='- heading "Example" [level=1]')
    seen = {}

    def fake_stdio_client(params):
        seen["params"] = params
        return AsyncPairContext()

    monkeypatch.setattr(playwright_tools, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(playwright_tools.run_tool_async({"action": "navigate", "url": "https://example.com"}))

    assert 'heading "Example"' in result
    assert fake_session.calls[0] == ("browser_navigate", {"url": "https://example.com"})
    assert seen["params"].command == "npx"
    assert "@playwright/mcp@latest" in seen["params"].args
    assert "--isolated" in seen["params"].args


def test_playwright_blocks_mutating_actions_by_default(monkeypatch):
    monkeypatch.setattr(playwright_tools, "_mutations_allowed", lambda: False)

    result = asyncio.run(playwright_tools.run_tool_async({"action": "click", "ref": "e5"}))

    assert "requires PLAYWRIGHT_MCP_ALLOW_MUTATIONS=true" in result


def test_playwright_click_when_mutations_are_allowed(monkeypatch):
    fake_session = FakeSession(tools=["browser_click"], text="clicked")
    monkeypatch.setattr(playwright_tools, "_mutations_allowed", lambda: True)
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(playwright_tools.run_tool_async({"action": "click", "ref": "e5", "element": "Search"}))

    assert result == "clicked"
    assert fake_session.calls[0] == ("browser_click", {"target": "e5", "element": "Search"})


def test_playwright_click_accepts_target_alias(monkeypatch):
    fake_session = FakeSession(tools=["browser_click"], text="clicked")
    monkeypatch.setattr(playwright_tools, "_mutations_allowed", lambda: True)
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(playwright_tools.run_tool_async({"action": "click", "target": "button[name=Go]"}))

    assert result == "clicked"
    assert fake_session.calls[0] == ("browser_click", {"target": "button[name=Go]"})


def test_playwright_screenshot_and_resize_map_to_mcp_tools(monkeypatch):
    fake_session = FakeSession(tools=["browser_take_screenshot", "browser_resize"], text="ok")
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    screenshot = asyncio.run(
        playwright_tools.run_tool_async(
            {
                "action": "screenshot",
                "target": "main",
                "filename": "main.png",
                "full_page": True,
            }
        )
    )
    resize = asyncio.run(playwright_tools.run_tool_async({"action": "resize", "width": 1280, "height": 720}))

    assert screenshot == "ok"
    assert resize == "ok"
    assert fake_session.calls == [
        (
            "browser_take_screenshot",
            {"type": "png", "target": "main", "filename": "main.png", "fullPage": True},
        ),
        ("browser_resize", {"width": 1280, "height": 720}),
    ]


def test_playwright_drag_and_fill_form_when_mutations_allowed(monkeypatch):
    fake_session = FakeSession(tools=["browser_drag", "browser_fill_form"], text="ok")
    monkeypatch.setattr(playwright_tools, "_mutations_allowed", lambda: True)
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    drag = asyncio.run(
        playwright_tools.run_tool_async(
            {
                "action": "drag",
                "start_target": "source",
                "end_target": "dest",
                "start_element": "Source",
                "end_element": "Destination",
            }
        )
    )
    fill = asyncio.run(
        playwright_tools.run_tool_async(
            {
                "action": "fill_form",
                "fields": [
                    {"target": "input[name=q]", "name": "Query", "type": "textbox", "value": "Vellum"}
                ],
            }
        )
    )

    assert drag == "ok"
    assert fill == "ok"
    assert fake_session.calls == [
        (
            "browser_drag",
            {
                "startTarget": "source",
                "endTarget": "dest",
                "startElement": "Source",
                "endElement": "Destination",
            },
        ),
        (
            "browser_fill_form",
            {"fields": [{"target": "input[name=q]", "name": "Query", "type": "textbox", "value": "Vellum"}]},
        ),
    ]


def test_playwright_reuses_one_mcp_session_across_browser_actions(monkeypatch):
    fake_session = FakeSession(tools=["browser_navigate", "browser_snapshot"], text="ok")
    starts = 0

    class CountingAsyncPairContext:
        async def __aenter__(self):
            nonlocal starts
            starts += 1
            return "read", "write"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: CountingAsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    try:
        first = asyncio.run(playwright_tools.run_tool_async({"action": "navigate", "url": "https://example.com"}))
        second = asyncio.run(playwright_tools.run_tool_async({"action": "snapshot"}))
    finally:
        shutdown = getattr(playwright_tools, "shutdown_async", None)
        if shutdown is not None:
            asyncio.run(shutdown())

    assert first == "ok"
    assert second == "ok"
    assert starts == 1
    assert fake_session.calls == [
        ("browser_navigate", {"url": "https://example.com"}),
        ("browser_snapshot", {}),
    ]


def test_playwright_client_recreates_asyncio_lock_per_event_loop():
    client = playwright_tools._PlaywrightMcpClient()

    async def lock_id():
        return id(client._lock_for_current_loop())

    first = asyncio.run(lock_id())
    second = asyncio.run(lock_id())

    assert first != second


def test_playwright_worker_shutdown_after_transport_error(monkeypatch):
    events = []

    class FakeWorker:
        def submit(self, coro):
            coro.close()
            future = concurrent.futures.Future()
            future.set_exception(RuntimeError("asyncio event loop mismatch"))
            return future

        async def shutdown_async(self):
            events.append("shutdown")

    monkeypatch.setattr(playwright_tools, "_worker", FakeWorker())

    result = asyncio.run(playwright_tools.run_tool_async({"action": "snapshot"}))

    assert "Playwright MCP failed" in result
    assert events == ["shutdown"]


def test_playwright_close_uses_short_timeout_and_resets_session(monkeypatch):
    fake_session = FakeSession(tools=["browser_close"], text="closed")
    closed = []

    async def never_return(name, params):
        await asyncio.Future()

    async def fake_close():
        closed.append("close")

    fake_session.call_tool = never_return
    monkeypatch.setattr(playwright_tools, "_mcp_action_timeout_seconds", lambda action: 0.01)
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    client = playwright_tools._PlaywrightMcpClient()
    monkeypatch.setattr(client, "close", fake_close)

    result = asyncio.run(client.call({"action": "close"}))

    assert "timed out" in result
    assert closed == ["close"]


def test_playwright_tabs_new_maps_to_browser_tabs(monkeypatch):
    fake_session = FakeSession(tools=["browser_tabs"], text="tab opened")
    monkeypatch.setattr(playwright_tools, "stdio_client", lambda params: AsyncPairContext())
    monkeypatch.setattr(playwright_tools, "ClientSession", lambda read, write: fake_session)

    try:
        result = asyncio.run(
            playwright_tools.run_tool_async(
                {"action": "tabs", "tab_action": "new", "url": "https://example.com/docs"}
            )
        )
    finally:
        shutdown = getattr(playwright_tools, "shutdown_async", None)
        if shutdown is not None:
            asyncio.run(shutdown())

    assert result == "tab opened"
    assert fake_session.calls[0] == (
        "browser_tabs",
        {"action": "new", "url": "https://example.com/docs"},
    )


def test_browser_tabs_tool_calls_playwright_tabs(monkeypatch):
    calls = []
    monkeypatch.setattr(browser_tools, "playwright_run", lambda params: calls.append(params) or "tabs")

    result = browser_tools.browser_tabs.invoke({"action": "new", "url": "https://example.com/docs"})

    assert result == "tabs"
    assert calls == [{"action": "tabs", "tab_action": "new", "index": "", "url": "https://example.com/docs"}]


def test_browser_click_and_type_tools_call_playwright_actions(monkeypatch):
    calls = []
    monkeypatch.setattr(browser_tools, "playwright_run", lambda params: calls.append(params) or "ok")

    click_result = browser_tools.browser_click.invoke({"ref": "e5", "element": "Search"})
    type_result = browser_tools.browser_type.invoke(
        {"ref": "e6", "element": "Search input", "text": "vellum", "submit": True}
    )

    assert click_result == "ok"
    assert type_result == "ok"
    assert calls == [
        {"action": "click", "ref": "e5", "element": "Search"},
        {"action": "type", "ref": "e6", "element": "Search input", "text": "vellum", "submit": True},
    ]


def test_github_search_repositories_calls_remote_mcp(monkeypatch):
    fake_session = FakeSession(tools=["search_repositories"], text="repo result")
    seen = {}

    def fake_streamablehttp_client(url, headers=None, timeout=None, sse_read_timeout=None):
        seen.update({"url": url, "headers": headers, "timeout": timeout, "sse_read_timeout": sse_read_timeout})
        return AsyncStreamableHttpContext()

    monkeypatch.setattr(github_tools, "_github_token", lambda: "ghp_test")
    monkeypatch.setattr(github_tools, "streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr(github_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(github_tools.run_tool_async({"action": "search_repositories", "query": "vellum"}))

    assert result == "repo result"
    assert fake_session.calls[0] == ("search_repositories", {"query": "vellum"})
    assert seen["url"] == "https://api.githubcopilot.com/mcp/"
    assert seen["headers"]["Authorization"] == "Bearer ghp_test"


def test_github_blocks_write_tools(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_token", lambda: "ghp_test")

    result = asyncio.run(github_tools.run_tool_async({"action": "create_or_update_file"}))

    assert "requires GITHUB_MCP_ALLOW_WRITES=true" in result


def test_github_create_repository_when_writes_allowed(monkeypatch):
    fake_session = FakeSession(tools=["create_repository"], text="created")
    monkeypatch.setattr(github_tools, "_github_token", lambda: "ghp_test")
    monkeypatch.setattr(github_tools, "_writes_allowed", lambda: True)
    monkeypatch.setattr(github_tools, "streamablehttp_client", lambda *args, **kwargs: AsyncStreamableHttpContext())
    monkeypatch.setattr(github_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(
        github_tools.run_tool_async(
            {
                "action": "create_repository",
                "name": "vellum-test",
                "description": "test repo",
                "private": True,
                "auto_init": True,
            }
        )
    )

    assert result == "created"
    assert fake_session.calls[0] == (
        "create_repository",
        {"name": "vellum-test", "description": "test repo", "private": True, "autoInit": True},
    )


def test_github_delete_repository_requires_destructive_flag(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_token", lambda: "ghp_test")
    monkeypatch.setattr(github_tools, "_writes_allowed", lambda: True)
    monkeypatch.setattr(github_tools, "_destructive_allowed", lambda: False)

    result = asyncio.run(github_tools.run_tool_async({"action": "delete_repository", "owner": "me", "repo": "old"}))

    assert "requires GITHUB_MCP_ALLOW_DESTRUCTIVE=true" in result


def test_github_delete_repository_uses_rest_when_destructive_allowed(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 204
        text = ""

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def delete(self, url, headers=None):
            seen["url"] = url
            seen["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(github_tools, "_github_token", lambda: "ghp_test")
    monkeypatch.setattr(github_tools, "_writes_allowed", lambda: True)
    monkeypatch.setattr(github_tools, "_destructive_allowed", lambda: True)
    monkeypatch.setattr(github_tools.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(github_tools.run_tool_async({"action": "delete_repository", "owner": "me", "repo": "old"}))

    assert result == "GitHub repository deleted: me/old."
    assert seen["url"] == "https://api.github.com/repos/me/old"
    assert seen["headers"]["Authorization"] == "Bearer ghp_test"


def test_github_requires_token(monkeypatch):
    monkeypatch.setattr(github_tools, "_github_token", lambda: "")

    result = asyncio.run(github_tools.run_tool_async({"action": "search_repositories", "query": "vellum"}))

    assert "GITHUB_MCP_TOKEN" in result


def test_github_token_reads_pat_from_settings(monkeypatch):
    monkeypatch.setattr(github_tools, "get_settings", lambda: SimpleNamespace(github_mcp_token="", github_pat="ghp_from_settings"))
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert github_tools._github_token() == "ghp_from_settings"


def test_obsidian_read_calls_local_mcp(monkeypatch):
    fake_session = FakeSession(tools=["vault_read"], text="# Note")
    seen = {}

    def fake_streamablehttp_client(url, headers=None, timeout=None, sse_read_timeout=None, httpx_client_factory=None):
        seen.update(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "sse_read_timeout": sse_read_timeout,
                "httpx_client_factory": httpx_client_factory,
            }
        )
        return AsyncStreamableHttpContext()

    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "obsidian-key")
    monkeypatch.setattr(obsidian_tools, "_use_stream_transport", lambda: True)
    monkeypatch.setattr(obsidian_tools, "streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr(obsidian_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(obsidian_tools.run_tool_async({"action": "read", "path": "Agent/Memories/test.md"}))

    assert result == "# Note"
    assert fake_session.calls[0] == ("vault_read", {"path": "Agent/Memories/test.md"})
    assert seen["url"] == "https://127.0.0.1:27124/mcp/"
    assert seen["headers"]["Authorization"] == "Bearer obsidian-key"
    assert seen["httpx_client_factory"] is not None


def test_obsidian_write_requires_write_flag(monkeypatch):
    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "obsidian-key")
    monkeypatch.setattr(obsidian_tools, "_writes_allowed", lambda: False)

    result = asyncio.run(obsidian_tools.run_tool_async({"action": "write", "path": "x.md", "content": "hello"}))

    assert "requires OBSIDIAN_MCP_ALLOW_WRITES=true" in result


def test_obsidian_append_when_writes_allowed(monkeypatch):
    fake_session = FakeSession(tools=["vault_append"], text="appended")
    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "obsidian-key")
    monkeypatch.setattr(obsidian_tools, "_writes_allowed", lambda: True)
    monkeypatch.setattr(obsidian_tools, "_use_stream_transport", lambda: True)
    monkeypatch.setattr(obsidian_tools, "streamablehttp_client", lambda *args, **kwargs: AsyncStreamableHttpContext())
    monkeypatch.setattr(obsidian_tools, "ClientSession", lambda read, write: fake_session)

    result = asyncio.run(
        obsidian_tools.run_tool_async(
            {"action": "append", "path": "Agent/Memories/test.md", "content": "\nhello"}
        )
    )

    assert result == "appended"
    assert fake_session.calls[0] == ("vault_append", {"path": "Agent/Memories/test.md", "content": "\nhello"})


def test_obsidian_delete_requires_destructive_flag(monkeypatch):
    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "obsidian-key")
    monkeypatch.setattr(obsidian_tools, "_writes_allowed", lambda: True)
    monkeypatch.setattr(obsidian_tools, "_destructive_allowed", lambda: False)

    result = asyncio.run(obsidian_tools.run_tool_async({"action": "delete", "path": "old.md"}))

    assert "requires OBSIDIAN_MCP_ALLOW_DESTRUCTIVE=true" in result


def test_obsidian_requires_api_key(monkeypatch):
    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "")

    result = asyncio.run(obsidian_tools.run_tool_async({"action": "list"}))

    assert "OBSIDIAN_API_KEY" in result


def test_obsidian_rest_list_fallback(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"files": ["Agent/", "X/"]}

        @property
        def text(self):
            return '{"files":["Agent/","X/"]}'

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            seen["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            seen["url"] = url
            seen["headers"] = headers
            seen["params"] = params
            return FakeResponse()

    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "obsidian-key")
    monkeypatch.setattr(obsidian_tools.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(obsidian_tools.run_rest_action_async({"action": "list"}))

    assert "Agent/" in result
    assert seen["url"] == "https://127.0.0.1:27124/vault/"
    assert seen["headers"]["Authorization"] == "Bearer obsidian-key"
    assert seen["client_kwargs"]["verify"] is False


def test_obsidian_rest_append_reads_then_writes(monkeypatch):
    calls = []

    class FakeReadResponse:
        status_code = 200
        text = "old"

    class FakeWriteResponse:
        status_code = 204
        text = ""

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append(("get", url, None))
            return FakeReadResponse()

        async def put(self, url, headers=None, content=None):
            calls.append(("put", url, content))
            return FakeWriteResponse()

    monkeypatch.setattr(obsidian_tools, "_obsidian_api_key", lambda: "obsidian-key")
    monkeypatch.setattr(obsidian_tools, "_writes_allowed", lambda: True)
    monkeypatch.setattr(obsidian_tools.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        obsidian_tools.run_rest_action_async(
            {"action": "append", "path": "Agent/test.md", "content": "\nnew"}
        )
    )

    assert result == "Obsidian REST append completed: Agent/test.md."
    assert calls == [
        ("get", "https://127.0.0.1:27124/vault/Agent/test.md", None),
        ("put", "https://127.0.0.1:27124/vault/Agent/test.md", "old\nnew"),
    ]


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

    async def fake_browser(params):
        return "browser-ok"

    async def fake_github(params):
        return "github-ok"

    async def fake_obsidian(params):
        return "obsidian-ok"

    monkeypatch.setattr("agent.mcp.client.SERVER_RUNNERS", {
        "filesystem": fake_filesystem,
        "apify_amazon": fake_apify,
        "playwright": fake_browser,
        "github": fake_github,
        "obsidian": fake_obsidian,
    })

    results = asyncio.run(
        run_tools_async(
            [
                McpToolRequest("filesystem", {"query": "show files"}),
                McpToolRequest("apify_amazon", {"query": "amazon notebook price"}),
                McpToolRequest("playwright", {"action": "snapshot"}),
                McpToolRequest("github", {"action": "search_repositories", "query": "vellum"}),
                McpToolRequest("obsidian", {"action": "list"}),
            ]
        )
    )

    assert [item.result for item in results] == ["filesystem-ok", "apify-ok", "browser-ok", "github-ok", "obsidian-ok"]
    assert events[:2] == ["filesystem-start", "apify-start"]
