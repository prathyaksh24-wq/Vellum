"""Typed contracts for the dedicated local browser session."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class BrowserControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["open", "close", "pause", "resume", "take_over", "navigate", "back", "forward", "reload", "new_tab", "select_tab", "close_tab", "click", "type", "press", "scroll", "show_download"]
    url: str = Field(default="", max_length=4096)
    tab_id: str = Field(default="", max_length=80)
    frame_id: str = Field(default="", max_length=160)
    download_id: str = Field(default="", max_length=80)
    x: float = Field(default=0, ge=0, le=1920)
    y: float = Field(default=0, ge=0, le=1080)
    text: str = Field(default="", max_length=10000)
    key: str = Field(default="", max_length=80)
    delta: int = Field(default=0, ge=-2000, le=2000)


class BrowserTab(BaseModel):
    id: str
    index: int
    title: str
    url: str
    active: bool


class BrowserDownload(BaseModel):
    id: str
    name: str
    state: Literal["downloading", "saved", "failed"]
    size: int = 0


class BrowserStatus(BaseModel):
    contract_version: int = 1
    available: bool
    reason: str = ""
    running: bool = False
    control: Literal["agent", "paused", "user", "closed"] = "closed"
    session_id: str = ""
    active_tab_id: str = ""
    tabs: list[BrowserTab] = Field(default_factory=list)
    downloads: list[BrowserDownload] = Field(default_factory=list)
    activity: str = ""
    snapshot_id: str = ""
    viewport_width: int = 1280
    viewport_height: int = 800


class BrowserFrame(BaseModel):
    contract_version: int = 1
    frame_id: str
    tab_id: str
    width: int
    height: int
    data_url: str


class BrowserStep(BaseModel):
    """A bounded local-model decision; never arbitrary code or OS commands."""
    model_config = ConfigDict(extra="forbid")
    action: Literal["navigate", "snapshot", "click", "type", "scroll", "press_key", "back", "forward", "reload", "close", "tabs", "done", "ask"]
    url: str = Field(default="", max_length=4096)
    ref: str = Field(default="", max_length=32)
    text: str = Field(default="", max_length=4000)
    key: str = Field(default="", max_length=80)
    direction: Literal["up", "down"] = "down"
    tab_action: Literal["list", "new", "select", "close"] = "list"
    index: str = Field(default="", max_length=12)
    summary: str = Field(default="", max_length=2000)
