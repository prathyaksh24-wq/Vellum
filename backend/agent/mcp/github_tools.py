"""Canonical GitHub adapter: prefer gh, fall back to the configured MCP."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings
from agent.mcp.github_cli import run as cli_run
from agent.mcp.github_cli import credential as cli_credential
from agent.plugins.registry import get_plugin_registry

logger = logging.getLogger(__name__)

ACTION_TO_TOOL = {
    "search_repositories": "search_repositories",
    "search_code": "search_code",
    "get_file": "get_file_contents",
    "get_file_contents": "get_file_contents",
    "list_commits": "list_commits",
    "get_commit": "get_commit",
    "list_branches": "list_branches",
    "list_tags": "list_tags",
    "list_releases": "list_releases",
    "get_latest_release": "get_latest_release",
    "get_pull_request": "get_pull_request",
    "list_pull_requests": "list_pull_requests",
    "get_issue": "get_issue",
    "list_issues": "list_issues",
}

WRITE_ACTION_TO_TOOL = {
    "create_issue": "create_issue",
    "create_pull_request": "create_pull_request",
    "create_repository": "create_repository",
    "create_branch": "create_branch",
    "create_or_update_file": "create_or_update_file",
    "push_files": "push_files",
    "delete_file": "delete_file",
    "fork_repository": "fork_repository",
}

DESTRUCTIVE_ACTIONS = {"delete_file", "delete_repository"}

PARAM_KEYS = {
    "owner",
    "repo",
    "query",
    "path",
    "ref",
    "sha",
    "branch",
    "tag",
    "pullNumber",
    "issueNumber",
    "page",
    "perPage",
    "since",
    "until",
    "author",
    "state",
    "title",
    "body",
    "name",
    "organization",
    "description",
    "private",
    "autoInit",
    "from_branch",
    "head",
    "base",
    "draft",
    "content",
    "message",
    "files",
}


def _github_token() -> str:
    settings = get_settings()
    return settings.github_mcp_token or settings.github_pat or os.environ.get("GITHUB_PAT", "") or os.environ.get("GITHUB_TOKEN", "")


def _github_headers(token: str = "") -> dict[str, str]:
    return {"Authorization": f"Bearer {token or _github_token()}"}


def _writes_allowed() -> bool:
    return get_settings().github_mcp_allow_writes


def _destructive_allowed() -> bool:
    return get_settings().github_mcp_allow_destructive


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
    return str(params.get("action") or params.get("tool") or "").strip().casefold().replace("-", "_")


def _tool_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    action = _action_name(normalized)
    if "pull_number" in normalized:
        normalized["pullNumber"] = normalized.pop("pull_number")
    if "issue_number" in normalized:
        normalized["issueNumber"] = normalized.pop("issue_number")
    if "per_page" in normalized:
        normalized["perPage"] = normalized.pop("per_page")
    if "auto_init" in normalized:
        normalized["autoInit"] = normalized.pop("auto_init")
    if action == "create_issue" and "body" not in normalized and "description" in normalized:
        normalized["body"] = normalized.pop("description")
    if action == "create_issue":
        normalized.pop("description", None)
    return {
        key: value
        for key, value in normalized.items()
        if key in PARAM_KEYS and value not in ("", None, [])
    }


async def _run_tool_inner(params: dict[str, Any]) -> str:
    registry = get_plugin_registry()
    with registry.read_snapshot():
        if registry.contains("github") and not registry.is_enabled("github"):
            return "GitHub is disabled. Enable its plugin before using either transport."
    action = _action_name(params)
    tool_name = ACTION_TO_TOOL.get(action) or WRITE_ACTION_TO_TOOL.get(action)
    if tool_name is None and action != "delete_repository":
        return f"GitHub MCP action '{action or 'missing'}' is not allowed."
    if (action in WRITE_ACTION_TO_TOOL or action == "delete_repository") and not _writes_allowed():
        return f"GitHub MCP action '{action}' requires GITHUB_MCP_ALLOW_WRITES=true."
    if action in DESTRUCTIVE_ACTIONS and not _destructive_allowed():
        return f"GitHub MCP action '{action}' requires GITHUB_MCP_ALLOW_DESTRUCTIVE=true."

    settings = get_settings()
    timeout = settings.mcp_timeout_seconds
    token = await cli_credential(_github_token(), timeout=timeout)
    try:
        cli_result = await cli_run(action, params, token=token, timeout=min(timeout / 3, 8))
    except ValueError as exc:
        return f"GitHub failed: {exc}"
    if cli_result is not None:
        return cli_result
    if not token:
        return "GitHub MCP skipped: CLI unavailable and no MCP credential. Set GITHUB_MCP_TOKEN or GITHUB_PAT."
    if action == "delete_repository":
        return await _delete_repository(params, token=token)
    async with streamablehttp_client(
        settings.github_mcp_url,
        headers=_github_headers(token),
        timeout=timeout,
        sse_read_timeout=timeout,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if action in {"get_issue", "get_pull_request"} and tool_name not in tool_names:
                modern = "issue_read" if action == "get_issue" else "pull_request_read"
                if modern in tool_names:
                    arguments = {**_tool_params(params), "method": "get"}
                    if modern == "issue_read" and "issueNumber" in arguments:
                        arguments["issue_number"] = arguments.pop("issueNumber")
                    result = await session.call_tool(modern, arguments)
                    if getattr(result, "isError", False):
                        return "GitHub MCP failed: the server rejected this operation."
                    return _content_text(result)
            if tool_name not in tool_names:
                return f"GitHub MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, _tool_params(params))
            if getattr(result, "isError", False):
                return "GitHub MCP failed: the server rejected this operation."
            return _content_text(result) or f"GitHub MCP {action} completed."


async def _delete_repository(params: dict[str, Any], *, token: str = "") -> str:
    if not _writes_allowed():
        return "GitHub MCP action 'delete_repository' requires GITHUB_MCP_ALLOW_WRITES=true."
    if not _destructive_allowed():
        return "GitHub MCP action 'delete_repository' requires GITHUB_MCP_ALLOW_DESTRUCTIVE=true."
    owner = str(params.get("owner") or "").strip()
    repo = str(params.get("repo") or "").strip()
    if not owner or not repo:
        return "GitHub delete_repository requires owner and repo."
    async with httpx.AsyncClient(timeout=get_settings().mcp_timeout_seconds) as client:
        response = await client.delete(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers={
                **_github_headers(token),
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if response.status_code in {202, 204}:
        return f"GitHub repository deleted: {owner}/{repo}."
    return f"GitHub delete_repository failed ({response.status_code}): {response.text[:1000]}"


async def run_tool_async(params: dict[str, Any]) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"GitHub MCP timed out after {timeout} seconds."
    except Exception as exc:
        logger.error("[GITHUB_MCP] Error: %s", exc)
        return f"GitHub MCP failed: {exc}"


def run_tool(params: dict[str, Any]) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("github_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
