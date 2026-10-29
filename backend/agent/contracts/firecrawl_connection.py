"""Public contracts for Firecrawl's official MCP connection; no token inputs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FirecrawlOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    popup: bool = True

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="github", return_url=value).return_url


class FirecrawlStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = True
    status: str = "not_connected"
    message: str = "Sign in with Firecrawl to choose the workspace Vellum can access."
    auth_type: Literal["none", "oauth", "configured_api_key"] = "none"
    configured_key_available: bool = False
    identity_verified: bool = False
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)


class FirecrawlFlowStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class FirecrawlFlowStart(FirecrawlFlowStatus):
    authorization_url: str


class FirecrawlMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class FirecrawlMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class FirecrawlMcpCatalog(BaseModel):
    source: Literal["Official Firecrawl MCP server"] = "Official Firecrawl MCP server"
    tools: list[FirecrawlMcpTool]


class FirecrawlMcpResult(BaseModel):
    tool_name: str
    result: str
