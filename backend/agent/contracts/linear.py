"""Credential-free contracts for Linear's official MCP connection."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PLUGIN_ID = "linear"


class LinearStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    status: str = "not_connected"
    message: str = "Sign in with Linear to connect its official MCP server."
    verified_at: str | None = None
    account_name: str | None = None
    workspace_name: str | None = None
    read_access: str = "not_verified"
    write_access: str = "not_verified"
    auth_type: Literal["oauth"] = "oauth"
    mcp_tool_count: int = 0
    mcp_status: str = "not_checked"
    reconnect_required: bool = False


class LinearOAuthStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class LinearOAuthStart(BaseModel):
    flow_id: str
    authorization_url: str


class LinearOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    popup: bool = False

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="google", return_url=value).return_url




class LinearMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=150, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class LinearMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class LinearMcpCatalog(BaseModel):
    source: Literal["Linear official MCP server"] = "Linear official MCP server"
    endpoint: Literal["https://mcp.linear.app/mcp"] = "https://mcp.linear.app/mcp"
    tools: list[LinearMcpTool]


class LinearMcpResult(BaseModel):
    source: Literal["Linear official MCP server"] = "Linear official MCP server"
    tool_name: str
    result: str


class LinearReviewField(BaseModel):
    label: str
    value: str


class LinearActionPreview(BaseModel):
    heading: str
    confirm_label: str
    title: str = ""
    description: str = ""
    description_note: str = "No description supplied."
    workspace: str
    fields: list[LinearReviewField] = Field(default_factory=list)
