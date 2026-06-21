from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.config import REPO_ROOT, get_settings
from agent.tools.capabilities.agent_reach_x_provider import AgentReachError, AgentReachXProvider
from agent.tools.registry import (
    CapabilityAccess,
    CapabilityRecord,
    ToolPermissionError,
    ToolRegistry,
)

SearchPostsBackend = Callable[[str, int], list[dict[str, Any]]]
PostBackend = Callable[..., dict[str, Any]]
AccountBackend = Callable[[], dict[str, Any]]
BookmarksBackend = Callable[[str, int], dict[str, Any]]
ImageBackend = Callable[[str], dict[str, Any]]
MediaUploadBackend = Callable[[str], dict[str, Any]]


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
        image_backend: ImageBackend | None = None,
        media_upload_backend: MediaUploadBackend | None = None,
        agent_reach_provider: Any | None = None,
        allow_private_reads: bool | None = None,
        allow_posts: bool | None = None,
    ) -> None:
        self.search_posts_backend = search_posts_backend or self._default_search_posts
        self.post_backend = post_backend or self._default_post
        self.account_backend = account_backend or self._default_account
        self.bookmarks_backend = bookmarks_backend or self._default_bookmarks
        self.image_backend = image_backend or self._default_generate_image
        self.media_upload_backend = media_upload_backend or self._default_upload_media
        self.agent_reach_provider = agent_reach_provider or AgentReachXProvider()
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
        registry.register(
            CapabilityRecord(
                name="x.publish_post_with_media",
                namespace="x",
                access=CapabilityAccess.EXTERNAL_WRITE,
                allowed_agents=frozenset({"XAgent", "VellumAgent"}),
                stream_label="Posted image to X",
                requires_confirmation=True,
                adapter=self.publish_post_with_media,
            )
        )
        return registry

    def search_posts(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        max_results = self._normalize_max_results(payload.get("max_results", 10))
        fallback_reason = ""
        if self._agent_reach_available():
            try:
                items = [self._normalize_post(item) for item in self.agent_reach_provider.search(query, max_results)]
                return {"action": "x.search_posts", "items": items, "provider": "agent-reach"}
            except AgentReachError as exc:
                fallback_reason = self._safe_reason(exc)
        items = [self._normalize_post(item) for item in self.search_posts_backend(query, max_results)]
        result = {"action": "x.search_posts", "items": items, "provider": "xai"}
        if fallback_reason:
            result["fallback_reason"] = fallback_reason
        return result

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
        if self._agent_reach_available():
            try:
                return {
                    "action": "x.publish_post",
                    "tweet": self.agent_reach_provider.post_tweet(text),
                    "provider": "agent-reach",
                }
            except AgentReachError:
                pass
        return {"action": "x.publish_post", "tweet": self.post_backend(text)}

    def publish_post_with_media(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_posts:
            raise ToolPermissionError("Posting to X requires X_TOOL_ALLOW_POSTS=true.")
        if payload.get("confirm") is not True:
            raise ToolPermissionError("Posting to X requires confirm=True.")
        text = str(payload.get("text", "")).strip()
        image_path = str(payload.get("image_path") or "").strip()
        image: dict[str, Any] = {"path": image_path} if image_path else {}
        if not image_path:
            image_prompt = str(payload.get("image_prompt") or payload.get("prompt") or "").strip()
            if not image_prompt:
                raise ToolPermissionError("Image post requires image_path or image_prompt.")
            image = self.image_backend(image_prompt)
            image_path = str(image.get("path") or "").strip()
        if not image_path:
            raise ToolPermissionError("Generated image did not return a file path.")
        uploaded = self.media_upload_backend(image_path)
        media_id = self._extract_media_id(uploaded)
        if not media_id:
            raise ToolPermissionError("X media upload did not return a media id.")
        tweet = self.post_backend(text, media_ids=[media_id], made_with_ai=not bool(payload.get("image_path")))
        return {
            "action": "x.publish_post_with_media",
            "tweet": tweet,
            "image": image,
            "media": uploaded,
        }

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
            oauth_file=XCapabilityService._xai_oauth_file(),
        )

    @staticmethod
    def _default_post(text: str, media_ids: list[str] | None = None, made_with_ai: bool = False) -> dict[str, Any]:
        client = _load_script("x_api_client")
        return client.post_tweet(
            text=text,
            media_ids=media_ids,
            made_with_ai=made_with_ai,
            oauth_file=XCapabilityService._oauth_file(),
        ).get("data", {})

    @staticmethod
    def _oauth_file():
        return REPO_ROOT / "data" / "x-api-oauth.json"

    @staticmethod
    def _xai_oauth_file():
        return REPO_ROOT / "data" / "xai-oauth.json"

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

    @staticmethod
    def _default_generate_image(prompt: str) -> dict[str, Any]:
        client = _load_script("openai_image_client")
        settings = get_settings()
        return client.generate_image_file(
            prompt=prompt,
            api_key=getattr(settings, "openai_api_key", None),
            base_url=getattr(settings, "openai_base_url", "https://api.openai.com/v1"),
        )

    @staticmethod
    def _default_upload_media(path: str) -> dict[str, Any]:
        client = _load_script("x_api_client")
        result = client.upload_media(media_path=Path(path), oauth_file=XCapabilityService._oauth_file())
        data = result.get("data", {})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_media_id(uploaded: dict[str, Any]) -> str:
        for key in ("id", "media_id", "media_id_string"):
            value = uploaded.get(key)
            if value:
                return str(value)
        data = uploaded.get("data")
        if isinstance(data, dict):
            for key in ("id", "media_id", "media_id_string"):
                value = data.get(key)
                if value:
                    return str(value)
        return ""

    def _agent_reach_available(self) -> bool:
        try:
            return bool(self.agent_reach_provider and self.agent_reach_provider.available())
        except Exception:
            return False

    def _safe_reason(self, exc: Exception) -> str:
        return str(exc).replace("\r", " ").replace("\n", " ")[:200]
