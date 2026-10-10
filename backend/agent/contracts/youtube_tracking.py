"""Local, account-scoped creator monitoring contracts."""
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreatorRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_id: str = Field(default="", pattern=r"^(?:UC[A-Za-z0-9_-]{22})?$")
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    relationship: Literal["auto", "long_term", "seasonal", "current", "former", "excluded"] = "auto"
    topic_terms: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_identity(self):
        if not self.channel_id and self.relationship != "excluded":
            raise ValueError("Monitoring rules require a verified channel ID.")
        if any(len(term) > 100 or not term.strip() for term in self.aliases + self.topic_terms):
            raise ValueError("Aliases and topic terms must be short, nonempty strings.")
        return self


class CreatorTrackingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=200)
    # These are canonical source account IDs. Linking two accounts is explicit.
    history_accounts: list[str] = Field(min_length=1, max_length=5)
    enabled: bool = False
    rules: list[CreatorRule] = Field(default_factory=list, max_length=200)
    max_channels: int = Field(default=20, ge=1, le=100)
    requests_per_run: int = Field(default=8, ge=1, le=10)
    requests_per_day: int = Field(default=768, ge=1, le=1000)
    api_fallback: bool = True
    fallback_units_per_day: int = Field(default=1536, ge=0, le=2000)
    timezone: str = Field(default="UTC", max_length=100)

    @model_validator(mode="after")
    def validate_accounts_and_rules(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("A valid history timezone is required.") from None
        if any(not account.strip() or len(account) > 200 or any(ord(char) < 32 for char in account) for account in self.history_accounts):
            raise ValueError("History account IDs must be nonempty and bounded.")
        identities = [rule.channel_id or rule.name.casefold() for rule in self.rules]
        if len(identities) != len(set(identities)):
            raise ValueError("Each channel may have only one relationship rule.")
        return self


class CreatorTrackingRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)


class CreatorAssessment(BaseModel):
    channel_id: str
    name: str
    relationship: str
    state: str
    score: float
    recent_video_days: int
    recent_days: int
    total_video_days: int
    last_watched: str
    reason: str
    topic_terms: list[str] = Field(default_factory=list)


class CreatorTrackingSnapshot(BaseModel):
    contract_version: int = 1
    local_only: bool = True
    configured: bool = False
    enabled: bool = False
    account_id: str = ""
    creators: list[CreatorAssessment] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    uploads: list[dict[str, str]] = Field(default_factory=list)
    pending_attribution: int = 0
    unavailable_attribution: int = 0
    status: str = "not_configured"
    last_checked_at: str = ""
    monitored_channels: int = 0
    baselined_channels: int = 0
    warnings: list[str] = Field(default_factory=list)
    polling_limits: dict[str, int] = Field(default_factory=dict)
    coverage: str = "Saved watch history only; searches and recommendations do not endorse creators. Counts are distinct video/day records, not complete lifetime viewing. Topic-filtered creators count matching titles only."
