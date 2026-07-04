from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry
from agent.tools.web import web_search


def build_shared_tool_registry(
    *,
    vault_root: Path,
    sessions_db: Path | None = None,
    x_service: XCapabilityService | None = None,
    youtube_service: YoutubeCapabilityService | None = None,
    memory_service: MemoryCapabilityService | None = None,
    mcp_service: McpCapabilityService | None = None,
    sports_searcher: Callable[[str], str | dict[str, Any]] | None = None,
) -> ToolRegistry:
    root = Path(vault_root)
    memory_sessions_db = sessions_db or root / "Agent" / "Memory" / "shared-tool-registry-sessions.db"
    services = (
        x_service or XCapabilityService(),
        youtube_service or YoutubeCapabilityService(vault_root=root),
        memory_service or MemoryCapabilityService(vault_root=root, sessions_db=memory_sessions_db),
        mcp_service or McpCapabilityService(),
    )
    registry = ToolRegistry()
    for service in services:
        _copy_records(registry, service.build_registry())
    search = sports_searcher or (lambda query: web_search.invoke({"query": query}))
    registry.register(
        CapabilityRecord(
            name="sports.search",
            namespace="sports",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"SportsAgent", "ResearchAgent", "VellumAgent"}),
            stream_label="Searched sports",
            adapter=lambda payload: search(str(payload["query"])),
        )
    )
    return registry


def _copy_records(target: ToolRegistry, source: ToolRegistry) -> None:
    for name in source.names():
        target.register(source.get(name))
