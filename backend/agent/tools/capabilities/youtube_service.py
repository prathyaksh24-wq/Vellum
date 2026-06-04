from __future__ import annotations

from typing import Any

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


class YoutubeCapabilityService:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        allowed_agents = frozenset({"YoutubeAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"})
        registry.register(
            CapabilityRecord(
                name="youtube.search_videos",
                namespace="youtube",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Searched YouTube",
                adapter=self.search_videos,
            )
        )
        registry.register(
            CapabilityRecord(
                name="youtube.get_transcript",
                namespace="youtube",
                access=CapabilityAccess.READ,
                allowed_agents=allowed_agents,
                stream_label="Read YouTube transcript",
                adapter=self.get_transcript,
            )
        )
        return registry

    def search_videos(self, payload: dict[str, Any]) -> dict[str, str]:
        return self._unsupported("youtube.search_videos")

    def get_transcript(self, payload: dict[str, Any]) -> dict[str, str]:
        return self._unsupported("youtube.get_transcript")

    def _unsupported(self, action: str) -> dict[str, str]:
        return {
            "action": action,
            "status": "unsupported",
            "message": "The read-only YouTube backend is not configured yet.",
        }
