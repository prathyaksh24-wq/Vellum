from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ConversationOrganizationPatch(BaseModel):
    assignment: Literal["automatic", "manual"] = "manual"
    space_id: str | None = None
    space_label: str | None = None
    topic_id: str | None = None
    topic_label: str | None = None

    @field_validator("space_id", "space_label", "topic_id", "topic_label")
    @classmethod
    def clean_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = " ".join(value.split()).strip()
        if not clean:
            return None
        if len(clean) > 80:
            raise ValueError("Organization labels must be 80 characters or fewer.")
        return clean


class ConversationProject(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    pinned: bool = False
    memory: Literal['default', 'project-only'] = 'default'
    sources: list[dict[str, Any]] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)
    created_at: str = ''
    updated_at: str = ''


class ConversationLibraryResponse(BaseModel):
    generated_at: str
    projects: list[ConversationProject] = Field(default_factory=list)
    spaces: list[dict[str, Any]] = Field(default_factory=list)
    smart_views: list[dict[str, Any]] = Field(default_factory=list)
    conversations: list[dict[str, Any]] = Field(default_factory=list)


class ConversationSearchResponse(BaseModel):
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)
    hits: list[dict[str, Any]] = Field(default_factory=list)


class ConversationOrganizationResponse(BaseModel):
    conversation: dict[str, Any]
    memory_index: dict[str, Any] = Field(default_factory=dict)
    obsidian_projection: dict[str, Any] = Field(default_factory=dict)
