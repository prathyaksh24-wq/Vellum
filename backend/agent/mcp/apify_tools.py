"""
Apify MCP tool wrapper.

Apify results are treated as private. Raw tool output is stored locally for
memory, then sanitized before anything downstream can include it in an LLM
prompt or user-visible tool response.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings
from agent.privacy.scrubber import PrivacyScrubber

logger = logging.getLogger(__name__)
scrubber = PrivacyScrubber()

APIFY_CALL_ACTOR_TOOL = "call-actor"
ASIN_RE = re.compile(r"\b(?:ASIN[:\s#-]*)?[A-Z0-9]{10}\b")
URL_RE = re.compile(r"https?://\S+", re.I)
PRESIDIO_URL_RE = re.compile(r"\[URL_\d+\]")


def _apify_mcp_url() -> str:
    return get_settings().apify_mcp_url


def _apify_headers() -> dict[str, str]:
    token = get_settings().apify_api_token
    return {"Authorization": f"Bearer {token}"}


def _content_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts).strip()


def sanitize_apify_result(raw_text: str) -> str:
    clean, _ = scrubber.scrub(raw_text or "")
    clean = URL_RE.sub("[URL_REDACTED]", clean)
    clean = PRESIDIO_URL_RE.sub("[URL_REDACTED]", clean)
    clean = ASIN_RE.sub("[ASIN_REDACTED]", clean)
    return clean[:4000]


def _amazon_actor_input(query: str, max_items: int) -> dict:
    return {
        "search": query,
        "maxItems": max_items,
        "scrapeProductDetails": False,
        "getFullDetails": False,
        "headless": True,
    }


async def _run_tool_inner(params: dict) -> str:
    query = (params.get("query") or "").strip()
    if not query:
        return "Apify search skipped: no query provided."

    logger.info("[APIFY] Running Amazon search for: %s", query[:50])
    try:
        timeout = get_settings().mcp_timeout_seconds
        async with streamablehttp_client(
            _apify_mcp_url(),
            headers=_apify_headers(),
            timeout=timeout,
            sse_read_timeout=timeout,
        ) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    APIFY_CALL_ACTOR_TOOL,
                    {
                        "actor": params.get("actor") or get_settings().apify_amazon_actor,
                        "input": _amazon_actor_input(query, int(params.get("max_items", 5))),
                        "previewOutput": True,
                        "callOptions": {"timeout": timeout},
                    },
                )
                raw_text = _content_text(result) or "No results."
                return sanitize_apify_result(raw_text)
    except Exception as exc:
        logger.error("[APIFY] Error: %s", exc)
        return f"Apify search failed: {exc}"


async def run_tool_async(params: dict) -> str:
    timeout = get_settings().mcp_timeout_seconds
    try:
        return await asyncio.wait_for(_run_tool_inner(params), timeout=timeout)
    except TimeoutError:
        return f"Apify search timed out after {timeout} seconds."


def run_tool(params: dict) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_tool_async(params))
    raise RuntimeError("apify_tools.run_tool cannot run inside an active event loop; use run_tool_async.")
