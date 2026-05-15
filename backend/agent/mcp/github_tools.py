"""Read-only GitHub MCP wrapper."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings

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
    "name",
    "organization",
    "description",
    "private",
    "autoInit",
    "from_branch",
    "content",
    "message",
    "files",
}


def _github_token() -> str:
    settings = get_settings()
    return settings.github_mcp_token or settings.github_pat or os.environ.get("GITHUB_PAT", "") or os.environ.get("GITHUB_TOKEN", "")


def _github_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_github_token()}"}


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
    if "pull_number" in normalized:
        normalized["pullNumber"] = normalized.pop("pull_number")
    if "issue_number" in normalized:
        normalized["issueNumber"] = normalized.pop("issue_number")
    if "per_page" in normalized:
        normalized["perPage"] = normalized.pop("per_page")
    if "auto_init" in normalized:
        normalized["autoInit"] = normalized.pop("auto_init")
    return {
        key: value
        for key, value in normalized.items()
        if key in PARAM_KEYS and value not in ("", None, [])
    }


async def _run_tool_inner(params: dict[str, Any]) -> str:
    token = _github_token()
    if not token:
        return "GitHub MCP skipped: set GITHUB_MCP_TOKEN or GITHUB_PAT."

    action = _action_name(params)
    if action == "delete_repository":
        return await _delete_repository(params)

    tool_name = ACTION_TO_TOOL.get(action) or WRITE_ACTION_TO_TOOL.get(action)
    if tool_name is None:
        return f"GitHub MCP action '{action or 'missing'}' is not allowed."
    if action in WRITE_ACTION_TO_TOOL and not _writes_allowed():
        return f"GitHub MCP action '{action}' requires GITHUB_MCP_ALLOW_WRITES=true."
    if action in DESTRUCTIVE_ACTIONS and not _destructive_allowed():
        return f"GitHub MCP action '{action}' requires GITHUB_MCP_ALLOW_DESTRUCTIVE=true."

    settings = get_settings()
    timeout = settings.mcp_timeout_seconds
    async with streamablehttp_client(
        settings.github_mcp_url,
        headers=_github_headers(),
        timeout=timeout,
        sse_read_timeout=timeout,
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_names = _tool_names(await session.list_tools())
            if tool_name not in tool_names:
                return f"GitHub MCP server does not expose {tool_name}."
            result = await session.call_tool(tool_name, _tool_params(params))
            return _content_text(result) or f"GitHub MCP {action} completed."


async def _delete_repository(params: dict[str, Any]) -> str:
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
                **_github_headers(),
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
