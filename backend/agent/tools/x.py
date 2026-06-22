"""Controlled X actions for Vellum."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from agent.config import REPO_ROOT, get_settings
from agent.tools.capabilities.agent_reach_x_provider import AgentReachError, AgentReachXProvider


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _xai_client():
    return _load_script("xai_x_search_client")


def _x_api_client():
    return _load_script("x_api_client")


def _image_client():
    return _load_script("openai_image_client")


def _agent_reach_provider() -> AgentReachXProvider:
    return AgentReachXProvider()


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _oauth_file() -> Path:
    return REPO_ROOT / "data" / "x-api-oauth.json"


def _xai_oauth_file() -> Path:
    return REPO_ROOT / "data" / "xai-oauth.json"


@tool
def x_action(
    action: str,
    query: str = "",
    text: str = "",
    image_path: str = "",
    image_prompt: str = "",
    max_results: int = 10,
    confirm: bool = False,
) -> str:
    """Run controlled X actions: status, search, me, bookmarks, timeline, likes, profile, read_tweet, post, reply, like, repost, delete, post_image.

    status reports Agent-Reach/X connector availability. Search prefers
    Agent-Reach when ready and falls back to xAI X Search. me/bookmarks use
    official X API OAuth and require X_TOOL_ALLOW_PRIVATE_READS=true.
    write actions require confirm=True and X_TOOL_ALLOW_POSTS=true.
    """
    normalized = action.strip().casefold().replace("-", "_")
    settings = get_settings()

    try:
        if normalized == "status":
            agent_reach = _agent_reach_provider()
            agent_reach_status = agent_reach.status().model_dump()
            return _json(
                {
                    "action": "status",
                    "agent_reach": agent_reach_status,
                    "agent_reach_available": bool(agent_reach_status.get("configured"))
                    and agent_reach_status.get("status") == "ready",
                    "x_private_reads_enabled": bool(settings.x_tool_allow_private_reads),
                    "x_posts_enabled": bool(settings.x_tool_allow_posts),
                }
            )

        if normalized == "search":
            if not query.strip():
                return "X search requires query."
            agent_reach = _agent_reach_provider()
            if agent_reach.available():
                try:
                    return _json({
                        "action": "search",
                        "provider": "agent-reach",
                        "items": agent_reach.search(query, max_results=max_results),
                    })
                except AgentReachError:
                    pass
            client = _xai_client()
            now = datetime.now(timezone.utc).replace(microsecond=0)
            items = client.search_x(
                query=query,
                start=now - timedelta(days=7),
                end=now,
                max_items=max_results,
                oauth_file=_xai_oauth_file(),
            )
            return _json({"action": "search", "items": items})

        if normalized in {"me", "bookmarks"} and not settings.x_tool_allow_private_reads:
            return "X private reads require X_TOOL_ALLOW_PRIVATE_READS=true."

        if normalized == "me":
            client = _x_api_client()
            return _json({"action": "me", "account": client.get_me(oauth_file=_oauth_file()).get("data", {})})

        if normalized == "bookmarks":
            agent_reach = _agent_reach_provider()
            if agent_reach.available():
                try:
                    return _json({
                        "action": "bookmarks",
                        "provider": "agent-reach",
                        "items": agent_reach.bookmarks(max_results=max_results),
                    })
                except AgentReachError:
                    pass
            client = _x_api_client()
            me = client.get_me(oauth_file=_oauth_file()).get("data", {})
            user_id = str(me.get("id") or "")
            if not user_id:
                return "X bookmarks require an authenticated user id."
            bookmarks = client.get_bookmarks(
                user_id=user_id,
                max_results=max_results,
                oauth_file=_oauth_file(),
            )
            return _json({
                "action": "bookmarks",
                "account": me,
                "items": bookmarks.get("data", []),
                "meta": bookmarks.get("meta", {}),
            })

        if normalized in {"timeline", "feed"}:
            agent_reach = _agent_reach_provider()
            if not agent_reach.available():
                return "Agent-Reach X connector is not ready."
            return _json({
                "action": "timeline",
                "provider": "agent-reach",
                "items": agent_reach.timeline(max_results=max_results),
            })

        if normalized == "likes":
            if not settings.x_tool_allow_private_reads:
                return "X private reads require X_TOOL_ALLOW_PRIVATE_READS=true."
            handle = (query or text).strip().lstrip("@")
            if not handle:
                return "X likes requires a handle."
            agent_reach = _agent_reach_provider()
            if not agent_reach.available():
                return "Agent-Reach X connector is not ready."
            return _json({
                "action": "likes",
                "provider": "agent-reach",
                "items": agent_reach.likes(handle, max_results=max_results),
            })

        if normalized in {"profile", "user"}:
            handle = (query or text).strip().lstrip("@")
            if not handle:
                return "X profile requires a handle."
            agent_reach = _agent_reach_provider()
            if not agent_reach.available():
                return "Agent-Reach X connector is not ready."
            return _json({
                "action": "profile",
                "provider": "agent-reach",
                "profile": agent_reach.profile(handle),
            })

        if normalized in {"read_tweet", "tweet", "read"}:
            tweet_id = (query or text).strip()
            if not tweet_id:
                return "X read_tweet requires a tweet id or URL."
            agent_reach = _agent_reach_provider()
            if not agent_reach.available():
                return "Agent-Reach X connector is not ready."
            return _json({
                "action": "read_tweet",
                "provider": "agent-reach",
                "tweet": agent_reach.read_tweet(tweet_id),
            })

        if normalized == "post":
            if not confirm:
                return "Posting to X requires confirm=True in the tool call."
            if not settings.x_tool_allow_posts:
                return "Posting to X requires X_TOOL_ALLOW_POSTS=true."
            agent_reach = _agent_reach_provider()
            if agent_reach.available():
                try:
                    return _json({
                        "action": "post",
                        "provider": "agent-reach",
                        "tweet": agent_reach.post_tweet(text),
                    })
                except AgentReachError:
                    pass
            client = _x_api_client()
            result = client.post_tweet(text=text, oauth_file=_oauth_file())
            return _json({"action": "post", "tweet": result.get("data", {})})

        if normalized in {"reply", "like", "repost", "retweet", "delete"}:
            if not confirm:
                return "X write actions require confirm=True in the tool call."
            if not settings.x_tool_allow_posts:
                return "X write actions require X_TOOL_ALLOW_POSTS=true."
            tweet_id = query.strip()
            if not tweet_id:
                return "X write actions require query to contain a tweet id or URL."
            agent_reach = _agent_reach_provider()
            if not agent_reach.available():
                return "Agent-Reach X connector is not ready."
            if normalized == "reply":
                if not text.strip():
                    return "X reply requires text."
                result = agent_reach.reply(tweet_id, text)
            elif normalized == "like":
                result = agent_reach.like(tweet_id)
            elif normalized in {"repost", "retweet"}:
                result = agent_reach.repost(tweet_id)
            else:
                result = agent_reach.delete(tweet_id)
            return _json({"action": normalized, "provider": "agent-reach", "result": result})

        if normalized in {"post_image", "post_with_image", "image_post"}:
            if not confirm:
                return "Posting to X requires confirm=True in the tool call."
            if not settings.x_tool_allow_posts:
                return "Posting to X requires X_TOOL_ALLOW_POSTS=true."
            client = _x_api_client()
            resolved_image_path = image_path.strip()
            generated: dict[str, Any] = {}
            if not resolved_image_path:
                prompt = (image_prompt or query).strip()
                if not prompt:
                    return "Image posting requires image_path, image_prompt, or query."
                generated = _image_client().generate_image_file(
                    prompt=prompt,
                    api_key=getattr(settings, "openai_api_key", None),
                    base_url=getattr(settings, "openai_base_url", "https://api.openai.com/v1"),
                )
                resolved_image_path = str(generated.get("path") or "")
            if not resolved_image_path:
                return "Image generation did not return a file path."
            uploaded = client.upload_media(media_path=Path(resolved_image_path), oauth_file=_oauth_file())
            media = uploaded.get("data", uploaded)
            media_id = ""
            if isinstance(media, dict):
                media_id = str(media.get("id") or media.get("media_id") or media.get("media_id_string") or "")
            if not media_id:
                return "X media upload did not return a media id."
            result = client.post_tweet(
                text=text,
                media_ids=[media_id],
                made_with_ai=not bool(image_path.strip()),
                oauth_file=_oauth_file(),
            )
            return _json({"action": "post_image", "tweet": result.get("data", {}), "image": generated, "media": media})

        return f"Unsupported X action: {normalized}."
    except Exception as exc:
        return f"X action failed: {exc}"
