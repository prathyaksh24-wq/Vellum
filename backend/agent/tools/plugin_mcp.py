"""Generic, policy-gated access to MCP connectors owned by enabled plugins."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any

from langchain_core.tools import tool

from agent.mcp.plugin_runtime import PluginMcpRuntime, PluginMcpRuntimeError
from agent.plugins.registry import get_plugin_registry


def _runtime() -> PluginMcpRuntime:
    return PluginMcpRuntime(get_plugin_registry())


@tool
def plugin_mcp(
    action: str,
    plugin_id: str = "",
    connector: str = "",
    tool_name: str = "",
    arguments: dict[str, Any] | None = None,
    confirm: bool = False,
) -> str:
    """Use an MCP connector contributed by an enabled plugin.

    Actions:
      - list_connectors: list enabled plugin-owned MCP connectors and whether
        their required environment configuration is present.
      - list_tools: plugin_id=<plugin>, connector=<name>. Inspect the connector's
        live MCP tools and read-only annotations.
      - call: plugin_id=<plugin>, connector=<name>, tool_name=<tool>,
        arguments=<object>. Read-only annotated tools can run automatically.
        Any tool not explicitly marked read-only requires confirm=true.

    Never put credentials in arguments. Connector authentication is resolved
    locally from its manifest-declared environment variables.
    """

    normalized = action.strip().casefold().replace("-", "_")
    runtime = _runtime()
    try:
        if normalized == "list_connectors":
            return json.dumps(
                {"connectors": [item.public() for item in runtime.connectors()]},
                ensure_ascii=False,
            )
        if normalized == "list_tools":
            tools = _run_async(runtime.list_tools(plugin_id, connector))
            return json.dumps(
                {"plugin_id": plugin_id, "connector": connector, "tools": tools},
                ensure_ascii=False,
            )
        if normalized == "call":
            return _run_async(
                runtime.call_tool(
                    plugin_id,
                    connector,
                    tool_name,
                    dict(arguments or {}),
                    confirm=confirm,
                )
            )
        return "Unsupported plugin MCP action."
    except PluginMcpRuntimeError as exc:
        return str(exc)
    except Exception:
        return "Unreachable."


def _run_async(operation):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(operation)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, operation).result()
