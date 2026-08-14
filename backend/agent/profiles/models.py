from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolPolicy(ProfileModel):
    allow: list[str] = Field(default_factory=list)
    require_confirmation: list[str] = Field(default_factory=list)


class InstructionPolicy(ProfileModel):
    inline: str = ""
    files: list[str] = Field(default_factory=list)


class SkillPolicy(ProfileModel):
    allow: list[str] = Field(default_factory=list)


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
    can_receive: bool = True
    can_delegate: bool = False
    max_depth: int = Field(default=1, ge=0)
    max_iterations: int = Field(default=30, ge=1)
    timeout_seconds: int = Field(default=0, ge=0)


class AgentProfile(ProfileModel):
    version: int = Field(default=2, ge=2)
    id: str = Field(min_length=1)
    description: str = ""
    executor: Literal["deterministic", "llm"] = "deterministic"
    model: str | None = None
    instructions: InstructionPolicy = Field(default_factory=InstructionPolicy)
    tools: ToolPolicy = Field(default_factory=ToolPolicy)
    skills: SkillPolicy = Field(default_factory=SkillPolicy)
    memory: MemoryPolicy = Field(default_factory=MemoryPolicy)
    cache: CachePolicy = Field(default_factory=CachePolicy)
    delegation: DelegationPolicy = Field(default_factory=DelegationPolicy)
    response_schema: str = Field(default="specialist-response-v1", min_length=1)

    @model_validator(mode="after")
    def validate_boundaries(self) -> "AgentProfile":
        expected_scope = f"agent:{self.id}"
        if self.id != "VellumAgent" and self.memory.write_scope not in {"", expected_scope}:
            raise ValueError(f"write_scope must be {expected_scope}")
        undeclared_confirmations = set(self.tools.require_confirmation) - set(self.tools.allow)
        if undeclared_confirmations:
            raise ValueError("confirmation-required tools must also appear in tools.allow")
        if self.executor == "llm" and self.tools.allow:
            raise ValueError("LLM profile tools are not supported until the allowlisted tool loop is available")
        return self


def _profile(
    profile_id: str,
    description: str,
    *,
    instructions: str,
    tools: list[str],
    skills: list[str],
    cache: CachePolicy | None = None,
    cache_first: bool = True,
) -> AgentProfile:
    return AgentProfile(
        id=profile_id,
        description=description,
        instructions=InstructionPolicy(inline=instructions),
        tools=ToolPolicy(allow=tools),
        skills=SkillPolicy(allow=skills),
        memory=MemoryPolicy(
            read_scopes=["user_profile", "shared", f"agent:{profile_id}"],
            write_scope=f"agent:{profile_id}",
            cache_first=cache_first,
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
            instructions="Research sports facts and analysis using profile-approved capabilities.",
            tools=["sports.web_search"],
            skills=["skill-route-sports-agent-v1", "skill-sports-memory-v1"],
        ),
        "XAgent": _profile(
            "XAgent",
            "X search, account reads, and confirmed X actions.",
            instructions="Handle X reads and confirmation-bound writes without widening permissions.",
            tools=x_tools,
            skills=[],
            cache=CachePolicy(
                bypass_terms=[
                    "live",
                    "latest",
                    "today",
                    "now",
                    "post",
                    "publish",
                    "tweet",
                    "delete",
                    "remove",
                    "like",
                    "reply",
                    "repost",
                    "retweet",
                ]
            ),
        ),
        "YoutubeAgent": _profile(
            "YoutubeAgent",
            "YouTube account, subscriptions, search, metadata, transcripts, and summaries.",
            instructions="Handle YouTube account data, discovery, metadata, transcripts, and summaries.",
            tools=[
                "youtube.account",
                "youtube.subscriptions",
                "youtube.liked_videos",
                "youtube.takeout_history",
                "youtube.personal_context",
                "youtube.subscription_feed",
                "youtube.search_videos",
                "youtube.fetch_transcript",
            ],
            skills=["skill-youtube-transcript-memory-v1"],
            cache_first=False,
        ),
        "MemoryAgent": AgentProfile(
            id="MemoryAgent",
            description="Durable memory lookup and reviewed memory proposals.",
            instructions=InstructionPolicy(
                inline="Retrieve durable memory and submit reviewed memory proposals."
            ),
            tools=ToolPolicy(
                allow=[
                    "memory.build_context_pack",
                    "memory.search_cards",
                    "memory.review_proposals",
                    "memory.detect_conflicts",
                    "memory.propose_card",
                ]
            ),
            skills=SkillPolicy(allow=["skill-retention-memory-v1"]),
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
