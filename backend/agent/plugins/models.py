from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PluginStatus:
    id: str
    name: str
    type: str
    category: str
    configured: bool
    status: str
    notes: str = ""
    capabilities: list[str] = field(default_factory=list)
    required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict:
        return asdict(self)
