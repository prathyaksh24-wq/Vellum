from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.registry import ToolRegistry


class XAgent:
    name = "XAgent"

    _KEYWORDS = ("twitter", "tweet", "tweets", "latest-50", "bookmark", "bookmarks")
    _X_CONTEXT_PATTERNS = (
        r"(?<!\w)post(?:s|ed|ing)?\s+on\s+x(?!\w)",
        r"(?<!\w)x\s+account(?:s)?(?!\w)",
        r"(?<!\w)x\s+feed(?:s)?(?!\w)",
        r"(?<!\w)x\s+post(?:s)?(?!\w)",
        r"(?<!\w)on\s+x(?!\w)",
        r"^\s*(?:please\s+)?(?:post|publish|tweet)\s+(?:this\s+)?(?:to|on)\s+x(?!\w)",
    )

    def __init__(
        self,
        vault_root: Path,
        x_service: XCapabilityService | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.vault_root = Path(vault_root)
        self.tool_registry = tool_registry
        self.x_service = x_service or (None if tool_registry is not None else XCapabilityService())

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._X_CONTEXT_PATTERNS
        )

    def answer(self, query: str) -> SpecialistResponse:
        lowered = query.lower()
        if self._is_bookmarks_query(lowered):
            return self._answer_bookmarks()
        if self._is_account_query(lowered):
            return self._answer_account()
        if self._is_image_post_query(lowered):
            return self._answer_image_post(query)
        if self._is_post_query(lowered):
            return self._answer_post(query)
        try:
            result = self._search_posts({"query": query, "max_results": 5})
        except Exception as exc:
            return SpecialistResponse(
                agent=self.name,
                status="error",
                summary="XAgent could not fetch X posts right now.",
                analysis=f"X search failed: {self._sanitize_error(exc)}",
                confidence=0.2,
            )
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="XAgent did not find matching X posts.",
                confidence=0.35,
            )
        lines = []
        sources = []
        for index, item in enumerate(items[:5], start=1):
            text = str(item.get("text") or "").strip()
            handle = str(item.get("handle") or "x").strip()
            url = str(item.get("url") or "").strip()
            lines.append(f"[{index}] @{handle}: {text}")
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=f"@{handle} on X",
                        path_or_url=url,
                        snippet=text[:500],
                        captured_at=str(item.get("created_at") or ""),
                        freshness="live",
                    )
                )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.search_posts through the shared X capability service.",
            sources=sources,
            confidence=0.75,
        )

    def _search_posts(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.search_posts", payload, agent_name=self.name)
        return self.x_service.search_posts(payload)

    def _account(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.account", payload, agent_name=self.name)
        return self.x_service.account(payload)

    def _bookmarks(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.bookmarks", payload, agent_name=self.name)
        return self.x_service.bookmarks(payload)

    def _publish_post(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.publish_post", payload, agent_name=self.name)
        return self.x_service.publish_post(payload)

    def _publish_post_with_media(self, payload: dict) -> dict:
        if self.tool_registry is not None:
            return self.tool_registry.invoke("x.publish_post_with_media", payload, agent_name=self.name)
        return self.x_service.publish_post_with_media(payload)

    def _answer_account(self) -> SpecialistResponse:
        try:
            result = self._account({})
        except Exception as exc:
            return self._error("XAgent could not read the X account right now.", exc)
        account = result.get("account", {})
        username = str(account.get("username") or account.get("name") or "").strip()
        summary = f"Authenticated X account: @{username}" if username else "Authenticated X account was found."
        return SpecialistResponse(agent=self.name, status="answered", summary=summary, analysis="Used x.account.", confidence=0.75)

    def _answer_bookmarks(self) -> SpecialistResponse:
        try:
            result = self._bookmarks({"max_results": 5})
        except Exception as exc:
            return self._error("XAgent could not read X bookmarks right now.", exc)
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(agent=self.name, status="needs_fetch", summary="XAgent did not find X bookmarks.", confidence=0.35)
        lines, sources = self._format_posts(items)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.bookmarks through the shared X capability service.",
            sources=sources,
            confidence=0.75,
        )

    def _answer_post(self, query: str) -> SpecialistResponse:
        text = self._extract_quoted_text(query)
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing.",
                confidence=0.4,
            )
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f'Confirm before I post this to X:\n\n"{text}"',
            analysis="Prepared x.publish_post and is waiting for explicit confirmation.",
            confidence=0.65,
            action_request={
                "action": "x.publish_post",
                "payload": {"text": text},
                "preview": text,
            },
            activity_events=[
                {"type": "tool_call_started", "label": "Preparing post...", "name": "agent_reach_x_prepare_post"},
            ],
        )

    def execute_action_request(self, action_request: dict) -> SpecialistResponse:
        action = str(action_request.get("action") or "")
        payload = action_request.get("payload") if isinstance(action_request.get("payload"), dict) else {}
        if action == "x.publish_post":
            return self._execute_publish_post(payload)
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary="XAgent cannot execute that pending X action.",
            confidence=0.3,
        )

    def _execute_publish_post(self, payload: dict) -> SpecialistResponse:
        text = str(payload.get("text") or "").strip()
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing.",
                confidence=0.4,
            )
        try:
            result = self._publish_post({"text": text, "confirm": True})
        except Exception as exc:
            return self._error("XAgent could not publish to X right now.", exc)
        tweet = result.get("tweet", {})
        tweet_id = str(tweet.get("id") or "").strip()
        summary = f"Posted to X: {tweet_id}" if tweet_id else "Posted to X."
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used x.publish_post.",
            confidence=0.8,
            activity_events=[
                {"type": "tool_call_started", "label": "Posting to X...", "name": "agent_reach_x_post"},
                {"type": "tool_call_completed", "label": "X action completed", "name": "agent_reach_x_completed", "status": "completed"},
            ],
        )

    def _answer_image_post(self, query: str) -> SpecialistResponse:
        text = self._extract_quoted_text(query)
        image_prompt = self._extract_image_prompt(query)
        if not text:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs the exact post text before publishing an image post.",
                confidence=0.4,
            )
        if not image_prompt:
            return SpecialistResponse(
                agent=self.name,
                status="blocked",
                summary="XAgent needs an image prompt before generating an X image post.",
                confidence=0.4,
            )
        try:
            result = self._publish_post_with_media({"text": text, "image_prompt": image_prompt, "confirm": True})
        except Exception as exc:
            return self._error("XAgent could not publish the image post to X right now.", exc)
        tweet = result.get("tweet", {})
        tweet_id = str(tweet.get("id") or "").strip()
        summary = f"Posted image to X: {tweet_id}" if tweet_id else "Posted image to X."
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used x.publish_post_with_media.",
            confidence=0.8,
        )

    def _format_posts(self, items: list[dict]) -> tuple[list[str], list[SpecialistSource]]:
        lines = []
        sources = []
        for index, item in enumerate(items[:5], start=1):
            text = str(item.get("text") or "").strip()
            handle = str(item.get("handle") or "x").strip()
            url = str(item.get("url") or "").strip()
            lines.append(f"[{index}] @{handle}: {text}" if handle else f"[{index}] {text}")
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=f"@{handle} on X",
                        path_or_url=url,
                        snippet=text[:500],
                        freshness="live",
                    )
                )
        return lines, sources

    def _error(self, summary: str, exc: Exception) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="error",
            summary=summary,
            analysis=self._sanitize_error(exc),
            confidence=0.2,
        )

    def _is_bookmarks_query(self, lowered_query: str) -> bool:
        return "bookmark" in lowered_query or "saved posts" in lowered_query

    def _is_account_query(self, lowered_query: str) -> bool:
        return bool(re.search(r"(?<!\w)(me|account|profile)\s+(?:on\s+)?x(?!\w)", lowered_query))

    def _is_post_query(self, lowered_query: str) -> bool:
        return bool(re.search(r"^\s*(?:please\s+)?(?:post|publish|tweet)\s+(?:this\s+)?(?:to|on)\s+x(?!\w)", lowered_query))

    def _is_image_post_query(self, lowered_query: str) -> bool:
        if self._is_post_query(lowered_query) and any(word in lowered_query for word in ("image", "photo", "picture", "generate")):
            return True
        return bool(
            re.search(
                r"^\s*(?:please\s+)?generate\s+an?\s+image\b.*\b(?:post|publish|tweet)\s+(?:it\s+)?(?:to|on)\s+x(?!\w)",
                lowered_query,
            )
        )

    def _extract_quoted_text(self, query: str) -> str:
        match = re.search(r'"([^"]+)"', query)
        if match:
            return match.group(1).strip()
        match = re.search(r"'([^']+)'", query)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_image_prompt(self, query: str) -> str:
        patterns = (
            r"generate\s+an?\s+image\s+of\s+(.+?)\s+and\s+(?:post|publish|tweet)",
            r"image\s+of\s+(.+?)\s+and\s+(?:post|publish|tweet)",
            r"photo\s+of\s+(.+?)\s+and\s+(?:post|publish|tweet)",
        )
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None

    def _sanitize_error(self, exc: Exception) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        message = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer|client[_-]?secret|password)\s*[:=]\s*\S+",
            r"\1=[redacted]",
            message,
        )
        message = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[redacted]", message)
        if not message:
            message = exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"[:160]
