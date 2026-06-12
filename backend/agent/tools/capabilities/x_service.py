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
AccountBackend = Callable[[], dict[str, Any]]
BookmarksBackend = Callable[[str, int], dict[str, Any]]


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
        account_backend: AccountBackend | None = None,
        bookmarks_backend: BookmarksBackend | None = None,
        allow_private_reads: bool | None = None,
        allow_posts: bool | None = None,
    ) -> None:
        self.search_posts_backend = search_posts_backend or self._default_search_posts
        self.post_backend = post_backend or self._default_post
        self.account_backend = account_backend or self._default_account
        self.bookmarks_backend = bookmarks_backend or self._default_bookmarks
        settings = get_settings()
        self.allow_private_reads = (
            bool(getattr(settings, "x_tool_allow_private_reads", False))
            if allow_private_reads is None
            else allow_private_reads
        )
        self.allow_posts = (
            bool(getattr(settings, "x_tool_allow_posts", False)) if allow_posts is None else allow_posts
        )

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
                name="x.account",
                namespace="x",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"XAgent", "VellumAgent"}),
                stream_label="Read X account",
                adapter=self.account,
                required_env_flags=frozenset({"X_TOOL_ALLOW_PRIVATE_READS"}),
            )
        )
        registry.register(
            CapabilityRecord(
                name="x.bookmarks",
                namespace="x",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"XAgent", "MemoryAgent", "VellumAgent"}),
                stream_label="Read X bookmarks",
                adapter=self.bookmarks,
                required_env_flags=frozenset({"X_TOOL_ALLOW_PRIVATE_READS"}),
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

    def account(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_private_reads:
            raise ToolPermissionError("X private reads require X_TOOL_ALLOW_PRIVATE_READS=true.")
        return {"action": "x.account", "account": self.account_backend()}

    def bookmarks(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_private_reads:
            raise ToolPermissionError("X private reads require X_TOOL_ALLOW_PRIVATE_READS=true.")
        max_results = self._normalize_max_results(payload.get("max_results", 10))
        account = self.account_backend()
        user_id = str(account.get("id") or "").strip()
        if not user_id:
            raise ToolPermissionError("X bookmarks require an authenticated user id.")
        result = self.bookmarks_backend(user_id, max_results)
        return {
            "action": "x.bookmarks",
            "account": account,
            "items": result.get("data", []),
            "meta": result.get("meta", {}),
        }

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

    @staticmethod
    def _oauth_file():
        return REPO_ROOT / "data" / "x-api-oauth.json"

    @staticmethod
    def _default_account() -> dict[str, Any]:
        client = _load_script("x_api_client")
        return client.get_me(oauth_file=XCapabilityService._oauth_file()).get("data", {})

    @staticmethod
    def _default_bookmarks(user_id: str, max_results: int) -> dict[str, Any]:
        client = _load_script("x_api_client")
        return client.get_bookmarks(
            user_id=user_id,
            max_results=max_results,
            oauth_file=XCapabilityService._oauth_file(),
        )
