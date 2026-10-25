"""Public contracts for Slack's official MCP connection; no token inputs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SlackAppRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = Field(pattern=r"^A[A-Z0-9]{6,32}$")
    client_id: str = Field(pattern=r"^[0-9]{3,32}\.[0-9]{3,32}$")


class SlackOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    popup: bool = True

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="github", return_url=value).return_url


class SlackStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = False
    status: str = "not_connected"
    message: str = "Set up a Slack app, then sign in to connect its official MCP server."
    app_id: str | None = None
    client_id: str | None = None
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)


class SlackFlowStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class SlackFlowStart(SlackFlowStatus):
    authorization_url: str


class SlackMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class SlackMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class SlackMcpCatalog(BaseModel):
    source: Literal["Official Slack MCP server"] = "Official Slack MCP server"
    tools: list[SlackMcpTool]


class SlackMcpResult(BaseModel):
    tool_name: str
    result: str


class SlackSetup(BaseModel):
    callback_url: str
    source_url: str = "https://docs.slack.dev/ai/slack-mcp-server/"
    manifest: dict[str, Any]
