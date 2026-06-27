"""
Apify MCP tool wrapper.

Apify results are treated as private. Raw tool output is stored locally for
memory, then sanitized before anything downstream can include it in an LLM
prompt or user-visible tool response.
"""

from __future__ import annotations

import asyncio
import json
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
YOUTUBE_VIDEO_FIELDS = (
    "videoId",
    "video_id",
    "id",
    "url",
    "videoUrl",
    "video_url",
    "watchUrl",
    "watch_url",
    "link",
    "title",
    "name",
    "channel",
    "channelName",
    "channel_name",
    "author",
    "publishedAt",
    "published_at",
    "date",
    "description",
    "snippet",
    "body",
    "transcript",
    "transcriptText",
    "transcript_text",
)


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


def _youtube_actor_input(query: str, max_items: int) -> dict:
    return {
        "search": query,
        "searchQuery": query,
        "searchQueries": [query],
        "maxItems": max_items,
        "maxResults": max_items,
        "maxVideos": max_items,
        "includeTranscript": True,
        "transcriptLanguage": "en",
        "sortBy": "relevance",
    }


def _json_items(raw_text: str) -> list[dict[str, Any]]:
    if not raw_text.strip():
        return []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"(?s)(\[.*\]|\{.*\})", raw_text)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = next(
            (
                value
                for key in ("items", "data", "results", "videos")
                if isinstance((value := payload.get(key)), list)
            ),
            [],
        )
    else:
        items = []

    return [_safe_youtube_item(item) for item in items if isinstance(item, dict)]


def _safe_youtube_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in YOUTUBE_VIDEO_FIELDS if key in item and item[key] is not None}


async def search_youtube_videos_async(query: str, max_results: int) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []

    logger.info("[APIFY] Running YouTube search for: %s", query[:50])
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
                    "actor": get_settings().apify_youtube_actor,
                    "input": _youtube_actor_input(query, int(max_results)),
                    "previewOutput": True,
                    "callOptions": {"timeout": timeout},
                },
            )
            return _json_items(_content_text(result))[:max_results]


def search_youtube_videos(query: str, max_results: int) -> list[dict[str, Any]]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(search_youtube_videos_async(query, max_results))
    raise RuntimeError("apify_tools.search_youtube_videos cannot run inside an active event loop.")


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
