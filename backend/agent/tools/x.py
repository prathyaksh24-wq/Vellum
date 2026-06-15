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
    """Run controlled X actions: search, me, bookmarks, post, post_image.

    search uses xAI X Search. me/bookmarks use official X API OAuth and require
    X_TOOL_ALLOW_PRIVATE_READS=true. post/post_image require confirm=True and
    X_TOOL_ALLOW_POSTS=true.
    """
    normalized = action.strip().casefold().replace("-", "_")
    settings = get_settings()

    try:
        if normalized == "search":
            if not query.strip():
                return "X search requires query."
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

        if normalized == "post":
            if not confirm:
                return "Posting to X requires confirm=True in the tool call."
            if not settings.x_tool_allow_posts:
                return "Posting to X requires X_TOOL_ALLOW_POSTS=true."
            client = _x_api_client()
            result = client.post_tweet(text=text, oauth_file=_oauth_file())
            return _json({"action": "post", "tweet": result.get("data", {})})

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
