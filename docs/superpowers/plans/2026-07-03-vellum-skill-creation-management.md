# Vellum Skill Creation and Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add confirmed, atomic skill creation and package management plus a Hermes-style `/learn` authoring handoff.

**Architecture:** `SkillManager` owns every local package mutation and writes through validated staging. `SkillUsageStore` records creation provenance and patch counters atomically. LLM tools expose manager actions behind confirmation; `/learn` produces a standards-guided authoring request that must finish through `skill_manage`.

**Tech Stack:** Python 3.11+, pathlib, PyYAML, LangChain tools, pytest.

---

## Files

- Create `backend/agent/skills/usage.py`: atomic `.usage.json` access and provenance/counter updates.
- Create `backend/agent/skills/manager.py`: create, patch, edit, write-file, remove-file, archive, restore, and delete operations.
- Create `backend/agent/skills/authoring.py`: `/learn` standards prompt builder.
- Create `backend/agent/tools/skill_manage.py`: confirmed `skill_manage` and `skill_learn` tools.
- Modify `backend/agent/skills/__init__.py`: public exports.
- Modify `backend/agent/graph/agent.py`: register and document mutation/learn tools.
- Create `backend/tests/test_skill_usage.py`.
- Create `backend/tests/test_skill_manager.py`.
- Create `backend/tests/test_skill_authoring.py`.
- Create `backend/tests/test_skill_manage_tools.py`.
- Modify `backend/tests/test_agent_prompt.py`.

## Task 1: Usage Provenance Store

- [ ] Write tests proving a missing sidecar reads as empty, foreground creation stores `created_by: null`, background review stores `created_by: agent`, counters increment, and writes leave valid JSON.
- [ ] Run `backend/tests/test_skill_usage.py` and verify import failure for `SkillUsageStore`.
- [ ] Implement `SkillUsageStore(root)` with `get`, `all`, `mark_created`, `increment_view`, `increment_use`, `increment_patch`, and `set_state`. Use a process lock, write `<root>/.usage.json.tmp`, then `os.replace`.
- [ ] Run the tests and require all pass.

The test contract is:

```python
store = SkillUsageStore(tmp_path)
store.mark_created("foreground", origin="foreground")
store.mark_created("background", origin="background_review")
store.increment_patch("foreground")
assert store.get("foreground")["created_by"] is None
assert store.get("foreground")["patch_count"] == 1
assert store.get("background")["created_by"] == "agent"
json.loads((tmp_path / ".usage.json").read_text(encoding="utf-8"))
```

## Task 2: Atomic Package Manager

- [ ] Write tests for confirmation, foreground/background creation, collision refusal, invalid package rollback, exact patching, full edit, support-file write/removal, archive/restore, traversal rejection, and confirmed delete.
- [ ] Run `backend/tests/test_skill_manager.py` and verify import failure for `SkillManager`.
- [ ] Implement `SkillMutationError` and `SkillManager(root, require_confirmation=True)`.
- [ ] Run the tests and require all pass.

Public interface:

```python
class SkillManager:
    def create(self, skill_md: str, *, category: str = "uncategorized", origin: str = "foreground", confirm: bool = False) -> dict: ...
    def patch(self, name: str, old_text: str, new_text: str, *, confirm: bool = False) -> dict: ...
    def edit(self, name: str, skill_md: str, *, confirm: bool = False) -> dict: ...
    def write_file(self, name: str, path: str, content: str, *, confirm: bool = False) -> dict: ...
    def remove_file(self, name: str, path: str, *, confirm: bool = False) -> dict: ...
    def archive(self, name: str, *, confirm: bool = False) -> dict: ...
    def restore(self, name: str, *, confirm: bool = False) -> dict: ...
    def delete(self, name: str, *, confirm: bool = False) -> dict: ...
```

Rules:

- Confirmation is required for every mutation when `require_confirmation` is true.
- `create` parses staged `SKILL.md`, uses its normalized name, refuses collisions in active/archive/retired/proposed roots, and publishes under `packages/<category>/<name>`.
- Only `origin="background_review"` marks `created_by="agent"`; other origins store null.
- `patch` requires `old_text` to occur exactly once.
- `edit` stages a complete copy of the package with replaced `SKILL.md`, validates it, and requires the name to remain unchanged.
- `write_file` and `remove_file` reject absolute paths, traversal, symlinks, and `SKILL.md`; the resulting package must still validate.
- Archive and restore move whole packages and update sidecar state.
- Delete requires confirmation even if manager confirmation is disabled. Pin enforcement lands with curator telemetry.
- Every failed operation leaves the original package unchanged.

## Task 3: `/learn` Authoring Contract and Tools

- [ ] Write tests for a learn prompt sourced from URL, local directory, conversation procedure, or pasted notes; assert it requires Hermes section order, forbids invented commands, forbids private data/machine paths, and ends by calling `skill_manage(action="create")`.
- [ ] Write tool tests for missing confirmation, successful create, patch, support-file write, archive/restore, and clean error JSON.
- [ ] Run the two test files and verify RED.
- [ ] Implement `build_learn_prompt(source, focus="")` without network access; it guides the live agent to gather material through existing tools.
- [ ] Implement `skill_manage` actions and `skill_learn` prompt generation as LangChain tools.
- [ ] Run the tests and require GREEN.

Tool signature:

```python
skill_manage(
    action: str,
    name: str = "",
    skill_md: str = "",
    path: str = "",
    content: str = "",
    old_text: str = "",
    new_text: str = "",
    category: str = "uncategorized",
    origin: str = "foreground",
    confirm: bool = False,
) -> str
```

`skill_learn(source: str, focus: str = "")` returns authoring instructions only. It does not bypass privacy, fetch content independently, or write files.

## Task 4: Live Agent Integration and Verification

- [ ] Extend prompt/tool-list tests to require `skill_manage` and `skill_learn`.
- [ ] Register both tools in `core_tools()` and document that mutations require `confirm=true`, foreground creation is user-directed, and background provenance may only be used by the background review path.
- [ ] Run creation, manager, tool, runtime, prompt, and routing tests.
- [ ] Run `git diff --check`.

## Plan Self-Review

- Creation matches the user-selected Hermes foreground behavior.
- `/learn` remains a normal agent turn and cannot bypass Vellum's privacy gate.
- All filesystem writes route through one validating manager.
- Pin enforcement is intentionally deferred to curator, where pin jurisdiction is defined.

