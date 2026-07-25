"""Shared mechanics for MCP transport adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any, TypeVar

from agent.mcp.results import UNREACHABLE

T = TypeVar("T")


def content_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    return "\n".join(
        str(text)
        for item in content
        if (text := getattr(item, "text", None)) is not None
    ).strip()


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