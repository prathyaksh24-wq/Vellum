"""Generic, policy-gated access to MCP connectors owned by enabled plugins."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import re
from typing import Any

from langchain_core.tools import tool

from agent.mcp.plugin_runtime import PluginMcpRuntime, PluginMcpRuntimeError
from agent.plugins.registry import get_plugin_registry


def _runtime() -> PluginMcpRuntime:
    return PluginMcpRuntime(get_plugin_registry())


@tool
def plugins_list(query: str = "") -> str:
    """List Vellum's actual installed plugins, enablement and locally saved connection state. Optional query filters by name or ID. Does not probe providers or load remote tool schemas. Use before claiming an integration is missing."""
    registry = get_plugin_registry()
    with registry.read_snapshot():
        records = registry.catalog()
        if query.strip():
            words = query.casefold().split()
            records = [item for item in records if all(word in (item['id'] + ' ' + item['name']).casefold() for word in words)]
        records = [item for item in records if item.get('installed') is not False]
        from agent.plugins.catalog import runtime_statuses
        statuses = {item['id']: item for item in runtime_statuses(plugin_ids={item['id'] for item in records})}
        plugins = []
        for item in records:
            status = statuses.get(item['id'])
            connection = (status or {}).get('metadata', {}).get('connection', {})
            plugins.append({
                'id': item['id'], 'name': item['name'], 'enabled': item['enabled'],
                'description': item['description'],
                'connection_state': connection.get('status') or (status or {}).get('status') or 'not_checked',
                'connected': connection.get('connected'),
                'message': (status or {}).get('notes', ''),
                'tool_count': len((status or {}).get('tools', item.get('tools', []))),
                'tools': [name for name in (status or {}).get('tools', item.get('tools', []))
                          if name.endswith(('_mcp_catalog', '_mcp_describe', '_mcp_read'))][:3]
                         or item.get('tools', [])[:3],
                'connectors': [str(row.get('name') or row.get('id') or '') for row in item.get('mcp_connectors', [])],
                'skills': [row['id'] for row in item.get('skills', [])],
            })
        return json.dumps({'plugins': plugins, 'connection_evidence': 'local_saved_state_not_live_probe'}, ensure_ascii=False)


def requested_plugins(query: str, *, references: list[dict] = ()) -> list[dict]:
    """Resolve user-selected or explicitly named identities against PluginRegistry."""
    registry = get_plugin_registry()
    requested = {str(ref.get('owner_plugin_id') or ref.get('id') or '')
                 for ref in references if ref.get('kind') in {'plugin', 'app', 'mcp'}}
    with registry.read_snapshot():
        records = registry.catalog()
    result = []
    for item in records:
        # Plain words such as 'browser' are also normal request vocabulary.
        # An explicit @reference still resolves all registered plugin IDs.
        aliases = {item['name'].casefold(), item['id'].replace('_', ' ').replace('-', ' ').casefold()}
        named = any(re.search(r'(?<![\w])' + re.escape(alias) + r'(?![\w])', query, re.I)
                    for alias in aliases if len(alias) >= 3 and alias not in {'browser', 'google', 'memory orchestrator'})
        if item['id'] in requested or named:
            result.append(item)
    return result[:6]


def current_references(messages) -> list[dict]:
    """Only the current user's structured selection can seed plugin routing."""
    for message in reversed(messages):
        if getattr(message, 'type', '') not in {'human', 'user'}:
            continue
        content = getattr(message, 'content', '')
        refs = []
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get('type') != 'vellum_attachment_text':
                continue
            text = str(part.get('text') or '')
            if not text.startswith('User-selected reference metadata ('):
                continue
            try:
                value = json.loads(text.split('\n', 1)[1])
            except (ValueError, IndexError):
                continue
            if isinstance(value, dict):
                refs.append(value)
        return refs
    return []


def plugin_route_names(query: str, messages, available: set[str]) -> tuple[list[dict], list[str]]:
    requested = requested_plugins(query, references=current_references(messages))
    names = []
    for item in requested:
        if not item['enabled'] or item.get('installed') is False:
            continue
        prefix = item['id'].replace('-', '_')
        bridge = [prefix + '_mcp_' + suffix for suffix in ('catalog', 'describe', 'read')]
        chosen = [name for name in bridge if name in available]
        if not chosen:
            chosen = [name for name in item.get('tools', []) if name in available and name not in {'plugin_mcp'}][:2]
        if not chosen and item.get('mcp_connectors') and 'plugin_mcp' in available:
            chosen = ['plugin_mcp']
        names.extend(chosen)
    return requested, list(dict.fromkeys(names))


def explicit_plugin_web_error(query: str, messages, call) -> str | None:
    """Keep explicit integration requests from silently becoming web searches."""
    from agent.tools.tool_search import unwrap_bridge_call
    name, _ = unwrap_bridge_call(call.get('name', ''), call.get('args') or {})
    if name != 'web_search' or re.search(r'\b(?:web|internet|online)\b', query, re.I):
        return None
    requested = requested_plugins(query, references=current_references(messages))
    if not requested:
        return None
    names = ', '.join(item['name'] for item in requested)
    return (f'This request explicitly selected {names}. Use its provider tools first. '
            'If unavailable, report the actual connection/catalog error and ask before substituting web search.')


@tool
def plugin_mcp(
    action: str,
    plugin_id: str = "",
    connector: str = "",
    tool_name: str = "",
    arguments: dict[str, Any] | None = None,
    approval_id: str = "",
) -> str:
    """Use an MCP connector contributed by an enabled plugin.

    Actions:
      - list_connectors: list enabled plugin-owned MCP connectors and whether
        their required environment configuration is present.
      - list_tools: plugin_id=<plugin>, connector=<name>. Inspect the connector's
        live MCP tools and read-only annotations.
      - call: plugin_id=<plugin>, connector=<name>, tool_name=<tool>,
        arguments=<object>. Read-only annotated tools can run automatically.
        Any tool not explicitly marked read-only requires a locally approved,
        operation-bound approval_id.

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
                    approval_id=approval_id,
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
