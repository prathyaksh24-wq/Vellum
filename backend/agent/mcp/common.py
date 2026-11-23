"""Shared mechanics for MCP transport adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
import logging
from typing import Any, TypeVar

from agent.mcp.results import UNREACHABLE

T = TypeVar("T")


def content_text(result: Any) -> str:
    """The text of an MCP tool result.

    A tool with an output schema returns its data in ``structuredContent``; its
    text part may be empty or only a status line. The structured data is used
    then, so the model sees what the provider returned.
    """
    content = getattr(result, "content", None) or []
    text = "\n".join(
        str(value)
        for item in content
        if (value := getattr(item, "text", None)) is not None
    ).strip()
    structured = getattr(result, "structuredContent", None)
    if structured in (None, {}, []):
        return text
    try:
        data = json.dumps(structured, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return text
    return data if len(data) > len(text) else text


def tool_names(tools_result: Any) -> set[str]:
    return {str(tool.name) for tool in getattr(tools_result, "tools", [])}


async def run_with_timeout(
    operation: Awaitable[str],
    *,
    timeout: float,
    logger: logging.Logger,
    label: str,
) -> str:
    try:
        return await asyncio.wait_for(operation, timeout=timeout)
    except Exception as exc:
        logger.error("[%s] Unreachable: %s", label, exc)
        return UNREACHABLE


def run_sync(
    async_runner: Callable[[dict[str, Any]], Awaitable[T]],
    params: dict[str, Any],
    *,
    adapter_name: str,
) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_runner(params))
    raise RuntimeError(
        f"{adapter_name}.run_tool cannot run inside an active event loop; "
        "use run_tool_async."
    )