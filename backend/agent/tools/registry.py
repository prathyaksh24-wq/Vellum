from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CapabilityAccess(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL_WRITE = "external_write"


class ToolPermissionError(PermissionError):
    pass


CapabilityAdapter = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class CapabilityRecord:
    name: str
    namespace: str
    access: CapabilityAccess
    allowed_agents: frozenset[str]
    stream_label: str
    adapter: CapabilityAdapter
    requires_confirmation: bool = False
    required_env_flags: frozenset[str] = frozenset()


class ToolRegistry:
    def __init__(self) -> None:
        self._records: dict[str, CapabilityRecord] = {}

    def register(self, record: CapabilityRecord) -> None:
        self._records[record.name] = record

    def get(self, name: str) -> CapabilityRecord:
        return self._records[name]

    def names(self) -> list[str]:
        return sorted(self._records)

    def invoke(self, name: str, payload: dict[str, Any], *, agent_name: str) -> dict[str, Any]:
        record = self.get(name)
        self._check_permission(record, payload, agent_name=agent_name)
        return record.adapter(payload)

    def _check_permission(self, record: CapabilityRecord, payload: dict[str, Any], *, agent_name: str) -> None:
        if agent_name not in record.allowed_agents:
            raise ToolPermissionError(f"{agent_name} cannot use {record.name}")
        if record.requires_confirmation and payload.get("confirm") is not True:
            raise ToolPermissionError(f"{record.name} requires explicit confirmation")
