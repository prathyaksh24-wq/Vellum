"""Google bundle selection, connection state, and API operation contracts."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

GoogleService = Literal["gmail", "drive", "calendar", "contacts"]


class GoogleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    services: list[GoogleService] = Field(max_length=4)
    force_signin: bool = False
    open_browser: bool = False
    access: Literal["read", "manage"] = "read"
    return_url: str = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"

    @field_validator("services")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Choose each Google service once.")
        return value

    @field_validator("return_url")
    @classmethod
    def local_return(cls, value):
        from agent.contracts.accounts import SignInRequest
        return SignInRequest(provider="google", return_url=value).return_url


class GoogleServiceStatus(BaseModel):
    id: GoogleService
    plugin_id: str
    name: str
    enabled: bool
    authorized: bool
    status: Literal["disabled", "not_connected", "needs_permission", "connected"]
    description: str
    can_write: bool = False
    operation_count: int = 0


class GoogleStatus(BaseModel):
    configured: bool
    connected: bool
    email: str = ""
    services: list[GoogleServiceStatus]
    message: str = ""


class GoogleFlow(BaseModel):
    flow_id: str = ""
    status: Literal["pending", "connected", "failed", "cancelled", "expired"]
    authorization_url: str = ""
    browser_opened: bool = False
    message: str = ""


class GoogleRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: GoogleService
    action: Literal["search", "message", "thread", "file"] = "search"
    query: str = Field(default="", max_length=2000)
    resource_id: str = Field(default="", max_length=512)
    limit: int = Field(default=20, ge=1, le=50)


class GoogleResult(BaseModel):
    service: GoogleService
    action: str
    result: dict[str, Any]


class GoogleApiOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: GoogleService
    method_id: str = Field(min_length=1, max_length=160)
    parameters: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    media_base64: str | None = Field(default=None, max_length=12_000_000)
    media_type: str = Field(default="application/octet-stream", max_length=150, pattern=r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


class GoogleApiQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: GoogleService
    query: str = Field(default="", max_length=300)
    method_id: str = Field(default="", max_length=160)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class GoogleApiCatalog(BaseModel):
    service: GoogleService
    total: int
    operation_count: int
    methods: list[dict[str, Any]]
    next_offset: int | None = None
    source: str
    revision: str


class GoogleApiDescription(BaseModel):
    service: GoogleService
    method_id: str
    description: str
    http_method: str
    read_only: bool
    scopes: list[str]
    parameters: dict[str, Any]
    body: dict[str, Any] | None = None
    supports_media_upload: bool
    supports_media_download: bool
    source: str
    revision: str


class GoogleApiResult(BaseModel):
    service: GoogleService
    method_id: str
    result: dict[str, Any]
    untrusted_provider_data: bool = True
