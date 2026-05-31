# Hybrid MCP Master-Pupil Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-grade hybrid MCP-shaped tool layer for Vellum's Master/Pupil system: a shared Tool Registry, real XAgent execution through xAI/SuperGrok OAuth-backed X search, a dependable MemoryAgent context/review service, and read-only YouTube capability scaffolding.

**Architecture:** Vellum remains the Master and final responder. Pupils use a shared, permissioned Tool Registry instead of raw integrations. Internal MCP-shaped services expose typed capabilities now and can be promoted to real MCP servers later without changing Pupil contracts.

**Tech Stack:** Python 3.11+, dataclasses/Pydantic-style plain models, pytest, existing `scripts/xai_x_search_client.py`, existing `agent.memory` stores, existing LangChain tool adapters, SQLite for lightweight memory/proposal persistence.

---

## Execution Notes

- Run Python test commands from `backend/`; `backend/pyproject.toml` sets `pythonpath = ["."]`.
- Run `git add`, `git commit`, and `git diff` commands from the repository root.
- Preserve the current uncommitted Sports/Master-Pupil work unless a task explicitly touches the same file.

---

## File Structure

Create:

- `backend/agent/tools/registry.py`: canonical capability metadata, permission checks, and adapter dispatch.
- `backend/agent/tools/capabilities/__init__.py`: exports capability service classes.
- `backend/agent/tools/capabilities/x_service.py`: X MCP-shaped service backed by xAI/SuperGrok OAuth search and existing X API client gates.
- `backend/agent/tools/capabilities/mcp_service.py`: capability wrappers for existing MCP servers such as Context7, Context Mode, GitHub, and Obsidian.
- `backend/agent/tools/capabilities/memory_service.py`: Memory MCP-shaped service around ProjectContext, FTS5, Honcho, memory cards, and proposal review.
- `backend/agent/tools/capabilities/youtube_service.py`: read-only YouTube service interface with deterministic unsupported responses until transcript/search backend is added.
- `backend/tests/test_tool_registry.py`: registry and permission tests.
- `backend/tests/test_x_capability_service.py`: X service tests with mocked clients.
- `backend/tests/test_mcp_capability_service.py`: existing MCP service registry and adapter tests with mocked runners.
- `backend/tests/test_memory_capability_service.py`: memory service tests.
- `backend/tests/test_youtube_capability_service.py`: YouTube service interface tests.

Modify:

- `backend/agent/agents/x_agent.py`: use `XCapabilityService` instead of returning stub responses.
- `backend/agent/agents/memory_agent.py`: use `MemoryCapabilityService` for context packs, proposal review, conflict checks, and memory card creation.
- `backend/agent/agents/youtube.py`: use `YoutubeCapabilityService` for read-only structured "unsupported until backend configured" behavior.
- `backend/agent/master/registry.py`: instantiate Pupils with capability services.
- `backend/agent/agents/live_dispatcher.py`: keep single chat route, now with capability-derived tools and evidence.
- `backend/tests/test_specialist_agents.py`: update X/YouTube/Memory Pupil expectations from stub-only to service-backed behavior.
- `backend/tests/test_master_pupil.py`: assert registry exposes capability-backed Pupils.

Do not modify:

- OAuth setup scripts unless a test exposes a real bug.
- `scripts/xai_x_search_client.py` internals unless the service adapter cannot use the current public functions.
- Frontend UI. Existing activity/source events are already generic enough for this phase.

---

## Task 1: Tool Registry Foundation

**Files:**
- Create: `backend/agent/tools/registry.py`
- Test: `backend/tests/test_tool_registry.py`

- [ ] **Step 1: Write failing registry tests**

Create `backend/tests/test_tool_registry.py`:

```python
import pytest

from agent.tools.registry import (
    CapabilityAccess,
    CapabilityRecord,
    ToolPermissionError,
    ToolRegistry,
)


def test_tool_registry_registers_and_invokes_allowed_capability():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.search_posts",
            namespace="x",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"XAgent", "VellumAgent"}),
            stream_label="Searched X",
            adapter=lambda payload: {"items": [{"text": payload["query"]}]},
        )
    )

    result = registry.invoke("x.search_posts", {"query": "arsenal"}, agent_name="XAgent")

    assert result == {"items": [{"text": "arsenal"}]}
    assert registry.get("x.search_posts").stream_label == "Searched X"


def test_tool_registry_blocks_unapproved_agent():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.search_posts",
            namespace="x",
            access=CapabilityAccess.READ,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Searched X",
            adapter=lambda payload: {},
        )
    )

    with pytest.raises(ToolPermissionError, match="MemoryAgent cannot use x.search_posts"):
        registry.invoke("x.search_posts", {"query": "nba"}, agent_name="MemoryAgent")


def test_tool_registry_requires_confirmation_for_external_posting():
    registry = ToolRegistry()
    registry.register(
        CapabilityRecord(
            name="x.publish_post",
            namespace="x",
            access=CapabilityAccess.EXTERNAL_WRITE,
            allowed_agents=frozenset({"XAgent"}),
            stream_label="Posted to X",
            requires_confirmation=True,
            adapter=lambda payload: {"posted": True},
        )
    )

    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke("x.publish_post", {"text": "hello"}, agent_name="XAgent")

    result = registry.invoke("x.publish_post", {"text": "hello", "confirm": True}, agent_name="XAgent")
    assert result == {"posted": True}
```

- [ ] **Step 2: Run registry tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_tool_registry.py -q --basetemp .pytest-tmp
```

Expected: collection fails with `ModuleNotFoundError: No module named 'agent.tools.registry'`.

- [ ] **Step 3: Implement registry models and permission checks**

Create `backend/agent/tools/registry.py`:

```python
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
```

- [ ] **Step 4: Run registry tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_tool_registry.py -q --basetemp .pytest-tmp
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 1**

```powershell
git add backend/agent/tools/registry.py backend/tests/test_tool_registry.py
git commit -m "feat: add hybrid tool registry"
```

---

## Task 2: X MCP-Shaped Capability Service

**Files:**
- Create: `backend/agent/tools/capabilities/__init__.py`
- Create: `backend/agent/tools/capabilities/x_service.py`
- Test: `backend/tests/test_x_capability_service.py`

- [ ] **Step 1: Write failing X service tests**

Create `backend/tests/test_x_capability_service.py`:

```python
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.registry import ToolPermissionError


def test_x_service_search_posts_returns_structured_records():
    calls = {}

    def fake_search(query, max_results):
        calls["query"] = query
        calls["max_results"] = max_results
        return [
            {
                "text": "Arsenal posted training photos.",
                "url": "https://x.com/arsenal/status/1",
                "author": {"username": "Arsenal"},
                "created_at": "2026-05-31T10:00:00Z",
            }
        ]

    service = XCapabilityService(search_posts_backend=fake_search)

    result = service.search_posts({"query": "Arsenal", "max_results": 3})

    assert calls == {"query": "Arsenal", "max_results": 3}
    assert result["action"] == "x.search_posts"
    assert result["items"][0]["url"] == "https://x.com/arsenal/status/1"
    assert result["items"][0]["handle"] == "Arsenal"


def test_x_service_publish_post_requires_confirm_and_enabled_gate():
    service = XCapabilityService(post_backend=lambda text: {"id": "1", "text": text}, allow_posts=False)

    try:
        service.publish_post({"text": "hello", "confirm": True})
    except ToolPermissionError as exc:
        assert "X_TOOL_ALLOW_POSTS=true" in str(exc)
    else:
        raise AssertionError("publish_post should require the posts env gate")

    service = XCapabilityService(post_backend=lambda text: {"id": "1", "text": text}, allow_posts=True)

    try:
        service.publish_post({"text": "hello"})
    except ToolPermissionError as exc:
        assert "confirm=True" in str(exc)
    else:
        raise AssertionError("publish_post should require confirm=True")


def test_x_service_registers_capabilities_with_tool_registry():
    service = XCapabilityService(search_posts_backend=lambda query, max_results: [])
    registry = service.build_registry()

    assert "x.search_posts" in registry.names()
    assert "x.publish_post" in registry.names()
    assert registry.get("x.search_posts").stream_label == "Searched X"
```

- [ ] **Step 2: Run X service tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_x_capability_service.py -q --basetemp .pytest-tmp
```

Expected: collection fails with `ModuleNotFoundError: No module named 'agent.tools.capabilities'`.

- [ ] **Step 3: Implement X capability service**

Create `backend/agent/tools/capabilities/__init__.py`:

```python
from agent.tools.capabilities.x_service import XCapabilityService

__all__ = ["XCapabilityService"]
```

Create `backend/agent/tools/capabilities/x_service.py`:

```python
from __future__ import annotations

from collections.abc import Callable
import importlib.util
from typing import Any

from agent.config import REPO_ROOT
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


SearchPostsBackend = Callable[[str, int], list[dict[str, Any]]]
PostBackend = Callable[[str], dict[str, Any]]


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class XCapabilityService:
    def __init__(
        self,
        *,
        search_posts_backend: SearchPostsBackend | None = None,
        post_backend: PostBackend | None = None,
        allow_posts: bool = False,
    ) -> None:
        self.search_posts_backend = search_posts_backend or self._default_search_posts
        self.post_backend = post_backend or self._default_post
        self.allow_posts = allow_posts

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            CapabilityRecord(
                name="x.search_posts",
                namespace="x",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"XAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"}),
                stream_label="Searched X",
                adapter=self.search_posts,
            )
        )
        registry.register(
            CapabilityRecord(
                name="x.publish_post",
                namespace="x",
                access=CapabilityAccess.EXTERNAL_WRITE,
                allowed_agents=frozenset({"XAgent", "VellumAgent"}),
                stream_label="Posted to X",
                requires_confirmation=True,
                adapter=self.publish_post,
            )
        )
        return registry

    def search_posts(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        max_results = int(payload.get("max_results") or 10)
        items = self.search_posts_backend(query, max_results)
        return {
            "action": "x.search_posts",
            "items": [self._normalize_post(item) for item in items],
        }

    def publish_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_posts:
            raise ToolPermissionError("Posting to X requires X_TOOL_ALLOW_POSTS=true.")
        if payload.get("confirm") is not True:
            raise ToolPermissionError("Posting to X requires confirm=True.")
        text = str(payload.get("text") or "").strip()
        return {"action": "x.publish_post", "tweet": self.post_backend(text)}

    def _normalize_post(self, item: dict[str, Any]) -> dict[str, str]:
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        return {
            "text": str(item.get("text") or item.get("body") or ""),
            "url": str(item.get("url") or item.get("x_url") or item.get("tweet_url") or ""),
            "handle": str(author.get("username") or item.get("handle") or ""),
            "created_at": str(item.get("created_at") or item.get("date") or ""),
        }

    def _default_search_posts(self, query: str, max_results: int) -> list[dict[str, Any]]:
        xai_x_search_client = _load_script("xai_x_search_client")
        return xai_x_search_client.search_x(query=query, max_items=max_results)

    def _default_post(self, text: str) -> dict[str, Any]:
        x_api_client = _load_script("x_api_client")
        return x_api_client.post_tweet(text=text).get("data", {})
```

- [ ] **Step 4: Run X service tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_x_capability_service.py -q --basetemp .pytest-tmp
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 2**

```powershell
git add backend/agent/tools/capabilities/__init__.py backend/agent/tools/capabilities/x_service.py backend/tests/test_x_capability_service.py
git commit -m "feat: add x capability service"
```

---

## Task 2A: Existing MCP Capability Service

**Files:**
- Create: `backend/agent/tools/capabilities/mcp_service.py`
- Modify: `backend/agent/tools/capabilities/__init__.py`
- Test: `backend/tests/test_mcp_capability_service.py`

- [ ] **Step 1: Write failing MCP service tests**

Create `backend/tests/test_mcp_capability_service.py`:

```python
import pytest

from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.registry import ToolPermissionError


def test_mcp_service_registers_existing_context7_and_project_tools():
    service = McpCapabilityService(runner=lambda server, params: "ok")
    registry = service.build_registry()

    assert "context7.resolve_library" in registry.names()
    assert "context7.fetch_docs" in registry.names()
    assert "context_mode.fetch_and_index" in registry.names()
    assert "github.read_issue" in registry.names()
    assert "obsidian.search_notes" in registry.names()


def test_mcp_service_invokes_context7_with_structured_result():
    calls = []

    def fake_runner(server, params):
        calls.append((server, params))
        return "Resolved /openai/openai-python"

    service = McpCapabilityService(runner=fake_runner)
    registry = service.build_registry()

    result = registry.invoke(
        "context7.resolve_library",
        {"library": "openai python"},
        agent_name="VellumAgent",
    )

    assert calls == [("context7", {"action": "resolve", "library": "openai python", "query": "openai python"})]
    assert result == {
        "action": "context7.resolve_library",
        "backend": "mcp",
        "server": "context7",
        "text": "Resolved /openai/openai-python",
    }


def test_mcp_service_gates_github_write_actions():
    service = McpCapabilityService(runner=lambda server, params: "created")
    registry = service.build_registry()

    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke(
            "github.write_issue",
            {"repo": "owner/repo", "title": "Bug", "body": "Details"},
            agent_name="CodingAgent",
        )
```

- [ ] **Step 2: Run MCP service tests and verify they fail**

Run from `backend/`:

```powershell
python -m pytest tests/test_mcp_capability_service.py -q --basetemp .pytest-tmp
```

Expected: collection fails with `ModuleNotFoundError` for `mcp_service`.

- [ ] **Step 3: Implement MCP capability service**

Create `backend/agent/tools/capabilities/mcp_service.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


McpRunner = Callable[[str, dict[str, Any]], str]


class McpCapabilityService:
    def __init__(self, *, runner: McpRunner | None = None) -> None:
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

    def resolve_library(self, payload: dict[str, Any]) -> dict[str, str]:
        library = str(payload.get("library") or payload.get("query") or "").strip()
        query = str(payload.get("query") or library).strip()
        return self._call(
            "context7",
            {"action": "resolve", "library": library, "query": query},
            "context7.resolve_library",
        )

    def fetch_docs(self, payload: dict[str, Any]) -> dict[str, str]:
        return self._call(
            "context7",
            {
                "action": "docs",
                "library_id": str(payload.get("library_id") or payload.get("libraryId") or "").strip(),
                "topic": str(payload.get("topic") or payload.get("query") or "").strip(),
                "tokens": payload.get("tokens"),
            },
            "context7.fetch_docs",
        )

    def context_mode_fetch_and_index(self, payload: dict[str, Any]) -> dict[str, str]:
        return self._call("context_mode", dict(payload), "context_mode.fetch_and_index")

    def github_read_issue(self, payload: dict[str, Any]) -> dict[str, str]:
        params = {"action": "issue", **payload}
        return self._call("github", params, "github.read_issue")

    def github_write_issue(self, payload: dict[str, Any]) -> dict[str, str]:
        params = {"action": "create_issue", **payload}
        return self._call("github", params, "github.write_issue")

    def obsidian_search_notes(self, payload: dict[str, Any]) -> dict[str, str]:
        params = {"action": "search", **payload}
        return self._call("obsidian", params, "obsidian.search_notes")

    def _call(self, server: str, params: dict[str, Any], action: str) -> dict[str, str]:
        text = self.runner(server, params)
        return {"action": action, "backend": "mcp", "server": server, "text": text}

    def _default_runner(self, server: str, params: dict[str, Any]) -> str:
        from agent.mcp.client import run_tools

        result = run_tools([{"server": server, "params": params}])[0]
        return result.result
```

- [ ] **Step 4: Export MCP service**

Modify `backend/agent/tools/capabilities/__init__.py`:

```python
from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.capabilities.x_service import XCapabilityService

__all__ = ["McpCapabilityService", "XCapabilityService"]
```

- [ ] **Step 5: Run MCP service tests**

Run from `backend/`:

```powershell
python -m pytest tests/test_mcp_capability_service.py -q --basetemp .pytest-tmp
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 2A**

Run from the repository root:

```powershell
git add backend/agent/tools/capabilities/mcp_service.py backend/agent/tools/capabilities/__init__.py backend/tests/test_mcp_capability_service.py
git commit -m "feat: register existing mcp capabilities"
```

---

## Task 3: XAgent Uses X Capability Service

**Files:**
- Modify: `backend/agent/agents/x_agent.py`
- Modify: `backend/agent/master/registry.py`
- Test: `backend/tests/test_specialist_agents.py`

- [ ] **Step 1: Add failing XAgent execution test**

Append to `backend/tests/test_specialist_agents.py`:

```python
def test_x_agent_searches_posts_through_capability_service(tmp_path):
    from agent.agents.x_agent import XAgent
    from agent.tools.capabilities.x_service import XCapabilityService

    service = XCapabilityService(
        search_posts_backend=lambda query, max_results: [
            {
                "text": "Naval posted about leverage.",
                "url": "https://x.com/naval/status/1",
                "author": {"username": "naval"},
                "created_at": "2026-05-31T12:00:00Z",
            }
        ]
    )
    agent = XAgent(vault_root=tmp_path, x_service=service)

    response = agent.answer("What did Naval post on X?")

    assert response.status == "answered"
    assert "Naval posted about leverage" in response.summary
    assert response.sources[0].kind == "web"
    assert response.sources[0].path_or_url == "https://x.com/naval/status/1"
```

- [ ] **Step 2: Run XAgent test and verify it fails**

Run:

```powershell
python -m pytest tests/test_specialist_agents.py::test_x_agent_searches_posts_through_capability_service -q --basetemp .pytest-tmp
```

Expected: fails with `TypeError: XAgent.__init__() got an unexpected keyword argument 'x_service'`.

- [ ] **Step 3: Update XAgent**

Modify `backend/agent/agents/x_agent.py` to:

```python
from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.capabilities.x_service import XCapabilityService


class XAgent:
    name = "XAgent"

    _KEYWORDS = ("twitter", "tweet", "tweets", "latest-50")
    _X_CONTEXT_PATTERNS = (
        r"(?<!\w)post(?:s|ed|ing)?\s+on\s+x(?!\w)",
        r"(?<!\w)x\s+account(?:s)?(?!\w)",
        r"(?<!\w)x\s+feed(?:s)?(?!\w)",
        r"(?<!\w)x\s+post(?:s)?(?!\w)",
        r"(?<!\w)on\s+x(?!\w)",
    )

    def __init__(self, vault_root: Path, x_service: XCapabilityService | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.x_service = x_service or XCapabilityService()

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS) or any(
            re.search(pattern, lowered) is not None for pattern in self._X_CONTEXT_PATTERNS
        )

    def answer(self, query: str) -> SpecialistResponse:
        result = self.x_service.search_posts({"query": query, "max_results": 5})
        items = result.get("items", [])
        if not items:
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary="XAgent did not find matching X posts.",
                confidence=0.35,
            )
        lines = []
        sources = []
        for index, item in enumerate(items[:5], start=1):
            text = str(item.get("text") or "").strip()
            handle = str(item.get("handle") or "x").strip()
            url = str(item.get("url") or "").strip()
            lines.append(f"[{index}] @{handle}: {text}")
            if url:
                sources.append(
                    SpecialistSource(
                        kind="web",
                        title=f"@{handle} on X",
                        path_or_url=url,
                        captured_at=str(item.get("created_at") or ""),
                        freshness="live",
                    )
                )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="\n".join(lines),
            analysis="Used x.search_posts through the shared X capability service.",
            sources=sources,
            confidence=0.75,
        )

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
```

- [ ] **Step 4: Run XAgent tests**

Run:

```powershell
python -m pytest tests/test_specialist_agents.py::test_x_agent_searches_posts_through_capability_service tests/test_x_capability_service.py -q --basetemp .pytest-tmp
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/agent/agents/x_agent.py backend/agent/master/registry.py backend/tests/test_specialist_agents.py
git commit -m "feat: route x agent through capability service"
```

---

## Task 4: Memory MCP-Shaped Capability Service

**Files:**
- Create: `backend/agent/tools/capabilities/memory_service.py`
- Test: `backend/tests/test_memory_capability_service.py`

- [ ] **Step 1: Write failing memory service tests**

Create `backend/tests/test_memory_capability_service.py`:

```python
from agent.agents.base import MemoryProposal
from agent.tools.capabilities.memory_service import MemoryCapabilityService


def test_memory_service_builds_context_pack_from_project_context_and_cards(tmp_path):
    vault = tmp_path / "Vault"
    memory_dir = vault / "Agent" / "Memories" / "Shared"
    memory_dir.mkdir(parents=True)
    (memory_dir / "style.md").write_text(
        "---\nscope: shared\nconfidence: 0.9\n---\n\nUser prefers concise answers.\n",
        encoding="utf-8",
    )
    (vault / "Meta").mkdir()
    (vault / "Meta" / "profile.md").write_text("User is building Vellum.", encoding="utf-8")
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    pack = service.build_context_pack({"query": "How should I answer?", "thread_id": "t1", "agent_name": "XAgent"})

    assert pack["action"] == "memory.build_context_pack"
    assert "concise answers" in pack["cards"][0]["text"]
    assert pack["agent_name"] == "XAgent"


def test_memory_service_reviews_proposals_and_detects_conflicts(tmp_path):
    service = MemoryCapabilityService(vault_root=tmp_path / "Vault", sessions_db=tmp_path / "sessions.db")
    proposals = [
        MemoryProposal(scope="memory", claim="User likes long answers.", evidence="one vague turn", confidence=0.4),
        MemoryProposal(scope="memory", claim="User likes concise answers.", evidence="three explicit corrections", confidence=0.9),
    ]

    reviewed = service.review_proposals({"proposals": proposals})
    conflicts = service.detect_conflicts({"claims": ["User likes concise answers.", "User dislikes concise answers."]})

    assert [item["claim"] for item in reviewed["accepted"]] == ["User likes concise answers."]
    assert reviewed["rejected"][0]["claim"] == "User likes long answers."
    assert conflicts["conflicts"]


def test_memory_service_create_card_writes_durable_memory(tmp_path):
    vault = tmp_path / "Vault"
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")

    result = service.create_card(
        {
            "scope": "shared",
            "title": "Answer style",
            "summary": "User prefers concise answers.",
            "evidence": "Repeated corrections.",
            "visible_to": ["VellumAgent", "MemoryAgent"],
        }
    )

    path = vault / result["path"]
    assert path.exists()
    assert "User prefers concise answers." in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run memory service tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_memory_capability_service.py -q --basetemp .pytest-tmp
```

Expected: collection fails with `ModuleNotFoundError` for `memory_service`.

- [ ] **Step 3: Implement memory service**

Create `backend/agent/tools/capabilities/memory_service.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from agent.agents.base import MemoryProposal


class MemoryCapabilityService:
    def __init__(self, *, vault_root: Path, sessions_db: Path) -> None:
        self.vault_root = Path(vault_root)
        self.sessions_db = Path(sessions_db)

    def build_context_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "")
        agent_name = str(payload.get("agent_name") or "VellumAgent")
        cards = self.search_cards({"query": query, "scope": ""})["cards"]
        return {
            "action": "memory.build_context_pack",
            "query": query,
            "thread_id": str(payload.get("thread_id") or ""),
            "agent_name": agent_name,
            "cards": cards[:8],
        }

    def search_cards(self, payload: dict[str, Any]) -> dict[str, Any]:
        query_terms = set(self._terms(str(payload.get("query") or "")))
        cards = []
        root = self.vault_root / "Agent" / "Memories"
        if root.exists():
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8", errors="ignore")
                text_terms = set(self._terms(text))
                if not query_terms or query_terms & text_terms:
                    cards.append({"path": path.relative_to(self.vault_root).as_posix(), "text": text[:1000]})
        return {"action": "memory.search_cards", "cards": cards}

    def review_proposals(self, payload: dict[str, Any]) -> dict[str, Any]:
        accepted = []
        rejected = []
        for proposal in payload.get("proposals", []):
            item = proposal.model_dump() if hasattr(proposal, "model_dump") else dict(proposal)
            if float(item.get("confidence") or 0) >= 0.75:
                accepted.append(item)
            else:
                rejected.append(item)
        return {"action": "memory.review_proposals", "accepted": accepted, "rejected": rejected}

    def detect_conflicts(self, payload: dict[str, Any]) -> dict[str, Any]:
        claims = [str(claim) for claim in payload.get("claims", [])]
        conflicts = []
        for left in claims:
            for right in claims:
                if left == right:
                    continue
                if self._is_simple_conflict(left, right):
                    conflicts.append({"left": left, "right": right})
        return {"action": "memory.detect_conflicts", "conflicts": conflicts}

    def create_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        scope = str(payload.get("scope") or "shared")
        title = str(payload.get("title") or "Memory").strip()
        summary = str(payload.get("summary") or "").strip()
        evidence = str(payload.get("evidence") or "").strip()
        visible_to = payload.get("visible_to") or ["VellumAgent", "MemoryAgent"]
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "memory"
        folder = self.vault_root / "Agent" / "Memories" / scope.title()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slug}.md"
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        content = (
            "---\n"
            f"type: memory-card\nscope: {scope}\ncreated: \"{created}\"\n"
            f"visible_to: {visible_to}\n"
            "---\n\n"
            f"# {title}\n\n"
            f"{summary}\n\n"
            "## Evidence\n"
            f"{evidence}\n"
        )
        path.write_text(content, encoding="utf-8", newline="\n")
        return {"action": "memory.create_card", "path": path.relative_to(self.vault_root).as_posix()}

    def propose_card(self, payload: dict[str, Any]) -> dict[str, Any]:
        proposal = MemoryProposal(
            scope=payload.get("scope", "memory"),
            claim=str(payload.get("claim") or ""),
            evidence=str(payload.get("evidence") or ""),
            confidence=float(payload.get("confidence") or 0),
        )
        return {"action": "memory.propose_card", "proposal": proposal.model_dump()}

    def _terms(self, text: str) -> list[str]:
        return [term.casefold() for term in re.findall(r"[A-Za-z0-9]+", text) if len(term) > 2]

    def _is_simple_conflict(self, left: str, right: str) -> bool:
        l = left.casefold()
        r = right.casefold()
        return (" likes " in l and " dislikes " in r and l.replace(" likes ", " dislikes ") == r) or (
            " dislikes " in l and " likes " in r and l.replace(" dislikes ", " likes ") == r
        )
```

- [ ] **Step 4: Export Memory service**

Modify `backend/agent/tools/capabilities/__init__.py`:

```python
from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools.capabilities.x_service import XCapabilityService

__all__ = ["McpCapabilityService", "MemoryCapabilityService", "XCapabilityService"]
```

- [ ] **Step 5: Run memory service tests**

Run:

```powershell
python -m pytest tests/test_memory_capability_service.py -q --basetemp .pytest-tmp
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 4**

```powershell
git add backend/agent/tools/capabilities/memory_service.py backend/agent/tools/capabilities/__init__.py backend/tests/test_memory_capability_service.py
git commit -m "feat: add memory capability service"
```

---

## Task 5: MemoryAgent Uses Memory Capability Service

**Files:**
- Modify: `backend/agent/agents/memory_agent.py`
- Modify: `backend/agent/master/registry.py`
- Test: `backend/tests/test_specialist_agents.py`

- [ ] **Step 1: Add failing MemoryAgent context test**

Append to `backend/tests/test_specialist_agents.py`:

```python
def test_memory_agent_builds_context_pack_and_reviews_memory(tmp_path):
    from agent.agents.memory_agent import MemoryAgent
    from agent.tools.capabilities.memory_service import MemoryCapabilityService

    vault = tmp_path / "Vault"
    card_dir = vault / "Agent" / "Memories" / "Shared"
    card_dir.mkdir(parents=True)
    (card_dir / "style.md").write_text("User prefers concise answers.", encoding="utf-8")
    service = MemoryCapabilityService(vault_root=vault, sessions_db=tmp_path / "sessions.db")
    agent = MemoryAgent(vault_root=vault, memory_service=service)

    response = agent.answer("What should you remember about my answer style?")

    assert response.status == "answered"
    assert "concise answers" in response.summary
    assert response.memory_proposals
```

- [ ] **Step 2: Run MemoryAgent test and verify it fails**

Run:

```powershell
python -m pytest tests/test_specialist_agents.py::test_memory_agent_builds_context_pack_and_reviews_memory -q --basetemp .pytest-tmp
```

Expected: fails with `TypeError: MemoryAgent.__init__() got an unexpected keyword argument 'memory_service'`.

- [ ] **Step 3: Update MemoryAgent**

Modify `backend/agent/agents/memory_agent.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import MemoryProposal, SpecialistResponse
from agent.config import REPO_ROOT
from agent.tools.capabilities.memory_service import MemoryCapabilityService


class MemoryAgent:
    name = "MemoryAgent"

    _KEYWORDS = ("memory", "memories", "remember", "preference", "preferences", "context")

    def __init__(self, vault_root: Path, memory_service: MemoryCapabilityService | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.memory_service = memory_service or MemoryCapabilityService(
            vault_root=self.vault_root,
            sessions_db=REPO_ROOT / "data" / "memory" / "sessions.db",
        )

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        pack = self.memory_service.build_context_pack(
            {"query": query, "thread_id": "default", "agent_name": self.name}
        )
        proposals = [
            MemoryProposal(
                scope="memory",
                claim="MemoryAgent should validate durable memories and provide context packs.",
                evidence=query,
                confidence=0.8,
            )
        ]
        reviewed = self.memory_service.review_proposals({"proposals": proposals})
        card_lines = [card["text"].strip() for card in pack.get("cards", []) if card.get("text")]
        summary = "Relevant memory context:\n" + "\n".join(card_lines[:3]) if card_lines else (
            "No matching memory cards found. MemoryAgent prepared a reviewed memory proposal."
        )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Built a context pack and reviewed memory proposals through memory capability service.",
            confidence=0.8,
            memory_proposals=[MemoryProposal(**item) for item in reviewed.get("accepted", [])],
        )

    def review_proposals(self, proposals: list[MemoryProposal]) -> list[MemoryProposal]:
        reviewed = self.memory_service.review_proposals({"proposals": proposals})
        return [MemoryProposal(**item) for item in reviewed["accepted"]]

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
```

- [ ] **Step 4: Run MemoryAgent tests**

Run:

```powershell
python -m pytest tests/test_specialist_agents.py::test_memory_agent_builds_context_pack_and_reviews_memory tests/test_memory_capability_service.py -q --basetemp .pytest-tmp
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add backend/agent/agents/memory_agent.py backend/agent/master/registry.py backend/tests/test_specialist_agents.py
git commit -m "feat: route memory agent through capability service"
```

---

## Task 6: YouTube Read-Only Capability Interface

**Files:**
- Create: `backend/agent/tools/capabilities/youtube_service.py`
- Modify: `backend/agent/tools/capabilities/__init__.py`
- Modify: `backend/agent/agents/youtube.py`
- Test: `backend/tests/test_youtube_capability_service.py`
- Test: `backend/tests/test_specialist_agents.py`

- [ ] **Step 1: Write failing YouTube service tests**

Create `backend/tests/test_youtube_capability_service.py`:

```python
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


def test_youtube_service_returns_read_only_unsupported_result_until_backend_configured():
    service = YoutubeCapabilityService()

    result = service.search_videos({"query": "Vellum demo", "max_results": 3})

    assert result["action"] == "youtube.search_videos"
    assert result["status"] == "unsupported"
    assert "read-only YouTube backend is not configured" in result["message"]


def test_youtube_service_registers_read_only_capabilities():
    registry = YoutubeCapabilityService().build_registry()

    assert "youtube.search_videos" in registry.names()
    assert "youtube.get_transcript" in registry.names()
    assert registry.get("youtube.search_videos").stream_label == "Searched YouTube"
```

- [ ] **Step 2: Run YouTube service tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_youtube_capability_service.py -q --basetemp .pytest-tmp
```

Expected: collection fails with `ModuleNotFoundError` for `youtube_service`.

- [ ] **Step 3: Implement YouTube service**

Create `backend/agent/tools/capabilities/youtube_service.py`:

```python
from __future__ import annotations

from typing import Any

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry


class YoutubeCapabilityService:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            CapabilityRecord(
                name="youtube.search_videos",
                namespace="youtube",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"YoutubeAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"}),
                stream_label="Searched YouTube",
                adapter=self.search_videos,
            )
        )
        registry.register(
            CapabilityRecord(
                name="youtube.get_transcript",
                namespace="youtube",
                access=CapabilityAccess.READ,
                allowed_agents=frozenset({"YoutubeAgent", "ResearchAgent", "MemoryAgent", "VellumAgent"}),
                stream_label="Read YouTube transcript",
                adapter=self.get_transcript,
            )
        )
        return registry

    def search_videos(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._unsupported("youtube.search_videos")

    def get_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._unsupported("youtube.get_transcript")

    def _unsupported(self, action: str) -> dict[str, str]:
        return {
            "action": action,
            "status": "unsupported",
            "message": "The read-only YouTube backend is not configured yet.",
        }
```

- [ ] **Step 4: Export YouTube service**

Modify `backend/agent/tools/capabilities/__init__.py`:

```python
from agent.tools.capabilities.mcp_service import McpCapabilityService
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService

__all__ = ["McpCapabilityService", "MemoryCapabilityService", "XCapabilityService", "YoutubeCapabilityService"]
```

- [ ] **Step 5: Update YoutubeAgent to call service**

Modify `backend/agent/agents/youtube.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

from agent.agents.base import SpecialistResponse
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


class YoutubeAgent:
    name = "YoutubeAgent"

    _SOURCE_KEYWORDS = ("youtube", "yt")

    def __init__(self, vault_root: Path, youtube_service: YoutubeCapabilityService | None = None) -> None:
        self.vault_root = Path(vault_root)
        self.youtube_service = youtube_service or YoutubeCapabilityService()

    def can_handle(self, query: str) -> bool:
        lowered = query.lower()
        return any(self._has_phrase(lowered, keyword) for keyword in self._SOURCE_KEYWORDS)

    def answer(self, query: str) -> SpecialistResponse:
        result = self.youtube_service.search_videos({"query": query, "max_results": 5})
        if result.get("status") == "unsupported":
            return SpecialistResponse(
                agent=self.name,
                status="needs_fetch",
                summary=result["message"],
                analysis="YoutubeAgent is wired to the shared YouTube capability interface; the read-only backend is next.",
                confidence=0.35,
            )
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=str(result),
            analysis="Used youtube.search_videos.",
            confidence=0.7,
        )

    def _has_phrase(self, lowered_query: str, phrase: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered_query) is not None
```

- [ ] **Step 6: Run YouTube tests**

Run:

```powershell
python -m pytest tests/test_youtube_capability_service.py tests/test_specialist_agents.py::test_youtube_agent_stub_defers_full_execution -q --basetemp .pytest-tmp
```

Expected: selected tests pass after updating `test_youtube_agent_stub_defers_full_execution` to assert `"read-only YouTube backend is not configured"` instead of `"full YouTube specialist execution deferred"`.

- [ ] **Step 7: Commit Task 6**

```powershell
git add backend/agent/tools/capabilities/youtube_service.py backend/agent/tools/capabilities/__init__.py backend/agent/agents/youtube.py backend/tests/test_youtube_capability_service.py backend/tests/test_specialist_agents.py
git commit -m "feat: add youtube capability interface"
```

---

## Task 7: Registry Wires Capability-Backed Pupils

**Files:**
- Modify: `backend/agent/master/registry.py`
- Test: `backend/tests/test_master_pupil.py`

- [ ] **Step 1: Add failing registry wiring test**

Append to `backend/tests/test_master_pupil.py`:

```python
def test_default_pupil_registry_uses_capability_backed_agents(tmp_path):
    registry = PupilRegistry.default(vault_root=tmp_path)

    assert hasattr(registry.get("XAgent"), "x_service")
    assert hasattr(registry.get("MemoryAgent"), "memory_service")
    assert hasattr(registry.get("YoutubeAgent"), "youtube_service")
```

- [ ] **Step 2: Run registry wiring test and verify it fails**

Run:

```powershell
python -m pytest tests/test_master_pupil.py::test_default_pupil_registry_uses_capability_backed_agents -q --basetemp .pytest-tmp
```

Expected: fails until all three agents expose the service attributes.

- [ ] **Step 3: Update default Pupil registry**

Modify `backend/agent/master/registry.py` so `PupilRegistry.default()` imports and instantiates services:

```python
from agent.tools.capabilities.memory_service import MemoryCapabilityService
from agent.tools.capabilities.x_service import XCapabilityService
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
from agent.config import REPO_ROOT

# inside default()
memory_service = MemoryCapabilityService(vault_root=root, sessions_db=REPO_ROOT / "data" / "memory" / "sessions.db")
pupils: list[SpecialistAgent] = [
    XAgent(vault_root=root, x_service=XCapabilityService()),
    YoutubeAgent(vault_root=root, youtube_service=YoutubeCapabilityService()),
    MemoryAgent(vault_root=root, memory_service=memory_service),
    SportsAgent(vault_root=root),
]
```

- [ ] **Step 4: Run registry and dispatcher tests**

Run:

```powershell
python -m pytest tests/test_master_pupil.py tests/test_specialist_agents.py -q --basetemp .pytest-tmp
```

Expected: selected tests pass.

- [ ] **Step 5: Commit Task 7**

```powershell
git add backend/agent/master/registry.py backend/tests/test_master_pupil.py
git commit -m "feat: wire capability backed pupil registry"
```

---

## Task 8: Verification and Cleanup

**Files:**
- Modify only files needed to fix verification failures.

- [ ] **Step 1: Run targeted backend suite**

Run:

```powershell
python -m pytest tests/test_tool_registry.py tests/test_x_capability_service.py tests/test_mcp_capability_service.py tests/test_memory_capability_service.py tests/test_youtube_capability_service.py tests/test_specialist_agents.py tests/test_master_pupil.py tests/test_live_sports_api.py tests/test_chat_stream_sources.py tests/test_agent_prompt.py -q --basetemp .pytest-tmp
```

Expected: all selected tests pass.

- [ ] **Step 2: Run existing X and memory tests**

Run:

```powershell
python -m pytest tests/test_x_tool.py tests/test_x_drivers.py tests/test_x_api_client.py tests/test_xai_x_search_client.py tests/test_memory.py tests/test_project_context.py tests/test_memory_sessions.py -q --basetemp .pytest-tmp
```

Expected: all selected tests pass. If `qdrant_client` is still missing in this local interpreter, do not include `tests/test_rag.py` in this command; note the missing dependency in the final report.

- [ ] **Step 3: Run frontend chat/source test**

Run:

```powershell
npm.cmd test -- vellum-chat-voice.test.js
```

Expected: `15 passed`.

- [ ] **Step 4: Run diff hygiene check**

Run:

```powershell
git diff --check
```

Expected: exit code `0`; line-ending warnings are acceptable on this Windows checkout.

- [ ] **Step 5: Remove temporary pytest folder if present**

Run:

```powershell
if (Test-Path backend\.pytest-tmp) { Remove-Item -LiteralPath backend\.pytest-tmp -Recurse -Force }
```

Expected: `backend/.pytest-tmp` no longer appears in `git status --short`.

- [ ] **Step 6: Commit verification cleanup**

If Task 8 required code or test fixes, commit them:

```powershell
git add backend/agent backend/tests frontend/ui
git commit -m "test: verify hybrid mcp pupil tools"
```

If Task 8 made no file changes, do not create an empty commit.

---

## Final Verification Checklist

- [ ] XAgent uses `XCapabilityService` and no longer returns only the old stub response for search questions.
- [ ] X posting remains gated by `confirm=True` and `X_TOOL_ALLOW_POSTS=true`.
- [ ] MemoryAgent can build context packs from durable memory cards.
- [ ] MemoryAgent filters low-confidence proposals.
- [ ] YouTubeAgent is wired to a read-only capability interface, even if the backend returns deterministic unsupported results in this phase.
- [ ] PupilRegistry creates service-backed X, YouTube, and Memory Pupils.
- [ ] Existing SportsAgent dispatch still works.
- [ ] Frontend remains a single Vellum chat with safe activity/source events.
- [ ] No OAuth token contents are logged, streamed, copied into Pupil memory, or written into tests.
