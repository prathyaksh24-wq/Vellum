"""Public, credential-free Product Hunt connection and read contracts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


PLUGIN_ID = "app-69b7bed23a9481919d2378ab225cddeb"


class ProductHuntCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=8, max_length=4096)


class ProductHuntStatus(BaseModel):
    enabled: bool
    configured: bool = False
    connected: bool = False
    status: str = "not_connected"
    verified_at: str | None = None
    message: str = "Connect Product Hunt to read launches, product details, and topics."
    access: Literal["public_read", "account_read"] = "public_read"
    account_access: Literal["not_checked", "available", "needs_permission"] = "not_checked"
    write_access: Literal["not_verified", "verified", "approval_required"] = "not_verified"


class ProductHuntRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["posts", "post", "topics", "viewer", "user", "account_posts", "account_collections"] = "posts"
    limit: int = Field(default=10, ge=1, le=20)
    after: str | None = Field(default=None, max_length=512)
    order: Literal["RANKING", "NEWEST", "VOTES"] = "RANKING"
    topic: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9-]+$")
    posted_after: str | None = Field(default=None, max_length=40)
    posted_before: str | None = Field(default=None, max_length=40)
    slug: str | None = Field(default=None, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")
    username: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    account_feed: Literal["voted", "made", "submitted"] = "voted"

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().removeprefix("@") if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_dates_and_slug(self):
        from datetime import datetime
        for value in (self.posted_after, self.posted_before):
            if value:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Use a timestamp with a time zone.")
        if self.operation == "post" and not self.slug:
            raise ValueError("A Product Hunt launch slug is required.")
        if self.operation == "user" and not self.username:
            raise ValueError("A Product Hunt username is required.")
        return self


class ProductHuntPost(BaseModel):
    id: str
    name: str
    slug: str
    tagline: str = ""
    description: str | None = None
    url: str = ""
    website: str = ""
    votesCount: int = 0
    commentsCount: int = 0
    createdAt: str = ""


class ProductHuntTopic(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None


class ProductHuntResult(BaseModel):
    source: Literal["Product Hunt API v2"] = "Product Hunt API v2"
    operation: Literal["posts", "post", "topics", "viewer", "user", "account_posts", "account_collections"]
    posts: list[ProductHuntPost] = Field(default_factory=list)
    topics: list[ProductHuntTopic] = Field(default_factory=list)
    has_next_page: bool = False
    end_cursor: str | None = None
    user: "ProductHuntUser | None" = None
    collections: list["ProductHuntCollection"] = Field(default_factory=list)
    account_feed: Literal["voted", "made", "submitted"] | None = None
    data_visibility: Literal["public", "authenticated_account"] = "public"


class ProductHuntUser(BaseModel):
    id: str
    username: str
    name: str
    url: str
    headline: str | None = None
    isFollowing: bool = False
    isViewer: bool = False
    followersCount: int = 0
    followingCount: int = 0


class ProductHuntCollection(BaseModel):
    id: str
    name: str
    url: str
    description: str | None = None


class ProductHuntFollow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().removeprefix("@") if isinstance(value, str) else value


ProductHuntResult.model_rebuild()
