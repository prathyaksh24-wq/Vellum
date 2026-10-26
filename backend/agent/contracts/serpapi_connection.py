"""Public contracts for SerpAPI's official MCP connection; no token inputs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SerpApiStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = False
    status: str = "not_connected"
    message: str = "Sign in with SerpAPI to choose the workspace Vellum can access."
    auth_type: Literal["none", "oauth", "configured_api_key", "api_key"] = "none"
    configured_key_available: bool = False
    identity_verified: bool = False
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)


class SerpApiMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class SerpApiMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class SerpApiMcpCatalog(BaseModel):
    source: Literal["Official SerpAPI MCP server"] = "Official SerpAPI MCP server"
    tools: list[SerpApiMcpTool]


class SerpApiMcpResult(BaseModel):
    tool_name: str
    result: str
