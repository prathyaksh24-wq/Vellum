"""Local automation notifications, separate from conversations."""
from pydantic import BaseModel, Field


class AutomationNotification(BaseModel):
    id: str
    automation_id: str
    title: str
    message: str
    url: str = ""
    created_at: str
    read_at: str | None = None


class AutomationNotifications(BaseModel):
    contract_version: int = 1
    local_only: bool = True
    items: list[AutomationNotification] = Field(default_factory=list)
    unread_count: int = 0
    recent_unread_count: int = 0
    total_count: int = 0
    matched_count: int = 0
    offset: int = 0
    has_more: bool = False
    recent_hours: int = 24
    retention_per_automation: int = 200
