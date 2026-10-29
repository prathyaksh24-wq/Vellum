"""Public contracts for Asana's official MCP connection; no token inputs."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class AsanaAppCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=1024)
    client_secret: SecretStr = Field(min_length=1, max_length=4096)

    @field_validator('client_id')
    @classmethod
    def valid_client(cls, value):
        if not value.isascii() or any(ord(char) <= 32 or ord(char) >= 127 for char in value):
            raise ValueError('Enter the Asana client ID from the connector details.')
        return value

    @field_validator('client_secret')
    @classmethod
    def valid_secret(cls, value):
        secret = value.get_secret_value()
        if not secret.isascii() or any(ord(char) <= 32 or ord(char) >= 127 for char in secret):
            raise ValueError('Enter the Asana client secret from the connector details.')
        return value


class AsanaStagedReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential_id: str = Field(min_length=30, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


class AsanaStagedCredential(AsanaStagedReference):
    expires_in: int = 600


class AsanaDiscardResult(BaseModel):
    discarded: bool = True


class AsanaOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    popup: bool = True

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="github", return_url=value).return_url


class AsanaStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    oauth_available: bool = False
    app_registered: bool = False
    status: str = "not_connected"
    message: str = "Sign in with Asana to choose the workspace Vellum can access."
    auth_type: Literal["none", "oauth"] = "none"
    configured_key_available: bool = False
    identity_verified: bool = False
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)


class AsanaFlowStatus(BaseModel):
    flow_id: str
    status: Literal["pending", "connected", "failed", "cancelled"]
    message: str


class AsanaFlowStart(AsanaFlowStatus):
    authorization_url: str


class AsanaMcpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class AsanaMcpTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


class AsanaMcpCatalog(BaseModel):
    source: Literal["Official Asana MCP server"] = "Official Asana MCP server"
    tools: list[AsanaMcpTool]


class AsanaMcpResult(BaseModel):
    tool_name: str
    result: str
