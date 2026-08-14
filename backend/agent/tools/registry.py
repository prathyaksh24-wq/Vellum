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


CapabilityAdapter = Callable[[dict[str, Any]], Any]


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
    runtime_tool: Any | None = None


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    namespace: str
    access: CapabilityAccess
    agent_name: str
    payload: dict[str, Any]
    result: Any


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

    def invoke(self, name: str, payload: dict[str, Any], *, agent_name: str) -> Any:
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

    def register_langchain(
        self,
        tool: Any,
        *,
        access: CapabilityAccess,
        allowed_agents: frozenset[str],
        namespace: str | None = None,
        stream_label: str | None = None,
        requires_confirmation: bool = False,
    ) -> None:
        """Register a LangChain tool without replacing its input schema or behavior."""
        name = str(tool.name)
        self.register(
            CapabilityRecord(
                name=name,
                namespace=namespace or name.split("_", 1)[0],
                access=access,
                allowed_agents=allowed_agents,
                requires_confirmation=requires_confirmation,
                stream_label=stream_label or name.replace("_", " ").strip().capitalize(),
                adapter=lambda payload, runtime_tool=tool: runtime_tool.invoke(payload),
                runtime_tool=tool,
            )
        )

    def langchain_tools(self, *, agent_name: str) -> list[Any]:
        """Return schema-preserving wrappers that authorize every invocation."""
        from langchain_core.tools import StructuredTool

        wrapped = []
        for record in self._records.values():
            tool = record.runtime_tool
            if tool is None:
                continue

            def invoke(_capability_name=record.name, **payload):
                return self.invoke(_capability_name, payload, agent_name=agent_name)

            wrapped.append(
                StructuredTool(
                    name=tool.name,
                    description=tool.description,
                    args_schema=tool.args_schema,
                    return_direct=tool.return_direct,
                    tags=tool.tags,
                    metadata=tool.metadata,
                    handle_tool_error=tool.handle_tool_error,
                    handle_validation_error=tool.handle_validation_error,
                    response_format=tool.response_format,
                    func=invoke,
                )
            )
        return wrapped

    def _check_permission(self, record: CapabilityRecord, payload: dict[str, Any], *, agent_name: str) -> None:
        if agent_name not in record.allowed_agents:
            raise ToolPermissionError(f"{agent_name} cannot use {record.name}")
        policy = get_active_profile_policy()
        if policy is not None and record.name not in policy.allowed_tools:
            raise ToolPermissionError(
                f"{record.name} is not allowed by active profile policy {policy.profile_id}"
            )
        profile_requires_confirmation = policy is not None and record.name in policy.require_confirmation
        requires_confirmation = (
            record.requires_confirmation or record.access == CapabilityAccess.EXTERNAL_WRITE or profile_requires_confirmation
        )
        if requires_confirmation and payload.get("confirm") is not True:
            raise ToolPermissionError(f"{record.name} requires explicit confirmation")
