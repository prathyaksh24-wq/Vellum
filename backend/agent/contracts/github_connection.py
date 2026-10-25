"""Credential-free GitHub plugin contracts."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitHubConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    access: Literal["read", "manage"] = "manage"
    popup: bool = True

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value: str) -> str:
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="github", return_url=value).return_url


class GitHubConnectionStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = False
    status: str = "not_connected"
    message: str = "Sign in with GitHub to connect repositories, issues, pull requests and more."
    account_name: str | None = None
    login: str | None = None
    verified_at: str | None = None
    access: Literal["read", "manage"] = "read"
    cli_available: bool = False
    primary_transport: str = "GitHub CLI"
    fallback_transport: str = "Official GitHub MCP server"
    mcp_tool_count: int = 0


class GitHubFlowStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class GitHubFlowStart(GitHubFlowStatus):
    authorization_url: str


class GitHubMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class GitHubMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class GitHubMcpCatalog(BaseModel):
    source: Literal["Official GitHub MCP server"] = "Official GitHub MCP server"
    tools: list[GitHubMcpTool]


class GitHubMcpResult(BaseModel):
    tool_name: str
    result: str
