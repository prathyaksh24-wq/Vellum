"""Typed contracts for the dedicated local browser session."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
import base64
import struct


SearchEngine = Literal["google", "brave", "duckduckgo", "startpage", "searxng"]


class BrowserSearchEngineSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_engine: SearchEngine


AgentPermission = Literal["allow", "ask", "block"]
SitePermission = Literal["allow", "ask", "block"]


class BrowserSiteDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: SitePermission = "ask"
    camera: SitePermission = "ask"
    microphone: SitePermission = "ask"
    notifications: SitePermission = "block"
    javascript: Literal["allow", "block"] = "allow"
    images: Literal["allow", "block"] = "allow"
    popups: Literal["allow", "block"] = "block"
    third_party_cookies: Literal["allow", "block"] = "allow"


class BrowserSiteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str = Field(min_length=1, max_length=512)
    browsing: AgentPermission = "ask"
    downloads: AgentPermission = "ask"
    permissions: BrowserSiteDefaults | None = None
    updated_at: str = Field(default="", max_length=48)


class BrowserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=r"^(default|[a-f0-9]{32})$")
    name: str = Field(min_length=1, max_length=40)
    site_defaults: BrowserSiteDefaults = Field(default_factory=BrowserSiteDefaults)
    site_rules: list[BrowserSiteRule] = Field(default_factory=list, max_length=100)


class BrowserShortcut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=4096)


class BrowserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_engine: SearchEngine = "google"
    searxng_url: str = Field(default="", max_length=4096)
    suggestions_enabled: bool = True
    agent_enabled: bool = True
    agent_interactions: Literal["allow", "ask"] = "allow"
    cursor_style: Literal["classic", "light", "ember", "mint", "pixel", "custom"] = "classic"
    cursor_size: int = Field(default=28, ge=16, le=48)
    cursor_image: str = Field(default="", max_length=90000)
    cursor_hotspot_x: int = Field(default=0, ge=0, le=47)
    cursor_hotspot_y: int = Field(default=0, ge=0, le=47)

    @field_validator("cursor_image")
    @classmethod
    def validate_cursor_image(cls, value):
        if not value:
            return value
        if not value.startswith("data:image/png;base64,"):
            raise ValueError("Choose a PNG cursor image.")
        try:
            raw = base64.b64decode(value.split(",",1)[1], validate=True)
            width,height = struct.unpack(">II",raw[16:24])
            if raw[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' or len(raw)>65536 or not (1<=width<=128 and 1<=height<=128):
                raise ValueError()
        except (ValueError,struct.error):
            raise ValueError("Choose a PNG up to 128 × 128 pixels and 64 KB.") from None
        return value
    agent_browsing: AgentPermission = "allow"
    agent_downloads: AgentPermission = "ask"
    agent_history: Literal["allow", "block"] = "allow"
    agent_screenshots: Literal["allow", "block"] = "allow"
    show_full_url: bool = True
    web_link_destination: Literal["vellum", "default"] = "default"
    local_link_destination: Literal["vellum", "default"] = "default"
    download_directory: str = Field(default="", max_length=1024)
    ask_download_location: bool = False
    expire_site_permissions: bool = True
    active_profile_id: str = "default"
    profiles: list[BrowserProfile] = Field(default_factory=lambda: [BrowserProfile(id="default", name="Personal")], min_length=1, max_length=12)
    shortcuts: list[BrowserShortcut] = Field(default_factory=lambda: [
        BrowserShortcut(id="github", name="GitHub", url="https://github.com/"),
        BrowserShortcut(id="wikipedia", name="Wikipedia", url="https://www.wikipedia.org/"),
        BrowserShortcut(id="youtube", name="YouTube", url="https://www.youtube.com/"),
    ], max_length=12)


class BrowserControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["open", "close", "pause", "resume", "take_over", "navigate", "back", "forward", "reload", "new_tab", "select_tab", "close_tab", "click", "hover", "type", "press", "scroll", "show_download", "resize", "preferences"]
    search_engine: SearchEngine | None = None
    suggestions_enabled: bool | None = None
    searxng_url: str | None = Field(default=None, max_length=4096)
    shortcuts: list[BrowserShortcut] | None = Field(default=None, max_length=12)
    url: str = Field(default="", max_length=4096)
    tab_id: str = Field(default="", max_length=80)
    frame_id: str = Field(default="", max_length=160)
    take_control: bool = False
    download_id: str = Field(default="", max_length=80)
    x: float = Field(default=0, ge=0, le=1920)
    y: float = Field(default=0, ge=0, le=1080)
    text: str = Field(default="", max_length=10000)
    key: str = Field(default="", max_length=80)
    delta: int = Field(default=0, ge=-2000, le=2000)
    width: int = Field(default=1280, ge=240, le=1920)
    height: int = Field(default=800, ge=160, le=1080)


class BrowserTab(BaseModel):
    id: str
    index: int
    title: str
    url: str
    active: bool
    loading: bool = False
    error: str = ""


class BrowserAddressSuggestion(BaseModel):
    title: str = Field(max_length=512)
    url: str = Field(max_length=4096)


class BrowserAddressSuggestions(BaseModel):
    contract_version: int = 1
    items: list[BrowserAddressSuggestion] = Field(default_factory=list, max_length=8)
    queries: list[str] = Field(default_factory=list, max_length=8)
    search_engine: SearchEngine = "google"
    suggestion_status: Literal["idle", "ready", "unavailable", "off"] = "idle"


class BrowserDownload(BaseModel):
    id: str
    name: str
    state: Literal["downloading", "saved", "failed", "awaiting_approval", "blocked"]
    size: int = 0


class BrowserSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_engine: SearchEngine | None = None
    searxng_url: str | None = Field(default=None, max_length=4096)
    suggestions_enabled: bool | None = None
    agent_enabled: bool | None = None
    agent_interactions: Literal["allow", "ask"] | None = None
    cursor_style: Literal["classic", "light", "ember", "mint", "pixel", "custom"] | None = None
    cursor_size: int | None = Field(default=None, ge=16, le=48)
    cursor_image: str | None = Field(default=None, max_length=90000)
    cursor_hotspot_x: int | None = Field(default=None, ge=0, le=47)
    cursor_hotspot_y: int | None = Field(default=None, ge=0, le=47)
    agent_browsing: AgentPermission | None = None
    agent_downloads: AgentPermission | None = None
    agent_history: Literal["allow", "block"] | None = None
    agent_screenshots: Literal["allow", "block"] | None = None
    show_full_url: bool | None = None
    web_link_destination: Literal["vellum", "default"] | None = None
    local_link_destination: Literal["vellum", "default"] | None = None
    download_directory: str | None = Field(default=None, max_length=1024)
    ask_download_location: bool | None = None
    expire_site_permissions: bool | None = None


class BrowserSettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["preferences", "create_profile", "rename_profile", "select_profile", "open_profile", "close_profile", "delete_profile", "clear_data", "site_defaults", "site_rule", "remove_site_rule", "save_download", "remove_download"]
    profile_id: str = Field(default="", max_length=40, pattern=r"^(|default|[a-f0-9]{32})$")
    name: str = Field(default="", max_length=40)
    patch: BrowserSettingsPatch | None = None
    defaults: BrowserSiteDefaults | None = None
    rule: BrowserSiteRule | None = None
    origin: str = Field(default="", max_length=512)
    data_types: list[Literal["history", "cookies", "cache", "downloads"]] = Field(default_factory=list, max_length=4)
    download_id: str = Field(default="", max_length=80, pattern=r"^[a-zA-Z0-9_-]*$")
    directory: str = Field(default="", max_length=1024)


class BrowserActivity(BaseModel):
    id: str
    at: str
    event: str
    url: str = ""
    title: str = ""


class BrowserSettingsView(BaseModel):
    contract_version: int = 1
    preferences: BrowserPreferences
    running: bool
    history: list[BrowserAddressSuggestion] = Field(default_factory=list)
    downloads: list[BrowserDownload] = Field(default_factory=list)
    activity: list[BrowserActivity] = Field(default_factory=list)
    download_directory: str
    native_save_dialog: bool = False
    site_tools: bool = False


class BrowserNavigationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)
    snapshot_id: str = Field(default="", max_length=80)
    session_id: str = Field(min_length=1, max_length=80)
    goal: str = Field(default="", max_length=4000)
    confirm: bool = False


class BrowserPointer(BaseModel):
    tab_id: str = ""
    x: float = 0
    y: float = 0
    action: str = ""


class BrowserStatus(BaseModel):
    contract_version: int = 1
    render_transport: Literal['stream', 'native'] = 'stream'
    browser_name: str = 'Brave'
    native_target_id: str = ''
    available: bool
    reason: str = ""
    running: bool = False
    presentation_requested: bool = True
    presentation_revision: int = Field(default=0, ge=0)
    control: Literal["agent", "paused", "user", "closed"] = "closed"
    session_id: str = ""
    active_tab_id: str = ""
    tabs: list[BrowserTab] = Field(default_factory=list)
    downloads: list[BrowserDownload] = Field(default_factory=list)
    activity: str = ""
    pointer: BrowserPointer | None = None
    snapshot_id: str = ""
    viewport_width: int = 1280
    viewport_height: int = 800
    preferences: BrowserPreferences = Field(default_factory=BrowserPreferences)


class BrowserDesktopConfiguration(BaseModel):
    contract_version: int = 1
    workspace_root: str


class BrowserFrame(BaseModel):
    contract_version: int = 1
    frame_id: str
    tab_id: str
    width: int
    height: int
    data_url: str
    pointer: BrowserPointer | None = None


class BrowserStep(BaseModel):
    """A bounded local-model decision; never arbitrary code or OS commands."""
    model_config = ConfigDict(extra="forbid")
    action: Literal["navigate", "snapshot", "click", "type", "scroll", "press_key", "back", "forward", "reload", "close", "tabs", "done", "ask"]
    url: str = Field(default="", max_length=4096)
    ref: str = Field(default="", max_length=32)
    text: str = Field(default="", max_length=4000)
    key: str = Field(default="", max_length=80)
    direction: Literal["up", "down", "top", "bottom"] = "down"
    tab_action: Literal["list", "new", "select", "close"] = "list"
    index: str = Field(default="", max_length=12)
    summary: str = Field(default="", max_length=2000)
