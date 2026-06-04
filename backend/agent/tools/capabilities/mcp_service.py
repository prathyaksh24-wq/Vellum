from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Callable
from typing import Any

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry

McpRunner = Callable[[str, dict[str, Any]], str]


class McpCapabilityService:
    def __init__(self, runner: McpRunner | None = None) -> None:
        self.runner = runner or self._default_runner

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            CapabilityRecord(
                name="context7.resolve_library",
                namespace="context7",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"CodingAgent", "ResearchAgent", "VellumAgent"}),
                stream_label="Resolved library docs",
                adapter=self.resolve_library,
            )
        )
        registry.register(
            CapabilityRecord(
                name="context7.fetch_docs",
                namespace="context7",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"CodingAgent", "ResearchAgent", "VellumAgent"}),
                stream_label="Fetched library docs",
                adapter=self.fetch_docs,
            )
        )
        registry.register(
            CapabilityRecord(
                name="context_mode.fetch_and_index",
                namespace="context_mode",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"ResearchAgent", "CodingAgent", "VellumAgent"}),
                stream_label="Fetched research context",
                adapter=self.context_mode_fetch_and_index,
            )
        )
        registry.register(
            CapabilityRecord(
                name="github.read_issue",
                namespace="github",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"CodingAgent", "ResearchAgent", "VellumAgent"}),
                stream_label="Read GitHub issue",
                adapter=self.github_read_issue,
            )
        )
        registry.register(
            CapabilityRecord(
                name="github.write_issue",
                namespace="github",
                access=CapabilityAccess.EXTERNAL_WRITE,
                allowed_agents=frozenset({"CodingAgent", "VellumAgent"}),
                stream_label="Updated GitHub issue",
                requires_confirmation=True,
                adapter=self.github_write_issue,
            )
        )
        registry.register(
            CapabilityRecord(
                name="obsidian.search_notes",
                namespace="obsidian",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"MemoryAgent", "ResearchAgent", "VellumAgent"}),
                stream_label="Searched Obsidian notes",
                adapter=self.obsidian_search_notes,
            )
        )
        return registry

    def resolve_library(self, payload: dict[str, Any]) -> dict[str, Any]:
        library = payload.get("library") or payload.get("query")
        query = payload.get("query") or library
        return self._call(
            "context7",
            {"action": "resolve", "library": library, "query": query},
            "context7.resolve_library",
        )

    def fetch_docs(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = {
            "action": "docs",
            "library_id": payload.get("library_id") or payload.get("libraryId"),
            "topic": payload.get("topic") or payload.get("query"),
        }
        if "tokens" in payload:
            params["tokens"] = payload["tokens"]
        return self._call("context7", params, "context7.fetch_docs")

    def context_mode_fetch_and_index(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = dict(payload)
        params["action"] = "fetch_and_index"
        return self._call("context_mode", params, "context_mode.fetch_and_index")

    def github_read_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = dict(payload)
        params["action"] = "get_issue"
        return self._call("github", params, "github.read_issue")

    def github_write_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = dict(payload)
        params["action"] = "create_issue"
        return self._call("github", params, "github.write_issue")

    def obsidian_search_notes(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = dict(payload)
        params["action"] = "search"
        return self._call("obsidian", params, "obsidian.search_notes")

    def _call(self, server: str, params: dict[str, Any], action: str) -> dict[str, str]:
        text = self.runner(server, params)
        return {"action": action, "backend": "mcp", "server": server, "text": text}

    @staticmethod
    def _default_runner(server: str, params: dict[str, Any]) -> str:
        from agent.mcp.client import run_tools

        request = [{"server": server, "params": params}]
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            result = run_tools(request)[0]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(run_tools, request).result()[0]
        return result.result
