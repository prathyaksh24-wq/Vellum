from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.config import REPO_ROOT, get_settings
from agent.tools.registry import (
    CapabilityAccess,
    CapabilityRecord,
    ToolPermissionError,
    ToolRegistry,
)

SearchPostsBackend = Callable[[str, int], list[dict[str, Any]]]
PostBackend = Callable[[str], dict[str, Any]]


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load script {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class XCapabilityService:
    def __init__(
        self,
        search_posts_backend: SearchPostsBackend | None = None,
        post_backend: PostBackend | None = None,
        allow_posts: bool | None = None,
    ) -> None:
        self.search_posts_backend = search_posts_backend or self._default_search_posts
        self.post_backend = post_backend or self._default_post
        self.allow_posts = get_settings().x_tool_allow_posts if allow_posts is None else allow_posts

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            CapabilityRecord(
                name="x.search_posts",
                namespace="x",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"XAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"}),
                stream_label="Searched X",
                adapter=self.search_posts,
            )
        )
        registry.register(
            CapabilityRecord(
                name="x.publish_post",
                namespace="x",
                access=CapabilityAccess.EXTERNAL_WRITE,
                allowed_agents=frozenset({"XAgent", "VellumAgent"}),
                stream_label="Posted to X",
                requires_confirmation=True,
                adapter=self.publish_post,
            )
        )
        return registry

    def search_posts(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        max_results = self._normalize_max_results(payload.get("max_results", 10))
        items = [self._normalize_post(item) for item in self.search_posts_backend(query, max_results)]
        return {"action": "x.search_posts", "items": items}

    def publish_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_posts:
            raise ToolPermissionError("Posting to X requires X_TOOL_ALLOW_POSTS=true.")
        if payload.get("confirm") is not True:
            raise ToolPermissionError("Posting to X requires confirm=True.")
        text = str(payload.get("text", ""))
        return {"action": "x.publish_post", "tweet": self.post_backend(text)}

    @staticmethod
    def _normalize_max_results(value: Any) -> int:
        try:
            max_results = int(value)
        except (TypeError, ValueError):
            return 10
        return max(1, max_results)

    @staticmethod
    def _normalize_post(item: dict[str, Any]) -> dict[str, str]:
        author = item.get("author")
        author_username = author.get("username") if isinstance(author, dict) else None
        handle = author_username or item.get("handle")
        return {
            "text": XCapabilityService._string(item.get("text") or item.get("body")),
            "url": XCapabilityService._string(item.get("url") or item.get("x_url") or item.get("tweet_url")),
            "handle": XCapabilityService._string(handle),
            "created_at": XCapabilityService._string(item.get("created_at") or item.get("date")),
        }

    @staticmethod
    def _string(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _default_search_posts(query: str, max_results: int) -> list[dict[str, Any]]:
        client = _load_script("xai_x_search_client")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return client.search_x(
            query=query,
            start=now - timedelta(days=7),
            end=now,
            max_items=max_results,
        )

    @staticmethod
    def _default_post(text: str) -> dict[str, Any]:
        client = _load_script("x_api_client")
        return client.post_tweet(text=text).get("data", {})
