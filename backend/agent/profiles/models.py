from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolPolicy(ProfileModel):
    allow: list[str] = Field(default_factory=list)
    require_confirmation: list[str] = Field(default_factory=list)


class SkillPolicy(ProfileModel):
    directories: list[str] = Field(default_factory=list)


class MemoryPolicy(ProfileModel):
    read_scopes: list[str] = Field(default_factory=list)
    write_scope: str = ""
    shared_writes: Literal["propose_only", "disabled"] = "propose_only"
    cache_first: bool = True


class CachePolicy(ProfileModel):
    default_ttl_seconds: int = Field(default=21600, ge=0)
    live_ttl_seconds: int = Field(default=120, ge=0)
    historical_ttl_seconds: int = Field(default=2592000, ge=0)
    bypass_terms: list[str] = Field(default_factory=lambda: ["live", "latest", "today", "now"])


class DelegationPolicy(ProfileModel):
    max_iterations: int = Field(default=30, ge=1)
    timeout_seconds: int = Field(default=0, ge=0)
    can_delegate: bool = False


class AgentProfile(ProfileModel):
    version: int = Field(default=1, ge=1)
    id: str = Field(min_length=1)
    description: str = ""
    executor: Literal["deterministic", "llm"] = "deterministic"
    model: str | None = None
    instructions: str = ""
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    skills: SkillPolicy = Field(default_factory=SkillPolicy)
    memory: MemoryPolicy = Field(default_factory=MemoryPolicy)
    cache: CachePolicy = Field(default_factory=CachePolicy)
    delegation: DelegationPolicy = Field(default_factory=DelegationPolicy)

    @model_validator(mode="after")
    def validate_boundaries(self) -> "AgentProfile":
        expected_scope = f"agent:{self.id}"
        if self.id not in {"VellumAgent", "MemoryAgent"} and self.memory.write_scope not in {"", expected_scope}:
            raise ValueError(f"write_scope must be {expected_scope}")
        if self.executor == "llm" and self.tools.allow:
            raise ValueError("llm profiles are reasoning-only and cannot declare tools")
        return self


def _profile(
    profile_id: str,
    description: str,
    *,
    tools: list[str],
    cache: CachePolicy | None = None,
) -> AgentProfile:
    return AgentProfile(
        id=profile_id,
        description=description,
        tools=ToolPolicy(allow=tools),
        memory=MemoryPolicy(
            read_scopes=["user_profile", "shared", f"agent:{profile_id}"],
            write_scope=f"agent:{profile_id}",
        ),
        cache=cache or CachePolicy(),
    )


def builtin_profiles() -> dict[str, AgentProfile]:
    x_tools = [
        "x.search_posts",
        "x.account",
        "x.bookmarks",
        "x.timeline",
        "x.likes",
        "x.profile",
        "x.read_tweet",
        "x.publish_post",
        "x.publish_post_with_media",
        "x.reply",
        "x.like",
        "x.repost",
        "x.delete",
    ]
    return {
        "SportsAgent": _profile(
            "SportsAgent",
            "Sports research, schedules, results, and analysis.",
            tools=[],
        ),
        "XAgent": _profile(
            "XAgent",
            "X search, account reads, and confirmed X actions.",
            tools=x_tools,
            cache=CachePolicy(
                bypass_terms=[
                    "live", "latest", "today", "now", "post", "publish", "tweet",
                    "delete", "remove", "like", "reply", "repost", "retweet",
                ]
            ),
        ),
        "YoutubeAgent": _profile(
            "YoutubeAgent",
            "YouTube search, metadata, transcripts, and summaries.",
            tools=["youtube.search_videos", "youtube.fetch_transcript"],
        ),
        "MemoryAgent": AgentProfile(
            id="MemoryAgent",
            description="Durable memory lookup and reviewed memory proposals.",
            tools=ToolPolicy(
                allow=[
                    "memory.build_context_pack",
                    "memory.search_cards",
                    "memory.review_proposals",
                    "memory.detect_conflicts",
                    "memory.create_card",
                    "memory.propose_card",
                ]
            ),
            memory=MemoryPolicy(
                read_scopes=["user_profile", "shared", "agent:MemoryAgent"],
                write_scope="agent:MemoryAgent",
            ),
            cache=CachePolicy(
                default_ttl_seconds=2592000,
                bypass_terms=["remember", "memorize", "note", "forget", "delete"],
            ),
        ),
    }
