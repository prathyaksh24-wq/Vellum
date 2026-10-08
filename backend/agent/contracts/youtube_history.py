"""Contracts for local, browser-derived YouTube history."""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HISTORY_URL = "https://www.youtube.com/feed/history"


class YouTubeHistoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(default=HISTORY_URL, max_length=2000)
    timezone: str = Field(default="UTC", max_length=80)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname not in {"www.youtube.com", "youtube.com"}
                or parsed.username or parsed.password or parsed.port not in {None, 443}
                or parsed.query or parsed.fragment or not parsed.path.startswith("/feed/")):
            raise ValueError("Use an HTTPS YouTube /feed/ history URL without credentials or query parameters.")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Select a valid IANA timezone.") from None
        return value


class YouTubeHistoryStatus(BaseModel):
    contract_version: int = 1
    config: YouTubeHistoryConfig = Field(default_factory=YouTubeHistoryConfig)
    status: str = "not_refreshed"
    last_success_at: str = ""
    last_attempt_at: str = ""
    message: str = "Open History in Vellum's browser and sign into YouTube."
    records: int = 0
    account_bound: bool = False
    coverage: Literal["recent_loaded_history"] = "recent_loaded_history"
    local_only: bool = True


class BrowserHistoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = Field(max_length=500)
    channel_title: str = Field(default="", max_length=200)
    channel_id: str = Field(default="", max_length=100)
    day_label: str = Field(default="", max_length=100)
    url: str = ""


class BrowserHistorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "empty", "signed_out", "account_unknown", "account_changed", "page_unreadable"]
    account_id: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    items: list[BrowserHistoryItem] = Field(default_factory=list, max_length=100)
    coverage: Literal["recent_page"] = "recent_page"
    timezone: str = Field(default="UTC", max_length=80)
    truncated: bool = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return YouTubeHistoryConfig(timezone=value).timezone


class BrowserHistoryReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)
    channel: str = Field(default="", max_length=200)
    day_label: Literal["", "Today", "Yesterday"] = ""
