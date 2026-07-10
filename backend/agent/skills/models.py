from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SKILL_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
PlatformName = Literal["windows", "linux", "macos"]


class ConfigSetting(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    default: Any = None
    prompt: str | None = None


class BlueprintMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    schedule: str = Field(min_length=1)
    deliver: str = "origin"
    prompt: str | None = None
    no_agent: bool = False


class HermesMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    tags: list[str] = Field(default_factory=list)
    category: str = "uncategorized"
    related_skills: list[str] = Field(default_factory=list)
    requires_toolsets: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    fallback_for_toolsets: list[str] = Field(default_factory=list)
    fallback_for_tools: list[str] = Field(default_factory=list)
    config: list[ConfigSetting] = Field(default_factory=list)
    blueprint: BlueprintMetadata | None = None


class VellumMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: list[str] = Field(default_factory=list)
    negative_trigger: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    route_to_agent: str | None = None
    routing_critical: bool = False


class MetadataExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")

    hermes: HermesMetadata = Field(default_factory=HermesMetadata)
    vellum: VellumMetadata = Field(default_factory=VellumMetadata)


class EnvironmentRequirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    prompt: str | None = None
    help: str | None = None
    required_for: str | None = None


class CredentialRequirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = Field(min_length=1)
    description: str | None = None

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        posix = PurePosixPath(value.replace("\\", "/"))
        windows = PureWindowsPath(value)
        if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts:
            raise ValueError("credential path must be relative and cannot traverse")
        return value


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = Field(min_length=1)
    version: str | None = None
    author: str | None = None
    license: str | None = None
    platforms: list[PlatformName] = Field(default_factory=list)
    metadata: MetadataExtensions = Field(default_factory=MetadataExtensions)
    required_environment_variables: list[EnvironmentRequirement] = Field(default_factory=list)
    required_credential_files: list[CredentialRequirement] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SKILL_NAME.fullmatch(value):
            raise ValueError("skill name must match ^[a-z][a-z0-9_-]*$")
        return value


class SkillPackage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    root: Path
    skill_file: Path
    metadata: SkillMetadata
    body: str
    state: Literal["active", "proposed", "retired", "archived"] = "active"
    source_root: Path
    is_external: bool = False


class SkillIndexEntry(BaseModel):
    name: str
    description: str
    category: str
    state: str
    available: bool
    unavailable_reason: str | None = None
    package_root: str
    is_external: bool


class SkillUsage(BaseModel):
    view_count: int = 0
    use_count: int = 0
    patch_count: int = 0
    last_viewed_at: datetime | None = None
    last_used_at: datetime | None = None
    last_patched_at: datetime | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    state: str = "active"
    pinned: bool = False
    archived_at: datetime | None = None
