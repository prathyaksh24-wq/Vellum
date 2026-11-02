"""Local desktop/backend handshake; no credentials or application content."""
from typing import Literal

from pydantic import BaseModel


class DesktopRuntimeIdentity(BaseModel):
    service: Literal["vellum"] = "vellum"
    protocol_version: Literal[1] = 1
    workspace_root: str
    build_id: str
    pid: int
    launch_id: str | None = None
