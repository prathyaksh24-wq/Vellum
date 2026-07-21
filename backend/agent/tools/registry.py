from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent.profiles.policy import get_active_profile_policy


class CapabilityAccess(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL_WRITE = "external_write"


class ToolPermissionError(PermissionError):
    pass


CapabilityAdapter = Callable[[dict[str, Any]], dict[str, Any]]


logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    namespace: str
    access: CapabilityAccess
    agent_name: str
    payload: dict[str, Any]
    result: dict[str, Any]


ToolInvocationObserver = Callable[[ToolInvocation], None]


class ToolRegistry:
    def __init__(self, *, observer: ToolInvocationObserver | None = None) -> None:
        self._records: dict[str, CapabilityRecord] = {}
        self._observer = observer

    def register(self, record: CapabilityRecord) -> None:
        if record.name in self._records:
            raise ValueError(f"{record.name} is already registered")
        self._records[record.name] = record

    def get(self, name: str) -> CapabilityRecord:
        return self._records[name]

    def names(self) -> list[str]:
        return sorted(self._records)

    def invoke(self, name: str, payload: dict[str, Any], *, agent_name: str) -> dict[str, Any]:
        record = self.get(name)
        self._check_permission(record, payload, agent_name=agent_name)
        result = record.adapter(payload)
        if self._observer is not None:
            try:
                self._observer(
                    ToolInvocation(
                        name=record.name,
                        namespace=record.namespace,
                        access=record.access,
                        agent_name=agent_name,
                        payload=dict(payload),
                        result=result,
                    )
                )
            except Exception:
                logger.exception("Tool observation failed for %s.", record.name)
        return result

    def _check_permission(self, record: CapabilityRecord, payload: dict[str, Any], *, agent_name: str) -> None:
        if agent_name not in record.allowed_agents:
            raise ToolPermissionError(f"{agent_name} cannot use {record.name}")
        policy = get_active_profile_policy()
        if policy is not None and record.name not in policy.allowed_tools:
            raise ToolPermissionError(
                f"{record.name} is not allowed by active profile policy {policy.profile_id}"
            )
        requires_confirmation = record.requires_confirmation or record.access == CapabilityAccess.EXTERNAL_WRITE
        if requires_confirmation and payload.get("confirm") is not True:
            raise ToolPermissionError(f"{record.name} requires explicit confirmation")
