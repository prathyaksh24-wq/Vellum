"""Public setup contracts for Brave Search and Context7. Secrets are write-only."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr

Provider = Literal['brave', 'context7']

class KeyedMcpStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    status: str = 'not_connected'
    message: str = ''
    auth_type: str = 'none'
    configured_key_available: bool = False
    identity_verified: bool = False
    account_name: str | None = None
    workspace_name: str | None = None
    verified_at: str | None = None
    mcp_tool_count: int = 0
    granted_scopes: list[str] = Field(default_factory=list)

class KeyedMcpTool(BaseModel):
    name: str
    description: str = ''
    input_schema: dict[str, Any]
    read_only: bool = False

class KeyedMcpCatalog(BaseModel):
    tools: list[KeyedMcpTool]

class StagedMcpKey(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: SecretStr = Field(min_length=8, max_length=4096, repr=False)

class McpKeyReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credential_id: str = Field(min_length=30, max_length=100)

class StagedMcpKeyResult(McpKeyReference):
    expires_in: int = 600
