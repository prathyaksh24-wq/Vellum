from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.tools.capabilities.mcp_service import McpCapabilityService
    from agent.tools.capabilities.memory_service import MemoryCapabilityService
    from agent.tools.capabilities.x_service import XCapabilityService
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService

__all__ = [
    "MemoryCapabilityService",
    "McpCapabilityService",
    "XCapabilityService",
    "YoutubeCapabilityService",
]


def __getattr__(name: str):
    if name == "MemoryCapabilityService":
        from agent.tools.capabilities.memory_service import MemoryCapabilityService

        return MemoryCapabilityService
    if name == "McpCapabilityService":
        from agent.tools.capabilities.mcp_service import McpCapabilityService

        return McpCapabilityService
    if name == "XCapabilityService":
        from agent.tools.capabilities.x_service import XCapabilityService

        return XCapabilityService
    if name == "YoutubeCapabilityService":
        from agent.tools.capabilities.youtube_service import YoutubeCapabilityService

        return YoutubeCapabilityService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
