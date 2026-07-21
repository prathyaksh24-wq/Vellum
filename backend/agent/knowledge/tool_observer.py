"""Policy-bound conversion of successful tool results into local evidence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from agent.knowledge.models import (
    ContentAnnotationInput,
    ExternalPolicy,
    ObservationActor,
    Sensitivity,
    SourceItemInput,
)
from agent.knowledge.service import KnowledgeCore
from agent.tools.registry import CapabilityAccess, ToolInvocation


_X_STATUS_ID = re.compile(r"/(?:status|statuses)/(\d+)")


class KnowledgeToolObserver:
    """Observe successful reads without inferring preferences from agent actions."""

    def __init__(self, core: KnowledgeCore) -> None:
        self.core = core

    def __call__(self, invocation: ToolInvocation) -> None:
        if invocation.access != CapabilityAccess.READ:
            return
        source_ids: list[str] = []
        if invocation.namespace == "x":
            source_ids = self._record_x(invocation)
        elif invocation.namespace == "youtube":
            source_ids = self._record_youtube(invocation)
        self.core.record_tool_result(
            tool_name=invocation.name,
            payload=self._request_metadata(invocation.payload),
            result={
                "source_ids": source_ids,
                "item_count": self._item_count(invocation.result),
                "provider": str(invocation.result.get("provider") or ""),
            },
            actor=ObservationActor.AGENT,
            trigger="agent_tool",
        )

    def _record_x(self, invocation: ToolInvocation) -> list[str]:
        if invocation.name not in {"x.search_posts", "x.bookmarks", "x.timeline", "x.likes", "x.read_tweet"}:
            return []
        items = invocation.result.get("items")
        if not isinstance(items, list):
            single = invocation.result.get("tweet")
            items = [single] if isinstance(single, dict) else []
        private_activity = invocation.name in {"x.bookmarks", "x.timeline", "x.likes"}
        source_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("x_url") or item.get("tweet_url") or "")
            text = str(item.get("text") or item.get("body") or "")
            external_id = self._x_id(url) or str(item.get("id") or "") or self._digest(item)
            result = self.core.store.upsert_source(
                SourceItemInput(
                    kind="x_post",
                    external_id=external_id,
                    title=self._x_title(item, text),
                    content=json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2, default=str),
                    uri=url,
                    sensitivity=Sensitivity.PRIVATE if private_activity else Sensitivity.PUBLIC,
                    external_policy=ExternalPolicy.ALLOW_SCRUBBED,
                    trust="live_tool_result",
                    metadata={
                        "observed_via": invocation.name,
                        "agent_name": invocation.agent_name,
                        "preference_evidence": False,
                    },
                )
            )
            source_ids.append(str(result["source_id"]))
            self._annotate_x_observation(str(result["source_id"]), invocation)
        return source_ids

    def _annotate_x_observation(self, source_id: str, invocation: ToolInvocation) -> None:
        if invocation.name in {"x.likes", "x.bookmarks", "x.timeline"}:
            labels = ["ambiguous_engagement"]
            context = invocation.name.removeprefix("x.")
        else:
            labels = ["agent_selected"]
            context = "agent_search"
        self.core.store.upsert_content_annotation(
            ContentAnnotationInput(
                target_type="source",
                target_id=source_id,
                labels=labels,
                context=context,
                stance="unknown",
                intent="unknown",
                confidence=1.0,
                eligible_for_preference=False,
                eligible_for_style=False,
                metadata={"observed_via": invocation.name},
            )
        )

    def _record_youtube(self, invocation: ToolInvocation) -> list[str]:
        if invocation.name == "youtube.fetch_transcript":
            transcript = str(invocation.result.get("transcript") or "")
            video_id = str(invocation.result.get("video_id") or invocation.payload.get("video_id") or "").strip()
            if not transcript or not video_id:
                return []
            result = self.core.store.upsert_source(
                SourceItemInput(
                    kind="youtube_transcript",
                    external_id=video_id,
                    title=f"YouTube transcript {video_id}",
                    content=transcript,
                    uri=f"https://www.youtube.com/watch?v={video_id}",
                    sensitivity=Sensitivity.PUBLIC,
                    external_policy=ExternalPolicy.DENY_RAW,
                    trust="live_tool_result",
                    metadata={
                        "observed_via": invocation.name,
                        "agent_name": invocation.agent_name,
                        "preference_evidence": False,
                    },
                )
            )
            return [str(result["source_id"])]
        if invocation.name != "youtube.search_videos":
            return []
        items = invocation.result.get("items")
        if not isinstance(items, list):
            return []
        source_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("video_id") or "").strip()
            if not video_id:
                continue
            result = self.core.store.upsert_source(
                SourceItemInput(
                    kind="youtube_video",
                    external_id=video_id,
                    title=str(item.get("title") or f"YouTube video {video_id}"),
                    content=json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2, default=str),
                    uri=str(item.get("url") or f"https://www.youtube.com/watch?v={video_id}"),
                    sensitivity=Sensitivity.PUBLIC,
                    external_policy=ExternalPolicy.ALLOW_SCRUBBED,
                    trust="live_tool_result",
                    metadata={
                        "observed_via": invocation.name,
                        "agent_name": invocation.agent_name,
                        "preference_evidence": False,
                    },
                )
            )
            source_ids.append(str(result["source_id"]))
        return source_ids

    @staticmethod
    def _request_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if key in {"query", "video_id", "handle", "username", "max_results"}
        }

    @staticmethod
    def _item_count(result: dict[str, Any]) -> int:
        items = result.get("items")
        return len(items) if isinstance(items, list) else int(bool(result))

    @staticmethod
    def _x_id(url: str) -> str:
        match = _X_STATUS_ID.search(url)
        return match.group(1) if match else ""

    @staticmethod
    def _x_title(item: dict[str, Any], text: str) -> str:
        handle = str(item.get("handle") or item.get("username") or "").lstrip("@")
        prefix = f"@{handle}: " if handle else "X post: "
        return f"{prefix}{text[:180]}".strip()

    @staticmethod
    def _digest(value: Any) -> str:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
