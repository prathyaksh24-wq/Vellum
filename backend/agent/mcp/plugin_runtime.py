"""Runtime adapter for MCP connectors declared by installed plugin bundles."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
import json
import os
from pathlib import Path
import re
from typing import Any, AsyncIterator, Protocol
from urllib.parse import urlsplit, urlunsplit

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings
from agent.mcp.common import content_text
from agent.mcp.results import normalize_mcp_text
from agent.plugins.registry import PluginRegistry
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber


_ENV_REFERENCE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


class PluginMcpRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class PluginMcpConnector:
    plugin_id: str
    name: str
    root: Path
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    missing_env: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return not self.missing_env and bool(self.url or self.command)

    def public(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "transport": self.transport,
            "configured": self.configured,
            "missing_env": list(self.missing_env),
            "url": _public_url(self.url),
            "command": Path(self.command).name if self.command else "",
        }


class PluginMcpTransport(Protocol):
    async def list_tools(self, connector: PluginMcpConnector) -> list[dict[str, Any]]: ...

    async def call_tool(
        self,
        connector: PluginMcpConnector,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str: ...


class SdkPluginMcpTransport:
    @asynccontextmanager
    async def _session(self, connector: PluginMcpConnector) -> AsyncIterator[ClientSession]:
        timeout = get_settings().mcp_timeout_seconds
        if connector.transport == "http":
            async with streamablehttp_client(
                connector.url,
                headers=connector.headers,
                timeout=timeout,
                sse_read_timeout=timeout,
            ) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            return

        params = StdioServerParameters(
            command=connector.command,
            args=list(connector.args),
            env=connector.env or None,
            cwd=str(connector.cwd) if connector.cwd else None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def list_tools(self, connector: PluginMcpConnector) -> list[dict[str, Any]]:
        async with self._session(connector) as session:
            result = await session.list_tools()
        return [_public_tool(tool) for tool in getattr(result, "tools", [])]

    async def call_tool(
        self,
        connector: PluginMcpConnector,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        async with self._session(connector) as session:
            result = await session.call_tool(tool_name, arguments)
        return content_text(result) or f"{tool_name} completed."


class PluginMcpRuntime:
    """Resolve enabled plugin connectors and mediate their tool calls."""

    def __init__(
        self,
        registry: PluginRegistry,
        *,
        transport: PluginMcpTransport | None = None,
    ) -> None:
        self.registry = registry
        self.transport = transport or SdkPluginMcpTransport()

    def connectors(self) -> list[PluginMcpConnector]:
        connectors: list[PluginMcpConnector] = []
        for manifest in self.registry.manifests():
            if not self.registry.is_enabled(manifest.id):
                continue
            connectors.extend(
                _connector(manifest.id, manifest.path.resolve(), item)
                for item in manifest.mcp_connectors
            )
        for record in self.registry.source_records():
            if not self.registry.is_enabled(record.id):
                continue
            connectors.extend(
                _connector(record.id, record.root.resolve(), item)
                for item in record.mcp_connectors
            )
        return sorted(connectors, key=lambda item: (item.plugin_id, item.name))

    def connector(self, plugin_id: str, connector_name: str) -> PluginMcpConnector:
        normalized_plugin = plugin_id.strip()
        normalized_name = connector_name.strip()
        for item in self.connectors():
            if item.plugin_id == normalized_plugin and item.name == normalized_name:
                return item
        raise PluginMcpRuntimeError("Plugin MCP connector is unavailable or disabled.")

    async def list_tools(self, plugin_id: str, connector_name: str) -> list[dict[str, Any]]:
        connector = self.connector(plugin_id, connector_name)
        if not connector.configured:
            missing = ", ".join(connector.missing_env)
            raise PluginMcpRuntimeError(f"Plugin MCP connector needs environment configuration: {missing}")
        return await asyncio.wait_for(
            self.transport.list_tools(connector),
            timeout=get_settings().mcp_timeout_seconds,
        )

    async def call_tool(
        self,
        plugin_id: str,
        connector_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        confirm: bool = False,
    ) -> str:
        connector = self.connector(plugin_id, connector_name)
        tools = await self.list_tools(plugin_id, connector_name)
        tool = next((item for item in tools if item.get("name") == tool_name), None)
        if tool is None:
            raise PluginMcpRuntimeError("Plugin MCP tool is not exposed by this connector.")
        if not tool.get("read_only") and not confirm:
            raise PluginMcpRuntimeError(f"Plugin MCP tool '{tool_name}' requires confirmation.")
        clean_arguments = _privacy_safe_arguments(arguments)
        return normalize_mcp_text(
            await asyncio.wait_for(
                self.transport.call_tool(connector, tool_name, clean_arguments),
                timeout=get_settings().mcp_timeout_seconds,
            )
        )


def _connector(
    plugin_id: str,
    root: Path,
    payload: dict[str, Any],
) -> PluginMcpConnector:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise PluginMcpRuntimeError("Plugin MCP connector name is required.")
    url = str(payload.get("url") or payload.get("serverUrl") or "").strip()
    env, env_missing = _resolved_mapping(payload.get("env"))
    headers, header_missing = _resolved_mapping(payload.get("headers"))
    missing = tuple(dict.fromkeys([*env_missing, *header_missing]))
    if url:
        parsed_url = urlsplit(url)
        if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.hostname:
            raise PluginMcpRuntimeError("Plugin MCP URL must use HTTP or HTTPS.")
        if parsed_url.username or parsed_url.password:
            raise PluginMcpRuntimeError("Plugin MCP URL must not contain credentials.")
        return PluginMcpConnector(
            plugin_id=plugin_id,
            name=name,
            root=root,
            transport="http",
            url=url,
            env=env,
            headers=headers,
            missing_env=missing,
        )

    command = str(payload.get("command") or "").strip()
    if not command:
        raise PluginMcpRuntimeError("Plugin MCP stdio connector requires a command.")
    resolved_command = _resolve_executable(root, command)
    args = tuple(_resolve_arg(root, str(value)) for value in payload.get("args", []) or [])
    cwd_value = str(payload.get("cwd") or "").strip()
    cwd = _inside_root(root, root / cwd_value) if cwd_value else root
    return PluginMcpConnector(
        plugin_id=plugin_id,
        name=name,
        root=root,
        transport="stdio",
        command=resolved_command,
        args=args,
        cwd=cwd,
        env=env,
        missing_env=missing,
    )


def _resolve_executable(root: Path, value: str) -> str:
    if value.startswith((".", "/", "\\")) or "/" in value or "\\" in value:
        return str(_inside_root(root, root / value))
    return value


def _resolve_arg(root: Path, value: str) -> str:
    if value.startswith("."):
        return str(_inside_root(root, root / value))
    return value


def _inside_root(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PluginMcpRuntimeError("Plugin MCP path resolves outside its plugin root.") from exc
    return resolved


def _resolved_mapping(value: Any) -> tuple[dict[str, str], tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}, ()
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        text = str(raw_value)
        reference = _ENV_REFERENCE.fullmatch(text)
        if reference:
            variable = reference.group(1)
            secret = os.getenv(variable)
            if secret is None:
                missing.append(variable)
                continue
            resolved[key] = secret
        else:
            resolved[key] = text
    return resolved, tuple(missing)


def _public_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _public_tool(tool: Any) -> dict[str, Any]:
    annotations = getattr(tool, "annotations", None)
    if hasattr(annotations, "model_dump"):
        annotation_data = annotations.model_dump(by_alias=True)
    elif isinstance(annotations, dict):
        annotation_data = dict(annotations)
    else:
        annotation_data = {}
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    return {
        "name": str(getattr(tool, "name", "")),
        "description": str(getattr(tool, "description", "") or ""),
        "input_schema": schema,
        "read_only": bool(
            annotation_data.get("readOnlyHint")
            or annotation_data.get("read_only_hint")
        ),
    }


def _privacy_safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    privacy_class, _reason = classify(raw)
    if privacy_class is DataClass.RED:
        raise PluginMcpRuntimeError("Withheld.")
    if privacy_class is DataClass.GREEN:
        return dict(arguments)
    scrubbed, _replacements = PrivacyScrubber().scrub(raw)
    loaded = json.loads(scrubbed)
    if not isinstance(loaded, dict):
        raise PluginMcpRuntimeError("Plugin MCP arguments must be an object.")
    return loaded
