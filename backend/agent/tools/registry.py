from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from langchain_core.runnables import RunnableConfig

from agent.profiles.policy import get_active_profile_policy


class CapabilityAccess(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL_WRITE = "external_write"


class ToolPermissionError(PermissionError):
    pass


def tool_result_failed(result: Any) -> bool:
    """Interpret the existing tool envelope consistently in execution and SSE."""
    if getattr(result, 'status', '') in ('error', 'failed', 'blocked'):
        return True
    value = getattr(result, 'content', result)
    if isinstance(value, str):
        import json
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return False
    return isinstance(value, dict) and (bool(value.get('error')) or value.get('ok') is False or
        value.get('success') is False or value.get('status') in ('error', 'failed', 'blocked', 'unavailable'))


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
    # Mixed read/write adapters must declare each read operation explicitly.
    read_actions: frozenset[str] | None = None
    input_schema: dict[str, Any] | None = None

    def schema(self) -> dict[str, Any]:
        if self.runtime_tool is not None:
            schema = self.runtime_tool.args_schema
            return schema if isinstance(schema, dict) else schema.model_json_schema()
        return self.input_schema or {"type":"object", "additionalProperties":True}


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

    def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        agent_name: str,
        runtime_config: RunnableConfig | None = None,
    ) -> Any:
        record = self.get(name)
        from agent.observability.activity import emit_activity as publish_activity
        from uuid import uuid4
        def emit_activity(*args, **kwargs):
            # The main graph already publishes its execution callbacks. Inner
            # specialist tools need this projection because they run in workers.
            if agent_name != 'VellumAgent':
                publish_activity(*args, **kwargs)
        item_id = str(uuid4())
        emit_activity('tool_call_preparing', name, item_id=item_id, label=f'Checking access to {name}',
                      agent=agent_name, input=payload)
        try:
            self._check_permission(record, payload, agent_name=agent_name)
            emit_activity('tool_call_started', name, item_id=item_id, label=f'Using {name}', agent=agent_name)
            if record.runtime_tool is not None:
                result = record.runtime_tool.invoke(payload, config=runtime_config)
            else:
                result = record.adapter(payload)
        except Exception as exc:
            emit_activity('tool_call_completed', name, item_id=item_id, label=f'{name} failed',
                          status='blocked' if isinstance(exc, ToolPermissionError) else 'failed',
                          agent=agent_name, output=exc.__class__.__name__)
            raise
        observed = result
        if isinstance(result, str) and result.lstrip().startswith('{'):
            import json
            try:
                observed = json.loads(result)
            except ValueError:
                pass
        failed = tool_result_failed(result)
        emit_activity('tool_call_completed', name, item_id=item_id, label=f'{name} failed' if failed else record.stream_label,
                      status='failed' if failed else 'completed', agent=agent_name, output=result)
        if not failed and agent_name != 'VellumAgent':
            try:
                # Expose returned public sources as soon as the read finishes,
                # before specialist synthesis. A discovered URL is not a page read.
                from agent.tools.web import extract_web_sources
                from urllib.parse import urlparse
                sources = observed.get('sources') if isinstance(observed, dict) else None
                if not isinstance(sources, list):
                    import json
                    sources = extract_web_sources(result if isinstance(result, str) else json.dumps(observed, default=str))
                for source in sources[:20]:
                    if not isinstance(source, dict):
                        continue
                    url = str(source.get('url') or source.get('path_or_url') or '')
                    if not url.startswith(('https://', 'http://')):
                        continue
                    domain = urlparse(url).netloc.removeprefix('www.')
                    public = {'url':url, 'title':str(source.get('title') or domain),
                              'domain':domain, 'source_type':'web'}
                    emit_activity('source_reading' if name=='web_extract_pages' else 'source_discovered', '', item_id='source-'+url,
                                  label=('Read ' if name=='web_extract_pages' else 'Found ')+domain, status='completed', source=public, agent=agent_name)
            except Exception as exc:
                logger.debug('Tool source progress omitted (%s)', type(exc).__name__)
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

            def make_invoker(capability_name: str):
                def invoke(config: RunnableConfig = None, **payload):
                    return self.invoke(
                        capability_name,
                        payload,
                        agent_name=agent_name,
                        runtime_config=config,
                    )

                return invoke

            wrapped.append(
                StructuredTool(
                    name=tool.name,
                    description=tool.description,
                    args_schema=tool.args_schema,
                    return_direct=tool.return_direct,
                    tags=tool.tags,
                    metadata={**(tool.metadata or {}), 'vellum_access':record.access.value},
                    handle_tool_error=tool.handle_tool_error,
                    handle_validation_error=tool.handle_validation_error,
                    response_format=tool.response_format,
                    func=make_invoker(record.name),
                )
            )
        return wrapped

    def _check_permission(self, record: CapabilityRecord, payload: dict[str, Any], *, agent_name: str) -> None:
        from agent.personalization import tool_preference_error
        preference_error = tool_preference_error(record.name, record.namespace)
        if preference_error:
            raise ToolPermissionError(preference_error)
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
