"""Obsidian Local REST API MCP wrapper."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings

logger = logging.getLogger(__name__)

READ_ACTION_TO_TOOL = {
    "list": "vault_list",
    "vault_list": "vault_list",
    "read": "vault_read",
    "vault_read": "vault_read",
    "document_map": "vault_get_document_map",
    "vault_get_document_map": "vault_get_document_map",
    "active_file": "active_file_get_path",
    "active_file_get_path": "active_file_get_path",
    "periodic": "periodic_note_get_path",
    "periodic_note_get_path": "periodic_note_get_path",
    "search": "search_simple",
    "search_simple": "search_simple",
    "search_query": "search_query",
    "tags": "tag_list",
    "tag_list": "tag_list",
    "commands": "command_list",
    "command_list": "command_list",
}

WRITE_ACTION_TO_TOOL = {
    "write": "vault_write",
    "vault_write": "vault_write",
    "append": "vault_append",
    "vault_append": "vault_append",
    "patch": "vault_patch",
    "vault_patch": "vault_patch",
    "open": "open_file",
    "open_file": "open_file",
}

DESTRUCTIVE_ACTION_TO_TOOL = {
    "delete": "vault_delete",
    "vault_delete": "vault_delete",
}

COMMAND_ACTION_TO_TOOL = {
    "execute_command": "command_execute",
    "command_execute": "command_execute",
}

PARAM_KEYS = {
    "path",
    "query",
    "contextLength",
    "content",
    "operation",
    "target",
    "targetType",
    "targetScope",
    "period",
    "date",
    "commandId",
    "newLeaf",
}


def _obsidian_api_key() -> str:
    return get_settings().obsidian_api_key


def _obsidian_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_obsidian_api_key()}"}


def _obsidian_markdown_headers() -> dict[str, str]:
    headers = _obsidian_headers()
    headers["Content-Type"] = "text/markdown"
    return headers


def _writes_allowed() -> bool:
    return get_settings().obsidian_mcp_allow_writes


def _destructive_allowed() -> bool:
    return get_settings().obsidian_mcp_allow_destructive


def _commands_allowed() -> bool:
    return get_settings().obsidian_mcp_allow_commands


def _use_stream_transport() -> bool:
    return get_settings().obsidian_mcp_use_stream


def _httpx_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        verify=get_settings().obsidian_mcp_verify_ssl,
    )


def _content_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _tool_names(tools_result: Any) -> set[str]:
    return {tool.name for tool in getattr(tools_result, "tools", [])}


def _action_name(params: dict[str, Any]) -> str:
    return str(params.get("action") or params.get("tool") or "list").strip().casefold().replace("-", "_")


def _tool_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    if "context_length" in normalized:
        normalized["contextLength"] = normalized.pop("context_length")
    if "target_type" in normalized:
        normalized["targetType"] = normalized.pop("target_type")
    if "target_scope" in normalized:
        normalized["targetScope"] = normalized.pop("target_scope")
    if "command_id" in normalized:
        normalized["commandId"] = normalized.pop("command_id")
    if "new_leaf" in normalized:
        normalized["newLeaf"] = normalized.pop("new_leaf")
    return {
        key: value
        for key, value in normalized.items()
        if key in PARAM_KEYS and value not in ("", None, [])
    }


def _rest_base_url() -> str:
    configured = get_settings().obsidian_mcp_url
    parts = urlsplit(configured)
    path = parts.path
    if path.endswith("/mcp/"):
        path = path[: -len("/mcp/")]
    elif path.endswith("/mcp"):
        path = path[: -len("/mcp")]
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", "")).rstrip("/")


def _vault_url(path: str = "") -> str:
    clean = path.strip().strip("/")
    if not clean:
        return f"{_rest_base_url()}/vault/"
    return f"{_rest_base_url()}/vault/{quote(clean, safe='/')}"


def _format_rest_response(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
    if "application/json" in content_type:
        try:
            return response.text
        except Exception:
            return str(response.json())
    return response.text.strip()


def _rest_error(response: httpx.Response) -> str:
    return f"Obsidian REST failed ({response.status_code}): {response.text[:1000]}"


async def run_rest_action_async(params: dict[str, Any]) -> str:
    if not _obsidian_api_key():
        return "Obsidian REST skipped: set OBSIDIAN_API_KEY."

    action = _action_name(params)
    if action in WRITE_ACTION_TO_TOOL and not _writes_allowed():
        return f"Obsidian REST action '{action}' requires OBSIDIAN_MCP_ALLOW_WRITES=true."
    if action in DESTRUCTIVE_ACTION_TO_TOOL and not _destructive_allowed():
        return f"Obsidian REST action '{action}' requires OBSIDIAN_MCP_ALLOW_DESTRUCTIVE=true."
    if action in COMMAND_ACTION_TO_TOOL and not _commands_allowed():
        return f"Obsidian REST action '{action}' requires OBSIDIAN_MCP_ALLOW_COMMANDS=true."

    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.mcp_timeout_seconds,
        verify=settings.obsidian_mcp_verify_ssl,
    ) as client:
        if action in {"list", "vault_list"}:
            response = await client.get(_vault_url(str(params.get("path") or "")), headers=_obsidian_headers())
            return _format_rest_response(response) if response.status_code == 200 else _rest_error(response)
        if action in {"read", "vault_read", "document_map", "vault_get_document_map"}:
            headers = _obsidian_headers()
            if action in {"document_map", "vault_get_document_map"}:
                headers["Accept"] = "application/vnd.olrapi.document-map+json"
            response = await client.get(_vault_url(str(params.get("path") or "")), headers=headers)
            return _format_rest_response(response) if response.status_code == 200 else _rest_error(response)
        if action in {"search", "search_simple"}:
            response = await client.post(
                f"{_rest_base_url()}/search/simple/",
                headers=_obsidian_headers(),
                params={
                    "query": str(params.get("query") or ""),
                    "contextLength": int(params.get("contextLength") or params.get("context_length") or 100),
                },
            )
            return _format_rest_response(response) if response.status_code == 200 else _rest_error(response)
        if action in {"tags", "tag_list"}:
            response = await client.get(f"{_rest_base_url()}/tags/", headers=_obsidian_headers())
            return _format_rest_response(response) if response.status_code == 200 else _rest_error(response)
        if action in {"commands", "command_list"}:
            response = await client.get(f"{_rest_base_url()}/commands/", headers=_obsidian_headers())
            return _format_rest_response(response) if response.status_code == 200 else _rest_error(response)
        if action in {"write", "vault_write"}:
            path = str(params.get("path") or "")
            response = await client.put(
                _vault_url(path),
                headers=_obsidian_markdown_headers(),
                content=str(params.get("content") or ""),
            )
            if response.status_code in {200, 204}:
                return f"Obsidian REST write completed: {path}."
            return _rest_error(response)
        if action in {"append", "vault_append"}:
            path = str(params.get("path") or "")
            read_response = await client.get(_vault_url(path), headers=_obsidian_headers())
            if read_response.status_code not in {200, 404}:
                return _rest_error(read_response)
            existing = "" if read_response.status_code == 404 else read_response.text
            response = await client.put(
                _vault_url(path),
                headers=_obsidian_markdown_headers(),
                content=f"{existing}{params.get('content') or ''}",
            )
            if response.status_code in {200, 204}:
                return f"Obsidian REST append completed: {path}."
            return _rest_error(response)
        if action in {"patch", "vault_patch"}:
            path = str(params.get("path") or "")
            headers = _obsidian_markdown_headers()
            if params.get("operation"):
                headers["Operation"] = str(params["operation"])
            if params.get("target_type"):
                headers["Target-Type"] = str(params["target_type"])
            if params.get("target"):
                headers["Target"] = str(params["target"])
            response = await client.patch(_vault_url(path), headers=headers, content=str(params.get("content") or ""))
            if response.status_code in {200, 204}:
                return _format_rest_response(response) or f"Obsidian REST patch completed: {path}."
            return _rest_error(response)
        if action in {"delete", "vault_delete"}:
            path = str(params.get("path") or "")
            response = await client.delete(_vault_url(path), headers=_obsidian_headers())
            if response.status_code == 204:
                return f"Obsidian REST delete completed: {path}."
            return _rest_error(response)
        if action in {"open", "open_file"}:
            path = str(params.get("path") or "")
            response = await client.post(
                f"{_rest_base_url()}/open/{quote(path.strip('/'), safe='/')}",
                headers=_obsidian_headers(),
                params={"newLeaf": bool(params.get("newLeaf") or params.get("new_leaf") or False)},
            )
            if response.status_code in {200, 204}:
                return f"Obsidian REST open completed: {path}."
            return _rest_error(response)
        if action in {"execute_command", "command_execute"}:
            command_id = str(params.get("commandId") or params.get("command_id") or "")
            response = await client.post(
                f"{_rest_base_url()}/commands/{quote(command_id, safe='')}/",
                headers=_obsidian_headers(),
            )
            if response.status_code == 204:
                return f"Obsidian REST command executed: {command_id}."
            return _rest_error(response)

    return f"Unsupported Obsidian REST action: {action}."


async def _run_tool_inner(params: dict[str, Any]) -> str:
    if not _obsidian_api_key():
        return "Obsidian MCP skipped: set OBSIDIAN_API_KEY."
    if not _use_stream_transport():
        return await run_rest_action_async(params)

    action = _action_name(params)
    tool_name = (
        READ_ACTION_TO_TOOL.get(action)
        or WRITE_ACTION_TO_TOOL.get(action)
        or DESTRUCTIVE_ACTION_TO_TOOL.get(action)
        or COMMAND_ACTION_TO_TOOL.get(action)
    )
    if tool_name is None:
        return f"Unsupported Obsidian MCP action: {action}."
    if action in WRITE_ACTION_TO_TOOL and not _writes_allowed():
        return f"Obsidian MCP action '{action}' requires OBSIDIAN_MCP_ALLOW_WRITES=true."
    if action in DESTRUCTIVE_ACTION_TO_TOOL and not _destructive_allowed():
        return f"Obsidian MCP action '{action}' requires OBSIDIAN_MCP_ALLOW_DESTRUCTIVE=true."
    if action in COMMAND_ACTION_TO_TOOL and not _commands_allowed():
        return f"Obsidian MCP action '{action}' requires OBSIDIAN_MCP_ALLOW_COMMANDS=true."

    settings = get_settings()
    timeout = settings.mcp_timeout_seconds
    async with streamablehttp_client(
        settings.obsidian_mcp_url,
        headers=_obsidian_headers(),
        timeout=timeout,
        sse_read_timeout=timeout,
        httpx_client_factory=_httpx_client_factory,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"Obsidian MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, _tool_params(params))
            return _content_text(result) or f"Obsidian MCP {action} completed."


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Obsidian MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[OBSIDIAN_MCP] Error: %s", exc)
        logger.info("[OBSIDIAN_REST] Falling back to Local REST API.")
        return await run_rest_action_async(params)


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("obsidian_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
