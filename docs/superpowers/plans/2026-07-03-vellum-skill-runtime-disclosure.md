# Vellum Skill Runtime Disclosure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Hermes-style Level 0/1/2 skill disclosure to Vellum's live agent while preserving deterministic specialist routing and preventing machine paths from entering external model prompts.

**Architecture:** A shared runtime registry builds a compact Level 0 prompt index from canonical packages. Read-only `skills_list` and `skill_view` tools expose catalog metadata, full `SKILL.md` content, or one relative support file; the graph prompt includes only Level 0 and the model explicitly loads deeper levels.

**Tech Stack:** Python 3.11+, LangChain tools, LangGraph prompt callable, Pydantic v2, pytest.

---

## File Structure

- Create `backend/agent/skills/runtime.py`: shared registry construction and compact Level 0 prompt formatting.
- Create `backend/agent/tools/skills.py`: read-only `skills_list` and `skill_view` tools.
- Modify `backend/agent/skills/__init__.py`: export runtime helpers.
- Modify `backend/agent/graph/agent.py`: inject the Level 0 index, register tools, and document loading rules.
- Create `backend/tests/test_skill_runtime.py`: compact-index and privacy-boundary tests.
- Create `backend/tests/test_skill_tools.py`: Level 0/1/2 tool contract tests.
- Modify `backend/tests/test_agent_prompt.py`: live prompt and tool-list integration tests.

## Task 1: Compact Runtime Index

**Files:**
- Create: `backend/agent/skills/runtime.py`
- Modify: `backend/agent/skills/__init__.py`
- Create: `backend/tests/test_skill_runtime.py`

- [ ] **Step 1: Write failing runtime-index tests**

Create `backend/tests/test_skill_runtime.py`:

```python
from pathlib import Path

from agent.skills import SkillRegistry, build_skill_index_block


def write_skill(root: Path, name: str, description: str, body: str) -> None:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  hermes:\n    category: research\n---\n{body}\n",
        encoding="utf-8",
    )


def test_skill_index_contains_only_level_zero_metadata(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    write_skill(root / "research" / "sports-brief", "sports-brief", "Prepare sports briefs", "# Secret body\n\nPrivate procedure text.")

    block = build_skill_index_block(SkillRegistry(local_root=root))

    assert "## Available Skills" in block
    assert "sports-brief" in block
    assert "Prepare sports briefs" in block
    assert "research" in block
    assert "Private procedure text" not in block
    assert str(tmp_path) not in block


def test_skill_index_omits_unavailable_skills(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    package = root / "platform" / "mac-only"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: mac-only\ndescription: macOS workflow\nplatforms: [macos]\n---\n# macOS\n",
        encoding="utf-8",
    )

    block = build_skill_index_block(SkillRegistry(local_root=root, platform_name="windows"))

    assert block == ""
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
$env:PYTHONPATH='D:\Vellum;D:\Vellum\backend'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_skill_runtime.py -q
```

Expected: collection fails because `build_skill_index_block` is absent.

- [ ] **Step 3: Implement shared runtime helpers**

Create `backend/agent/skills/runtime.py`:

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agent.skills.registry import SkillRegistry


SKILLS_PATH = Path(__file__).resolve().parents[3] / ".skills"
CORE_TOOL_NAMES = {
    "append_to_note", "browser_action", "browser_click", "browser_close",
    "browser_hover", "browser_navigate", "browser_press_key", "browser_select_option",
    "browser_snapshot", "browser_tabs", "browser_type", "browser_wait", "computer_use",
    "computer_use_route", "context_mode", "create_note", "escalate_to_cloud", "git_action",
    "github_read", "github_write", "library_docs", "list_files", "memory_orchestrator",
    "obsidian_api", "read_file", "repo_docs", "search_amazon", "search_my_notes",
    "skills_list", "skill_view", "web_extract", "web_research", "web_search", "x_action",
}
CORE_TOOLSETS = {"browser", "filesystem", "github", "memory", "skills", "terminal", "web"}


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    return SkillRegistry(
        local_root=SKILLS_PATH / "packages",
        available_tools=set(CORE_TOOL_NAMES),
        available_toolsets=set(CORE_TOOLSETS),
    )


def build_skill_index_block(registry: SkillRegistry | None = None) -> str:
    active_registry = registry or get_skill_registry()
    entries = active_registry.list_skills()
    if not entries:
        return ""
    lines = [
        "## Available Skills",
        "Load a skill with skill_view only when its description matches the current task.",
    ]
    for entry in entries:
        lines.append(f"- {entry.name} [{entry.category}]: {entry.description}")
    return "\n".join(lines)
```

Export `CORE_TOOL_NAMES`, `CORE_TOOLSETS`, `build_skill_index_block`, and `get_skill_registry` from `backend/agent/skills/__init__.py`.

- [ ] **Step 4: Run and verify GREEN**

Run the Task 1 test command. Expected: 2 tests pass.

## Task 2: Read-Only Skill Tools

**Files:**
- Create: `backend/agent/tools/skills.py`
- Create: `backend/tests/test_skill_tools.py`

- [ ] **Step 1: Write failing Level 0/1/2 tool tests**

Create `backend/tests/test_skill_tools.py`:

```python
import json
from pathlib import Path

import pytest

from agent.skills import SkillRegistry
from agent.tools import skills as skill_tools


def make_registry(tmp_path: Path) -> SkillRegistry:
    package = tmp_path / "packages" / "research" / "sports-brief"
    package.mkdir(parents=True)
    (package / "references").mkdir()
    (package / "references" / "format.md").write_text("Use three bullets.", encoding="utf-8")
    (package / "SKILL.md").write_text(
        """---
name: sports-brief
description: Prepare sports briefs
metadata:
  hermes:
    category: research
---
# Sports Brief

## Procedure
Use source-backed facts.
""",
        encoding="utf-8",
    )
    return SkillRegistry(local_root=tmp_path / "packages")


def test_skills_list_returns_compact_metadata_without_machine_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skills_list.invoke({}))

    assert payload["skills"] == [
        {"name": "sports-brief", "description": "Prepare sports briefs", "category": "research", "available": True}
    ]
    assert str(tmp_path) not in json.dumps(payload)


def test_skill_view_returns_full_body_without_absolute_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skill_view.invoke({"name": "sports-brief"}))

    assert payload["name"] == "sports-brief"
    assert "Use source-backed facts" in payload["content"]
    assert "package_root" not in payload
    assert str(tmp_path) not in json.dumps(payload)


def test_skill_view_reads_one_relative_support_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skill_view.invoke({"name": "sports-brief", "path": "references/format.md"}))

    assert payload == {"name": "sports-brief", "path": "references/format.md", "content": "Use three bullets."}


def test_skill_view_reports_missing_skill_without_crashing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skill_view.invoke({"name": "missing"}))

    assert payload == {"ok": False, "error": "Skill not found: missing"}
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
$env:PYTHONPATH='D:\Vellum;D:\Vellum\backend'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_skill_tools.py -q
```

Expected: collection fails because `agent.tools.skills` is absent.

- [ ] **Step 3: Implement the tools**

Create `backend/agent/tools/skills.py`:

```python
from __future__ import annotations

import json

from langchain_core.tools import tool

from agent.skills import SkillPackageError, get_skill_registry


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


@tool
def skills_list(category: str = "", include_unavailable: bool = False) -> str:
    """List installed skills using compact metadata only."""
    entries = get_skill_registry().list_skills(include_unavailable=include_unavailable)
    skills = []
    for entry in entries:
        if category and entry.category.casefold() != category.casefold():
            continue
        item = {
            "name": entry.name,
            "description": entry.description,
            "category": entry.category,
            "available": entry.available,
        }
        if entry.unavailable_reason:
            item["unavailable_reason"] = entry.unavailable_reason
        skills.append(item)
    return _json({"skills": skills})


@tool
def skill_view(name: str, path: str = "") -> str:
    """Load a skill's full instructions or one relative support file."""
    registry = get_skill_registry()
    try:
        if path:
            return _json({"name": name, "path": path, "content": registry.view_file(name, path)})
        package = registry.view(name)
    except KeyError:
        return _json({"ok": False, "error": f"Skill not found: {name}"})
    except SkillPackageError as exc:
        return _json({"ok": False, "error": str(exc)})
    return _json(
        {
            "name": package.metadata.name,
            "description": package.metadata.description,
            "category": package.metadata.metadata.hermes.category,
            "metadata": package.metadata.model_dump(mode="json", exclude_none=True),
            "content": package.body,
        }
    )
```

- [ ] **Step 4: Run and verify GREEN**

Run the Task 2 test command. Expected: 4 tests pass.

## Task 3: Live Graph Integration

**Files:**
- Modify: `backend/agent/graph/agent.py`
- Modify: `backend/tests/test_agent_prompt.py`

- [ ] **Step 1: Write failing prompt and tool integration tests**

Append to `backend/tests/test_agent_prompt.py`:

```python
def test_vellum_prompt_includes_compact_skill_index_without_skill_body(monkeypatch):
    class FakeRegistry:
        def list_skills(self):
            from agent.skills import SkillIndexEntry
            return [SkillIndexEntry(name="sports-brief", description="Prepare sports briefs", category="research", state="active", available=True, package_root="C:/private/path", is_external=False)]

    monkeypatch.setattr(agent_graph, "_prompt_skill_registry", FakeRegistry(), raising=False)
    monkeypatch.setattr(agent_graph, "_prompt_project_ctx", None, raising=False)

    messages = agent_graph.vellum_prompt({"messages": [HumanMessage(content="sports update")]}, {})

    assert "## Available Skills" in messages[0].content
    assert "sports-brief" in messages[0].content
    assert "C:/private/path" not in messages[0].content


def test_agent_tool_list_includes_progressive_skill_tools(monkeypatch):
    captured = {}

    def fake_create_react_agent(**kwargs):
        captured["tools"] = kwargs["tools"]
        return object()

    monkeypatch.setattr(agent_graph, "create_react_agent", fake_create_react_agent)
    monkeypatch.setattr(agent_graph, "build_llm", lambda model=None: object())
    monkeypatch.setattr(agent_graph, "build_checkpointer", lambda: object())
    monkeypatch.setattr(agent_graph, "portable_agent_tools", lambda: [])

    agent_graph.build_agent()

    names = {getattr(item, "name", "") for item in captured["tools"]}
    assert {"skills_list", "skill_view"} <= names
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
$env:PYTHONPATH='D:\Vellum;D:\Vellum\backend'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_agent_prompt.py -q
```

Expected: the new tests fail because the prompt lacks the index and the tools are not registered.

- [ ] **Step 3: Integrate the index and tools**

In `backend/agent/graph/agent.py`:

1. Import `SkillRegistry`, `build_skill_index_block`, `get_skill_registry`, `skill_view`, and `skills_list`.
2. Add `skills_list` and `skill_view` to `core_tools()`.
3. Add these tool descriptions to `VELLUM_SYSTEM_PROMPT`:

```text
23. skills_list - List compact metadata for installed skills.
24. skill_view - Load one skill's full instructions or one relative support file.
```

4. Add this rule:

```text
- The Available Skills index contains descriptions only. Load a matching skill with skill_view before following it. Never infer instructions from the description alone. Use only relative support-file paths and never expose local package paths.
```

5. Add a module global and helper:

```python
_prompt_skill_registry: SkillRegistry | None = None


def _get_skill_registry() -> SkillRegistry:
    global _prompt_skill_registry
    if _prompt_skill_registry is None:
        _prompt_skill_registry = get_skill_registry()
    return _prompt_skill_registry
```

6. In `vellum_prompt`, build the index defensively:

```python
    skill_index = ""
    try:
        skill_index = build_skill_index_block(_get_skill_registry())
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("skill index load failed: %s", exc)
```

Prepend `skill_index` to `system_body` after `memory_block` and before the identity block. Do not call `SkillStore.build_prompt_block`; ordinary skill bodies remain on-demand.

- [ ] **Step 4: Run integrated runtime tests**

Run:

```powershell
$env:PYTHONPATH='D:\Vellum;D:\Vellum\backend'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_skill_runtime.py backend\tests\test_skill_tools.py backend\tests\test_agent_prompt.py backend\tests\test_skill_driven_routing.py -q
```

Expected: all tests pass, including deterministic routing.

## Task 4: Runtime Verification

- [ ] **Step 1: Run the complete focused skill suite**

```powershell
$env:PYTHONPATH='D:\Vellum;D:\Vellum\backend'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_skill_packages.py backend\tests\test_skill_registry.py backend\tests\test_skill_migration.py backend\tests\test_skill_runtime.py backend\tests\test_skill_tools.py backend\tests\test_memory.py backend\tests\test_skill_driven_routing.py backend\tests\test_agent_prompt.py -q
```

- [ ] **Step 2: Verify privacy and diff hygiene**

```powershell
git diff --check
```

Confirm runtime tool results and prompt blocks contain no absolute package path.

## Plan Self-Review

- Spec coverage: this plan implements progressive Level 0/1/2 disclosure, model-directed loading, live graph injection, and read-only tools while leaving mutation and telemetry to later plans.
- Privacy: unlike Hermes' local-only directory token, absolute skill paths never enter Vellum's external model context.
- Type consistency: all surfaces consume `SkillRegistry`, `SkillIndexEntry`, and `SkillPackage` from the foundation layer.
- Routing: `SkillRouteResolver` remains unchanged and continues to use the canonical compatibility facade.
