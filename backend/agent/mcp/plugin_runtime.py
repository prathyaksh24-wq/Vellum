"""Runtime adapter for MCP connectors declared by installed plugin bundles."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
import json
import os
from pathlib import Path
import re
import time
from typing import Any, AsyncIterator, Protocol
from urllib.parse import urlsplit, urlunsplit

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from agent.config import get_settings
from agent.mcp.common import content_text
from agent.mcp.audit import McpAuditLog
from agent.mcp.plugin_approvals import (
    PluginMcpApprovalError,
    PluginMcpOperation,
    PluginMcpApprovalStore,
    get_plugin_mcp_approval_store,
)
from agent.mcp.results import summarize_mcp_text, structured_mcp_text
from agent.plugins.registry import PluginRegistry
from agent.plugins.credential_binding import credential_digest as bind_credential
from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber


_ENV_REFERENCE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


class PluginMcpRuntimeError(ValueError):
    pass


def operation_read_only(plugin_id, tool, arguments):
    """Exa publishes one tool for starting research and polling its existing run."""
    if (plugin_id == 'exa' and tool.get('name') == 'agent_run'
            and set(arguments) == {'runId'} and isinstance(arguments.get('runId'), str)
            and arguments['runId'].strip()):
        return True
    return bool(tool.get('read_only'))


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
    auth: Any = field(default=None, repr=False, compare=False)
    credential_digest: str = field(default="",repr=False,compare=False)

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
                auth=connector.auth,
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
            tools, cursor, seen = [], None, set()
            while True:
                result = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
                tools.extend(_public_tool(tool) for tool in getattr(result, "tools", []))
                cursor = getattr(result, "nextCursor", None)
                if not cursor:
                    return tools
                if cursor in seen or len(tools) > 500:
                    raise PluginMcpRuntimeError("MCP tool pagination exceeded its bound.")
                seen.add(cursor)

    async def call_tool(
        self,
        connector: PluginMcpConnector,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        async with self._session(connector) as session:
            result = await session.call_tool(tool_name, arguments)
        if getattr(result, "isError", False):
            raise PluginMcpRuntimeError("The MCP server rejected this operation. Check the tool arguments and account permissions before retrying.")
        return content_text(result) or f"{tool_name} completed."


class PluginMcpRuntime:
    """Resolve enabled plugin connectors and mediate their tool calls."""

    def __init__(
        self,
        registry: PluginRegistry,
        *,
        transport: PluginMcpTransport | None = None,
        approval_store: PluginMcpApprovalStore | None = None,
        audit_log: McpAuditLog | None = None,
    ) -> None:
        self.registry = registry
        self.transport = transport or SdkPluginMcpTransport()
        self.approval_store = approval_store or get_plugin_mcp_approval_store()
        self.audit_log = audit_log or McpAuditLog()
        self.connector_diagnostics: list[dict[str, str]] = []

    def connectors(self, *, skip_invalid: bool = False) -> list[PluginMcpConnector]:
        connectors: list[PluginMcpConnector] = []
        self.connector_diagnostics = []
        def append_connector(plugin_id, root, item):
            try:
                connectors.append(_connector(plugin_id, root, item))
            except PluginMcpRuntimeError:
                if not skip_invalid:
                    raise
                self.connector_diagnostics.append({"plugin_id": plugin_id, "status": "unavailable"})
        manifests = self.registry.manifests()
        portable_ids = {manifest.id for manifest in manifests}
        for manifest in manifests:
            if not self.registry.is_enabled(manifest.id):
                continue
            for item in manifest.mcp_connectors:
                append_connector(manifest.id, manifest.path.resolve(), item)
        for record in self.registry.source_records():
            if record.id in portable_ids:
                continue
            if not self.registry.is_enabled(record.id):
                continue
            for item in record.mcp_connectors:
                append_connector(record.id, record.root.resolve(), item)
        return sorted(connectors, key=lambda item: (item.plugin_id, item.name))

    def connector(self, plugin_id: str, connector_name: str) -> PluginMcpConnector:
        normalized_plugin = plugin_id.strip()
        normalized_name = connector_name.strip()
        # A call to one service must not resolve credentials/configuration for
        # every installed MCP server. Reuse the registry's request-local view;
        # enablement and manifest changes are still observed on the next call.
        with self.registry.read_snapshot():
            manifest=next((item for item in self.registry.manifests() if item.id==normalized_plugin),None)
            record=manifest or next((item for item in self.registry.source_records() if item.id==normalized_plugin),None)
            if record is not None and self.registry.is_enabled(normalized_plugin):
                root=manifest.path.resolve() if manifest else record.root.resolve()
                for item in record.mcp_connectors:
                    if str(item.get("name") or "").strip()!=normalized_name:continue
                    try:return _connector(normalized_plugin,root,item)
                    except PluginMcpRuntimeError:break
        raise PluginMcpRuntimeError("Plugin MCP connector is unavailable or disabled.")

    async def list_tools(self, plugin_id: str, connector_name: str) -> list[dict[str, Any]]:
        connector = self.connector(plugin_id, connector_name)
        return await self._list_tools(connector)

    async def _list_tools(self, connector):
        plugin_id,connector_name=connector.plugin_id,connector.name
        if plugin_id == 'serpapi' and connector_name == 'serpapi':
            from agent.plugins.serpapi_connection import serpapi_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = serpapi_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The SerpAPI catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == 'hubspot' and connector_name == 'hubspot':
            from agent.plugins.hubspot_connection import hubspot_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = hubspot_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The HubSpot catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == 'clickup' and connector_name == 'clickup':
            from agent.plugins.clickup_connection import clickup_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = clickup_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The ClickUp catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == 'vercel' and connector_name == 'vercel':
            from agent.plugins.vercel_connection import vercel_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = vercel_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Vercel catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == 'supabase' and connector_name == 'supabase':
            from agent.plugins.supabase_connection import supabase_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = supabase_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Supabase catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == 'exa' and connector_name == 'exa':
            from agent.plugins.exa_connection import exa_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = exa_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Exa catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == 'tavily' and connector_name == 'tavily':
            from agent.plugins.tavily_connection import tavily_service, SERVER
            if connector.url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            service = tavily_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Tavily catalog changed. Refresh the connection.")
            return service.cached_tools()
        if plugin_id == "firecrawl" and connector_name == "firecrawl" and connector.url == "https://mcp.firecrawl.dev/v2/mcp-oauth":
            from agent.plugins.firecrawl_connection import firecrawl_service
            service = firecrawl_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Firecrawl catalog changed. Refresh its connection before retrying.")
            return service.cached_tools()
        if plugin_id == "apify" and connector_name == "apify" and connector.url == "https://mcp.apify.com?tools=actors,docs,runs,storage,tasks,schedules,report-problem,apify/rag-web-browser,apify/web-fetch&telemetry-enabled=false":
            from agent.plugins.apify_connection import apify_service
            service = apify_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Apify catalog changed. Refresh its connection before retrying.")
            return service.cached_tools()
        if plugin_id == "notion" and connector_name == "notion" and connector.url == "https://mcp.notion.com/mcp":
            from agent.plugins.notion import notion_service
            service = notion_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Notion catalog changed. Refresh its connection before retrying.")
            return service.cached_tools()
        if plugin_id == "airtable" and connector_name == "airtable" and connector.url == "https://mcp.airtable.com/mcp":
            from agent.plugins.airtable import airtable_service
            service = airtable_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Airtable catalog changed. Refresh its connection before retrying.")
            return service.cached_tools()
        if plugin_id == "slack" and connector_name == "slack" and connector.url == "https://mcp.slack.com/mcp":
            from agent.plugins.slack import slack_service
            service = slack_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The Slack catalog changed. Refresh its connection before retrying.")
            return service.cached_tools()
        if plugin_id == "github" and connector_name == "github" and connector.url == "https://api.githubcopilot.com/mcp/x/all":
            from agent.plugins.github_connection import github_service
            service = github_service()
            if service.tools_revision != connector.credential_digest:
                raise PluginMcpRuntimeError("The GitHub catalog changed. Refresh its connection before retrying.")
            return service.cached_tools()
        if not connector.configured:
            missing = ", ".join(connector.missing_env)
            raise PluginMcpRuntimeError(f"Plugin MCP connector needs environment configuration: {missing}")
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.transport.list_tools(connector),
                timeout=get_settings().mcp_timeout_seconds,
            )
        except BaseException:
            self._audit(
                plugin_id,
                connector_name,
                operation="list_tools",
                tool_name="*",
                started=started,
                outcome="failed",
            )
            raise
        self._audit(
            plugin_id,
            connector_name,
            operation="list_tools",
            tool_name="*",
            started=started,
            outcome="success",
        )
        return result

    async def call_tool(
        self,
        plugin_id: str,
        connector_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approval_id: str = "",
        credential_digest: str = "",
        structured: bool = False,
    ) -> str:
        connector = self.connector(plugin_id, connector_name)
        if credential_digest and connector.credential_digest != credential_digest:
            raise PluginMcpRuntimeError("The connector credential changed. Review this operation again.")
        tools = await self._list_tools(connector)
        tool = next((item for item in tools if item.get("name") == tool_name), None)
        if tool is None:
            raise PluginMcpRuntimeError("Plugin MCP tool is not exposed by this connector.")
        clean_arguments = _privacy_safe_arguments(arguments)
        if not operation_read_only(plugin_id, tool, clean_arguments):
            operation = PluginMcpOperation.from_arguments(
                plugin_id=plugin_id,
                connector=connector_name,
                tool_name=tool_name,
                arguments=clean_arguments,
            )
            if not approval_id:
                approval = self.approval_store.request(operation)
                raise PluginMcpRuntimeError(
                    f"Plugin MCP tool '{tool_name}' requires user approval: {approval['id']}"
                )
            try:
                self.approval_store.consume(approval_id, operation)
            except PluginMcpApprovalError as exc:
                raise PluginMcpRuntimeError(str(exc)) from exc

        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.transport.call_tool(connector, tool_name, clean_arguments),
                timeout=get_settings().mcp_timeout_seconds,
            )
        except BaseException:
            self._audit(
                plugin_id,
                connector_name,
                operation="call_tool",
                tool_name=tool_name,
                started=started,
                outcome="failed",
            )
            raise
        self._audit(
            plugin_id,
            connector_name,
            operation="call_tool",
            tool_name=tool_name,
            started=started,
            outcome="success",
        )
        return structured_mcp_text(result) if structured else summarize_mcp_text(result)

    def _audit(
        self,
        plugin_id: str,
        connector: str,
        *,
        operation: str,
        tool_name: str,
        started: float,
        outcome: str,
    ) -> None:
        self.audit_log.record(
            plugin_id=plugin_id,
            connector=connector,
            operation=operation,
            tool_name=tool_name,
            latency_ms=round((time.perf_counter() - started) * 1000),
            outcome=outcome,
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
        auth = None
        credential_digest = ""
        parsed_url = urlsplit(url)
        if parsed_url.scheme.lower() not in {"http", "https"} or not parsed_url.hostname:
            raise PluginMcpRuntimeError("Plugin MCP URL must use HTTP or HTTPS.")
        if parsed_url.username or parsed_url.password:
            raise PluginMcpRuntimeError("Plugin MCP URL must not contain credentials.")
        if payload.get("credential_provider") == "linear":
            if plugin_id != "linear" or url != "https://mcp.linear.app/mcp":
                raise PluginMcpRuntimeError("Linear credentials are restricted to its official MCP endpoint.")
            from agent.plugins.linear import linear_service, LinearError
            try:
                service=linear_service()
                data=service._require()
                token=data["token"]
                credential_digest=bind_credential(token,provider="linear")
                from agent.plugins.linear_oauth import stored_auth
                headers,auth={},stored_auth(service,connection=data)
            except LinearError:
                headers, missing = {}, ("Linear connection",)
        if payload.get("credential_provider") == 'serpapi':
            from agent.plugins.serpapi_connection import serpapi_service, SERVER
            if plugin_id != 'serpapi' or name != 'serpapi' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = serpapi_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("SerpAPI connection",)
        if payload.get("credential_provider") == 'hubspot':
            from agent.plugins.hubspot_connection import hubspot_service, SERVER
            if plugin_id != 'hubspot' or name != 'hubspot' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = hubspot_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("HubSpot connection",)
        if payload.get("credential_provider") == 'clickup':
            from agent.plugins.clickup_connection import clickup_service, SERVER
            if plugin_id != 'clickup' or name != 'clickup' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = clickup_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("ClickUp connection",)
        if payload.get("credential_provider") == 'vercel':
            from agent.plugins.vercel_connection import vercel_service, SERVER
            if plugin_id != 'vercel' or name != 'vercel' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = vercel_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("Vercel connection",)
        if payload.get("credential_provider") == 'supabase':
            from agent.plugins.supabase_connection import supabase_service, SERVER
            if plugin_id != 'supabase' or name != 'supabase' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = supabase_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("Supabase connection",)
        if payload.get("credential_provider") == 'exa':
            from agent.plugins.exa_connection import exa_service, SERVER
            if plugin_id != 'exa' or name != 'exa' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = exa_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("Exa connection",)
        if payload.get("credential_provider") == 'tavily':
            from agent.plugins.tavily_connection import tavily_service, SERVER
            if plugin_id != 'tavily' or name != 'tavily' or url != SERVER:
                raise PluginMcpRuntimeError("Invalid official connector endpoint.")
            try:
                service = tavily_service()
                data = service.require()
                headers = {"Authorization": "Bearer " + data["access_token"]}
                credential_digest = data["revision"]
            except (ValueError, RuntimeError):
                headers, missing = {}, ("Tavily connection",)
        if payload.get("credential_provider") == "firecrawl":
            if plugin_id != "firecrawl" or name != "firecrawl" or url != "https://mcp.firecrawl.dev/v2/mcp-oauth":
                raise PluginMcpRuntimeError("Firecrawl authorization is restricted to its official MCP endpoint.")
            from agent.plugins.firecrawl_connection import FirecrawlError, firecrawl_service
            try:
                service = firecrawl_service()
                data = service.require()
                headers, credential_digest = service.connector(data).headers, data["revision"]
            except FirecrawlError:
                headers, missing = {}, ("Firecrawl OAuth connection",)
        if payload.get("credential_provider") == "apify":
            if plugin_id != "apify" or name != "apify" or url != "https://mcp.apify.com?tools=actors,docs,runs,storage,tasks,schedules,report-problem,apify/rag-web-browser,apify/web-fetch&telemetry-enabled=false":
                raise PluginMcpRuntimeError("Apify authorization is restricted to its official MCP endpoint.")
            from agent.plugins.apify_connection import ApifyError, apify_service
            try:
                service = apify_service()
                data = service.require()
                headers, credential_digest = service.connector(data).headers, data["revision"]
            except ApifyError:
                headers, missing = {}, ("Apify OAuth connection",)
        if payload.get("credential_provider") == "notion":
            if plugin_id != "notion" or name != "notion" or url != "https://mcp.notion.com/mcp":
                raise PluginMcpRuntimeError("Notion authorization is restricted to its official MCP endpoint.")
            from agent.plugins.notion import NotionError, notion_service
            try:
                service = notion_service()
                data = service.require()
                headers, credential_digest = service.connector(data).headers, data["revision"]
            except NotionError:
                headers, missing = {}, ("Notion OAuth connection",)
        if payload.get("credential_provider") == "airtable":
            if plugin_id != "airtable" or name != "airtable" or url != "https://mcp.airtable.com/mcp":
                raise PluginMcpRuntimeError("Airtable authorization is restricted to its official MCP endpoint.")
            from agent.plugins.airtable import AirtableError, airtable_service
            try:
                service = airtable_service()
                data = service.require()
                headers, credential_digest = service.connector(data).headers, data["revision"]
            except AirtableError:
                headers, missing = {}, ("Airtable OAuth connection",)
        if payload.get("credential_provider") == "slack":
            if plugin_id != "slack" or name != "slack" or url != "https://mcp.slack.com/mcp":
                raise PluginMcpRuntimeError("Slack authorization is restricted to its official MCP endpoint.")
            from agent.plugins.slack import SlackError, slack_service
            try:
                service = slack_service()
                data = service.require()
                headers, credential_digest = service.connector(data).headers, data["revision"]
            except SlackError:
                headers, missing = {}, ("Slack OAuth connection",)
        if payload.get("credential_provider") == "github":
            if plugin_id != "github" or name != "github" or url != "https://api.githubcopilot.com/mcp/x/all":
                raise PluginMcpRuntimeError("GitHub authorization is restricted to its official MCP endpoint.")
            from agent.plugins.github_connection import GitHubConnectionError, github_service
            try:
                service = github_service()
                data = service.require()
                headers = service.connector(data).headers
                credential_digest = data["revision"]
            except GitHubConnectionError:
                headers, missing = {}, ("GitHub OAuth connection",)
        return PluginMcpConnector(
            plugin_id=plugin_id,
            name=name,
            root=root,
            transport="http",
            url=url,
            env=env,
            headers=headers,
            missing_env=missing,
            auth=auth,
            credential_digest=credential_digest,
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
