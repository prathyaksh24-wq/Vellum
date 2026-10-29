"""Public, credential-free catalog returned by the plugin MCP API."""
from typing import Any

from pydantic import BaseModel, Field


class PublishedMcpTool(BaseModel):
    name: str
    description: str = ''
    input_schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False


class PublishedMcpCatalog(BaseModel):
    plugin_id: str
    connector: str
    tools: list[PublishedMcpTool]
