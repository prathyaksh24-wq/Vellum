"""Local account identity contracts. Provider credentials never cross this boundary."""
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


Provider = Literal["google", "github"]
IdentityProvider = Literal["google", "github", "email"]
SignInMethod = Literal["redirect", "device"]
DEFAULT_RETURN_URL = "http://localhost:5173/design-uploads/Vellum%20Default%20Re-designed.html"


class Account(BaseModel):
    id: str
    provider: IdentityProvider
    display_name: str
    username: str = ""
    email: str = ""


class AccountProvider(BaseModel):
    id: Provider
    name: str
    available: bool
    reason: str = ""
    method: SignInMethod = "redirect"


class AccountStatus(BaseModel):
    contract_version: int = 1
    accounts: list[Account] = Field(default_factory=list)
    active_account_id: str | None = None
    providers: list[AccountProvider] = Field(default_factory=list)
    storage_available: bool = True
    logged_out: bool = False
    email_auth_available: bool = False
    email_auth_reason: str = "Email sign-in is not available yet."


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider
    return_url: str = Field(default=DEFAULT_RETURN_URL, max_length=512)
    open_browser: bool = True

    @field_validator("return_url")
    @classmethod
    def local_vellum_page(cls, value: str) -> str:
        target = urlsplit(value)
        origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 4242)}
        paths = {"/", "/design-uploads/Vellum Default Re-designed.html"}
        if (f"{target.scheme}://{target.netloc}" not in origins or unquote(target.path) not in paths
                or target.fragment or target.query not in {"", "desktop=1"}):
            raise ValueError("Sign-in must return to the local Vellum page.")
        return value


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=100)


class SignInFlow(BaseModel):
    flow_id: str
    provider: IdentityProvider
    status: Literal["pending", "complete", "failed", "cancelled", "expired"]
    authorization_url: str = ""
    user_code: str = ""
    interval: int = 2
    browser_opened: bool = False
    message: str = ""
    method: SignInMethod = "redirect"


class FlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow_id: str = Field(min_length=20, max_length=200)


class EmailCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: SecretStr


class EmailSignUp(EmailCredentials):
    return_url: str = Field(default=DEFAULT_RETURN_URL, max_length=512)

    @field_validator("return_url")
    @classmethod
    def local_vellum_page(cls, value: str) -> str:
        return SignInRequest(provider="google", return_url=value).return_url


class EmailSignUpResult(BaseModel):
    status: Literal["complete", "confirmation_required"]
    message: str
    flow: SignInFlow | None = None
