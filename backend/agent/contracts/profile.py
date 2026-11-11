"""Device-local profile details and the activity read projection."""

from datetime import date, datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayName: str = Field(default="", max_length=120)
    username: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=254)
    website: str = Field(default="", max_length=2048)
    accountId: str = Field(default="", max_length=200)

    @field_validator("displayName", "username", "email", "website", "accountId", mode="before")
    @classmethod
    def trim(cls, value):
        if not isinstance(value, str):
            raise ValueError("Profile details must be text.")
        return value.strip()

    @field_validator("displayName")
    @classmethod
    def name(cls, value: str) -> str:
        if not value:
            raise ValueError("Enter a display name.")
        return value

    @field_validator("email")
    @classmethod
    def contact_email(cls, value: str) -> str:
        if value and (value.count("@") != 1 or any(char.isspace() for char in value)
                      or not all(value.split("@"))):
            raise ValueError("Enter a valid contact email.")
        return value

    @field_validator("website")
    @classmethod
    def website_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use a website beginning with https:// or http://.")
        return value


class ProfileActivityDay(BaseModel):
    date: date
    count: int = Field(ge=0)


class ProfileActivityItem(BaseModel):
    id: str
    at: datetime
    label: str
    status: str


class ProfileActivity(BaseModel):
    time_zone: str
    today: date
    days: list[ProfileActivityDay]
    recent: list[ProfileActivityItem]
    selected_date: date
    selected_items: list[ProfileActivityItem]
