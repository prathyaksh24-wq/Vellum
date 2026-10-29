"""Public contracts for Vercel's official MCP connection; no token inputs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VercelOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    popup: bool = True

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="github", return_url=value).return_url


class VercelStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = True
    status: str = "not_connected"
    message: str = "Sign in with Vercel to choose the workspace Vellum can access."
    auth_type: Literal["none", "oauth", "configured_api_key"] = "none"
    configured_key_available: bool = False
    identity_verified: bool = False
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)


class VercelFlowStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class VercelFlowStart(VercelFlowStatus):
    authorization_url: str


class VercelMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class VercelMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class VercelMcpCatalog(BaseModel):
    source: Literal["Official Vercel MCP server"] = "Official Vercel MCP server"
    tools: list[VercelMcpTool]


class VercelMcpResult(BaseModel):
    tool_name: str
    result: str
