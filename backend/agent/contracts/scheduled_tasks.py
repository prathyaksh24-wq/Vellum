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
