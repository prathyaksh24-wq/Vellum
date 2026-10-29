"""Public contracts for Swiggy's official MCP connection; no token inputs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SwiggyOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    popup: bool = True

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="github", return_url=value).return_url


class SwiggyServiceStatus(BaseModel):
    id: Literal['food', 'instamart']
    name: str
    enabled: bool
    connected: bool
    tool_count: int = 0


class SwiggySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    services: list[Literal['food', 'instamart']] = Field(max_length=2)

    @field_validator('services')
    @classmethod
    def unique_services(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Choose each Swiggy service once.')
        return value


class SwiggyStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = True
    status: str = "not_connected"
    message: str = "Sign in with Swiggy to connect Food and Instamart."
    auth_type: Literal["none", "oauth"] = "none"
    configured_key_available: bool = False
    identity_verified: bool = False
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)
    services: list[SwiggyServiceStatus] = Field(default_factory=list)


class SwiggyFlowStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class SwiggyFlowStart(SwiggyFlowStatus):
    authorization_url: str


class SwiggyMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class SwiggyMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    service: Literal['food', 'instamart'] | None = None
    original_name: str = ''


class SwiggyMcpCatalog(BaseModel):
    source: Literal["Official Swiggy MCP server"] = "Official Swiggy MCP server"
    tools: list[SwiggyMcpTool]


class SwiggyMcpResult(BaseModel):
    tool_name: str
    result: str
