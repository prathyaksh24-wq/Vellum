"""Read projection for the Scheduled workspace."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScheduledChatContext(BaseModel):
    task_id: str | None = Field(default=None, min_length=1, max_length=200)
    time_zone: str = Field(default="UTC", min_length=1, max_length=100)


class ScheduledTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    next_run_at: datetime | None = None
    schedule_ended: bool = False


class ScheduledTasks(BaseModel):
    automations: list[ScheduledTask]
    scheduler_available: bool


class ScheduledTaskSuggestion(BaseModel):
    name: str = Field(max_length=48)
    icon: str = Field(max_length=24)
    request: str = Field(max_length=280)
    reason: str = Field(default="", max_length=120)


class ScheduledTaskSuggestions(BaseModel):
    """Task ideas for the Scheduled page, learned from the user or starter ideas."""

    suggestions: list[ScheduledTaskSuggestion]
    source: str  # "learned" | "starter"
    status: str  # "ready" | "refreshing" | "unavailable"
    reason: str = ""
    generated_at: datetime | None = None
