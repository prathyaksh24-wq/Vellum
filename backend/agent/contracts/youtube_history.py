"""Browser history is a bounded page observation, never a full watch ledger."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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
    coverage: str = "recent_page"
    truncated: bool = False


class BrowserHistoryReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)
    channel: str = Field(default="", max_length=200)
    day_label: Literal["", "Today", "Yesterday"] = ""
