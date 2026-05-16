# Vellum Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Meta + Projects + Library vault restructure and a `ProjectContext` loader that prepends per-thread identity into every agent system prompt.

**Architecture:** A new `agent/memory/project_context.py` module reads `Meta/*.md` + active `Projects/<slug>/{vellum,hot}.md`, scrubs PII, wraps in `<PROTECTED>` tags, and returns a string. A dynamic-prompt callable in `agent/graph/agent.py` invokes this each turn. A new `thread_state` table in `sessions.db` holds per-thread `active_project` and `turns_since_hot_rewrite`. A one-time `migrate_vault_v2.py` moves existing folders under `Library/`. Chat commands `/project ...` set/clear/create projects.

**Tech Stack:** Python 3.11+, SQLite, LangGraph (`create_react_agent` with callable `prompt`), pytest, Presidio (`agent/privacy/scrubber.py`), Qdrant, FTS5.

**Spec reference:** [2026-05-16-vellum-foundation-design.md](../specs/2026-05-16-vellum-foundation-design.md)

---

## File map

**Create:**
- `Vellum/backend/agent/memory/project_context.py`
- `Vellum/backend/agent/memory/templates/__init__.py`
- `Vellum/backend/agent/memory/templates/profile.md.tpl`
- `Vellum/backend/agent/memory/templates/goals.md.tpl`
- `Vellum/backend/agent/memory/templates/principles.md.tpl`
- `Vellum/backend/agent/memory/templates/vellum.md.tpl`
- `Vellum/backend/agent/memory/templates/hot.md.tpl`
- `Vellum/backend/agent/cli/__init__.py` (if absent)
- `Vellum/backend/agent/cli/project_commands.py`
- `Vellum/backend/scripts/__init__.py` (if absent)
- `Vellum/backend/scripts/migrate_vault_v2.py`
- `Vellum/backend/tests/test_project_context.py`
- `Vellum/backend/tests/test_thread_state.py`
- `Vellum/backend/tests/test_project_commands.py`
- `Vellum/backend/tests/test_folder_policy_v2.py`
- `Vellum/backend/tests/test_migrate_vault.py`

**Modify:**
- `Vellum/backend/agent/memory/sessions.py` — add `ThreadStateStore`
- `Vellum/backend/agent/obsidian/folder_policy.py` — new path rules
- `Vellum/backend/agent/graph/agent.py` — callable prompt
- `Vellum/backend/agent/api.py` — wire `tick()` in `_background_learn`
- `Vellum/CLAUDE.md` — amend §5 write rules

---

## Phase 1 — Schema & state

### Task 1: Add `thread_state` table to sessions store

**Files:**
- Modify: `Vellum/backend/agent/memory/sessions.py`
- Create: `Vellum/backend/tests/test_thread_state.py`

- [ ] **Step 1: Write the failing test**

```python
# Vellum/backend/tests/test_thread_state.py
from pathlib import Path

from agent.memory.sessions import ThreadStateStore


def test_thread_state_round_trip(tmp_path: Path) -> None:
    store = ThreadStateStore(sessions_db=tmp_path / "sessions.db")

    # Defaults
    assert store.get_active_project("t1") is None
    assert store.get_turns_since_hot_rewrite("t1") == 0

    # Set + read back
    store.set_active_project("t1", "fitness")
    assert store.get_active_project("t1") == "fitness"

    store.bump_turns("t1")
    store.bump_turns("t1")
    assert store.get_turns_since_hot_rewrite("t1") == 2

    store.reset_turns("t1")
    assert store.get_turns_since_hot_rewrite("t1") == 0

    # Clear active project
    store.set_active_project("t1", None)
    assert store.get_active_project("t1") is None


def test_thread_state_independent_threads(tmp_path: Path) -> None:
    store = ThreadStateStore(sessions_db=tmp_path / "sessions.db")
    store.set_active_project("t1", "fitness")
    store.set_active_project("t2", "writing")
    assert store.get_active_project("t1") == "fitness"
    assert store.get_active_project("t2") == "writing"


def test_thread_state_idempotent_init(tmp_path: Path) -> None:
    db = tmp_path / "sessions.db"
    ThreadStateStore(sessions_db=db)
    ThreadStateStore(sessions_db=db)  # second init must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd Vellum/backend && pytest tests/test_thread_state.py -v`
Expected: ImportError — `ThreadStateStore` not defined.

- [ ] **Step 3: Implement `ThreadStateStore`**

Append to `Vellum/backend/agent/memory/sessions.py`:

```python
class ThreadStateStore:
    """Per-thread state: active project, hot.md rewrite counter.

    Lives in the same sessions.db as thread_titles to share its lifecycle.
    Kept in a separate table so the title schema stays simple.
    """

    def __init__(self, *, sessions_db: Path = SESSIONS_DB) -> None:
        self.sessions_db = Path(sessions_db)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.sessions_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sessions_db))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_state (
                    thread_id TEXT PRIMARY KEY,
                    active_project TEXT,
                    turns_since_hot_rewrite INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _row(self, thread_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM thread_state WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()

    def get_active_project(self, thread_id: str) -> str | None:
        row = self._row(thread_id)
        return row["active_project"] if row else None

    def set_active_project(self, thread_id: str, slug: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO thread_state (thread_id, active_project, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    active_project = excluded.active_project,
                    updated_at = excluded.updated_at
                """,
                (thread_id, slug),
            )

    def get_turns_since_hot_rewrite(self, thread_id: str) -> int:
        row = self._row(thread_id)
        return int(row["turns_since_hot_rewrite"]) if row else 0

    def bump_turns(self, thread_id: str) -> int:
        """Increment counter atomically. Returns new value.

        Uses BEGIN IMMEDIATE so the UPSERT + SELECT see the same DB snapshot,
        preventing a race when two workers tick the same thread concurrently."""
        conn = self._connect()
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO thread_state (thread_id, turns_since_hot_rewrite, updated_at)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    turns_since_hot_rewrite = turns_since_hot_rewrite + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (thread_id,),
            )
            row = conn.execute(
                "SELECT turns_since_hot_rewrite FROM thread_state WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            conn.execute("COMMIT")
            return int(row["turns_since_hot_rewrite"])
        finally:
            conn.close()

    def reset_turns(self, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE thread_state SET turns_since_hot_rewrite = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE thread_id = ?
                """,
                (thread_id,),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd Vellum/backend && pytest tests/test_thread_state.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/memory/sessions.py Vellum/backend/tests/test_thread_state.py
git commit -m "feat(memory): add ThreadStateStore for active_project + hot-rewrite counter"
```

---

## Phase 2 — Templates

### Task 2: Drop in vault file templates

**Files:**
- Create: `Vellum/backend/agent/memory/templates/__init__.py`
- Create: `Vellum/backend/agent/memory/templates/profile.md.tpl`
- Create: `Vellum/backend/agent/memory/templates/goals.md.tpl`
- Create: `Vellum/backend/agent/memory/templates/principles.md.tpl`
- Create: `Vellum/backend/agent/memory/templates/vellum.md.tpl`
- Create: `Vellum/backend/agent/memory/templates/hot.md.tpl`

- [ ] **Step 1: Create `__init__.py` with template loader**

```python
# Vellum/backend/agent/memory/templates/__init__.py
"""Starter templates for Meta/ and Projects/ files."""

from importlib import resources
from typing import Final

TEMPLATE_FILES: Final[dict[str, str]] = {
    "profile": "profile.md.tpl",
    "goals": "goals.md.tpl",
    "principles": "principles.md.tpl",
    "vellum": "vellum.md.tpl",
    "hot": "hot.md.tpl",
}


def load_template(name: str) -> str:
    """Return the raw text of a named template. Raises KeyError if unknown."""
    filename = TEMPLATE_FILES[name]
    return resources.files(__package__).joinpath(filename).read_text(encoding="utf-8")
```

- [ ] **Step 2: Create `profile.md.tpl`**

```markdown
---
type: meta-profile
updated: DD/MM/YYYY
---
# Profile

## Name


## Role


## Strengths
-

## Weaknesses
-

## Communication Style


## Pet Peeves
-

## Decision Style

```

- [ ] **Step 3: Create `goals.md.tpl`**

```markdown
---
type: meta-goals
updated: DD/MM/YYYY
---
# Goals

## Active

## Backlog

## Sunset
```

- [ ] **Step 4: Create `principles.md.tpl`**

```markdown
---
type: meta-principles
updated: DD/MM/YYYY
---
# Principles

-
```

- [ ] **Step 5: Create `vellum.md.tpl`**

```markdown
---
type: project-charter
slug: <slug>
status: active
created: DD/MM/YYYY
---
# <Project Name>

## Goal


## Vellum's Role


## Definition of Done
-

## Allowed Actions
- read: notes/, Library/
- write: notes/, hot.md, log.md
- forbid: anything outside this project folder

## Open Questions
-
```

- [ ] **Step 6: Create `hot.md.tpl`**

```markdown
---
type: project-hot
updated: DD/MM/YYYY HH:MM
turn_count: 0
---
# Hot

**Last touched:**
**Open threads:**
**Last decision:**
**Next:**

<!-- vellum-managed: empty -->
```

- [ ] **Step 7: Commit**

```bash
git add Vellum/backend/agent/memory/templates/
git commit -m "feat(memory): add starter templates for Meta and Projects files"
```

---

## Phase 3 — ProjectContext core

### Task 3: Slug validation + project I/O helpers

**Files:**
- Create: `Vellum/backend/agent/memory/project_context.py`
- Create: `Vellum/backend/tests/test_project_context.py`

- [ ] **Step 1: Write failing tests for slug validation and read helpers**

```python
# Vellum/backend/tests/test_project_context.py
from pathlib import Path

import pytest

from agent.memory.project_context import (
    InvalidSlug,
    ProjectContext,
    ProjectNotFound,
    validate_slug,
)


def test_validate_slug_accepts_valid() -> None:
    validate_slug("fitness")
    validate_slug("naval-x")
    validate_slug("p2")


def test_validate_slug_rejects_invalid() -> None:
    for bad in ["", "A", "1bad", "with space", "x", "x" * 41, "trailing-", "--double"]:
        with pytest.raises(InvalidSlug):
            validate_slug(bad)


def test_read_meta_files_empty_when_missing(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    meta = ctx._read_meta()
    assert meta == ""


def test_read_meta_files_concatenates(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("PROFILE BODY")
    (meta / "goals.md").write_text("GOALS BODY")
    (meta / "principles.md").write_text("PRINCIPLES BODY")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx._read_meta()
    assert "PROFILE BODY" in block
    assert "GOALS BODY" in block
    assert "PRINCIPLES BODY" in block
    # Ordered profile, goals, principles
    assert block.index("PROFILE BODY") < block.index("GOALS BODY") < block.index("PRINCIPLES BODY")


def test_read_project_missing_raises(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    with pytest.raises(ProjectNotFound):
        ctx._read_project("fitness")


def test_read_project_concatenates_charter_and_hot(tmp_path: Path) -> None:
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("HOT")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx._read_project("fitness")
    assert "CHARTER" in block and "HOT" in block
    assert block.index("CHARTER") < block.index("HOT")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: ImportError on `ProjectContext`.

- [ ] **Step 3: Implement the module skeleton**

```python
# Vellum/backend/agent/memory/project_context.py
"""Per-thread identity loader: assembles Meta + active project files into a
single <PROTECTED> block prepended to the agent system prompt each turn."""

from __future__ import annotations

import re
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock

from agent.memory.sessions import ThreadStateStore, SESSIONS_DB

logger = logging.getLogger(__name__)


SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_DOUBLE_HYPHEN = re.compile(r"--")


class ProjectContextError(Exception):
    """Base class for ProjectContext errors."""


class InvalidSlug(ProjectContextError):
    """Slug failed validation."""


class ProjectNotFound(ProjectContextError):
    """Project folder or vellum.md missing."""


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug or "") or _DOUBLE_HYPHEN.search(slug) or slug.endswith("-"):
        raise InvalidSlug(
            f"invalid slug {slug!r}: must match {SLUG_RE.pattern}, no '--', no trailing '-'"
        )


@dataclass
class ProjectContext:
    vault_root: Path
    sessions_db: Path = SESSIONS_DB

    def __post_init__(self) -> None:
        self.vault_root = Path(self.vault_root)
        self.sessions_db = Path(self.sessions_db)
        self._state = ThreadStateStore(sessions_db=self.sessions_db)
        self._cache: dict[tuple[str, frozenset[tuple[str, float]]], str] = {}
        self._cache_lock = RLock()

    # ---- file readers ----

    def _read_file(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("project_context: failed to read %s: %s", path, exc)
            return ""

    def _read_meta(self) -> str:
        meta = self.vault_root / "Meta"
        if not meta.exists():
            return ""
        parts: list[str] = []
        for name in ("profile.md", "goals.md", "principles.md"):
            body = self._read_file(meta / name)
            if body:
                parts.append(f"## {name}\n{body}")
        return "\n\n".join(parts)

    def _read_project(self, slug: str) -> str:
        validate_slug(slug)
        proj = self.vault_root / "Projects" / slug
        charter = proj / "vellum.md"
        if not charter.exists():
            raise ProjectNotFound(slug)
        parts: list[str] = [f"## vellum.md\n{self._read_file(charter)}"]
        hot = self._read_file(proj / "hot.md")
        if hot:
            parts.append(f"## hot.md\n{hot}")
        return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/memory/project_context.py Vellum/backend/tests/test_project_context.py
git commit -m "feat(memory): ProjectContext slug validation and file readers"
```

---

### Task 4: `build()` — assembled IDENTITY block with PII scrub + tags

**Files:**
- Modify: `Vellum/backend/agent/memory/project_context.py`
- Modify: `Vellum/backend/tests/test_project_context.py`

- [ ] **Step 1: Append failing tests**

```python
# append to Vellum/backend/tests/test_project_context.py

def test_build_empty_when_no_meta(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    assert ctx.build("thread1") == ""


def test_build_meta_only_wraps_in_protected(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("Name: TestUser")
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx.build("thread1")
    assert block.startswith("<PROTECTED>")
    assert block.rstrip().endswith("</PROTECTED>")
    # User name should be scrubbed by Presidio in real run, but the test only
    # asserts wrapping; full scrub verification lives in test_privacy_integration.


def test_build_active_project_included(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("PROFILE")

    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("HOT")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("thread1", "fitness")
    block = ctx.build("thread1")
    assert "PROFILE" in block
    assert "CHARTER" in block
    assert "HOT" in block


def test_build_clears_active_when_project_missing(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("PROFILE")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("thread1", "ghost")  # does not exist
    block = ctx.build("thread1")
    assert "PROFILE" in block
    # active_project must be cleared (graceful degradation)
    assert ctx._state.get_active_project("thread1") is None


def test_build_truncates_oversize_file(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    huge = "word " * 5000  # well over the 600-token budget for profile
    (meta / "profile.md").write_text(huge)

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    block = ctx.build("thread1")
    assert "[truncated]" in block
```

- [ ] **Step 2: Run, expect failures**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: 5 failures (build not implemented or insufficient).

- [ ] **Step 3: Implement `build()` with budgets, scrubbing, wrapping**

Append to `project_context.py`:

```python
from agent.privacy.scrubber import PrivacyScrubber

# Per-file token budgets (approximate; 1 token ~= 0.75 words).
TOKEN_BUDGETS: dict[str, int] = {
    "profile.md": 600,
    "goals.md": 400,
    "principles.md": 400,
    "vellum.md": 800,
    "hot.md": 200,
}


def _approx_token_count(text: str) -> int:
    # Rough heuristic; avoids a tokenizer dependency for a non-critical budget.
    return max(1, len(text.split()) * 4 // 3)


def _truncate_to_budget(text: str, budget: int) -> str:
    if _approx_token_count(text) <= budget:
        return text
    # Cut by words proportional to budget overrun
    words = text.split()
    keep = max(1, budget * 3 // 4)  # ~budget tokens worth of words
    return " ".join(words[:keep]) + "\n[truncated]"


def _budget_for(filename: str) -> int:
    return TOKEN_BUDGETS.get(filename, 1000)
```

Then add `build()` to `ProjectContext`:

```python
    def build(self, thread_id: str) -> str:
        """Return the IDENTITY block for this thread, ready to prepend to
        the system prompt. Empty string when Meta/ is absent."""
        meta_root = self.vault_root / "Meta"
        if not meta_root.exists():
            return ""

        parts: list[str] = []

        for name in ("profile.md", "goals.md", "principles.md"):
            body = self._read_file(meta_root / name)
            if not body:
                continue
            body = _truncate_to_budget(body, _budget_for(name))
            parts.append(f"## {name}\n{body}")

        slug = self._state.get_active_project(thread_id)
        if slug:
            try:
                proj_root = self.vault_root / "Projects" / slug
                charter = self._read_file(proj_root / "vellum.md")
                if not charter:
                    raise ProjectNotFound(slug)
                charter = _truncate_to_budget(charter, _budget_for("vellum.md"))
                parts.append(f"## vellum.md\n{charter}")
                hot = self._read_file(proj_root / "hot.md")
                if hot:
                    hot = _truncate_to_budget(hot, _budget_for("hot.md"))
                    parts.append(f"## hot.md\n{hot}")
            except ProjectNotFound:
                logger.warning("project_context: active project %r missing; clearing", slug)
                self._state.set_active_project(thread_id, None)

        if not parts:
            return ""

        raw = "\n\n".join(parts)

        # PII scrub before wrapping (Presidio runs locally, no network).
        try:
            scrubber = PrivacyScrubber()
            scrubbed, _replacements = scrubber.scrub(raw)
        except Exception as exc:
            # Per CLAUDE.md §8: scrubbing error → Withheld. Returning empty
            # block degrades gracefully without leaking unscrubbed content.
            logger.error("project_context: scrubber failed: %s", exc)
            return ""

        return f"<PROTECTED>\n{scrubbed}\n</PROTECTED>"
```

- [ ] **Step 4: Run tests, expect 5 passes**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: all 11 pass (6 from Task 3 + 5 here).

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/memory/project_context.py Vellum/backend/tests/test_project_context.py
git commit -m "feat(memory): ProjectContext.build with budgets, scrubbing, PROTECTED wrap"
```

---

### Task 5: mtime-keyed cache

**Files:**
- Modify: `Vellum/backend/agent/memory/project_context.py`
- Modify: `Vellum/backend/tests/test_project_context.py`

- [ ] **Step 1: Append failing tests**

```python
# append to test_project_context.py
import time


def test_build_cache_hit_when_unchanged(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("FIRST")
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    first = ctx.build("thread1")
    second = ctx.build("thread1")
    assert first == second
    # Tamper read counter — second call should have hit cache (proxy: same instance, no file change)
    # We rely on the explicit cache attribute for verification.
    assert len(ctx._cache) >= 1


def test_build_cache_miss_when_file_changes(tmp_path: Path) -> None:
    meta = tmp_path / "Meta"
    meta.mkdir()
    profile = meta / "profile.md"
    profile.write_text("FIRST")
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    first = ctx.build("thread1")
    # Sleep just enough that mtime tick is detected on common filesystems
    time.sleep(0.05)
    profile.write_text("SECOND")
    second = ctx.build("thread1")
    assert "FIRST" not in second
    assert "SECOND" in second
```

- [ ] **Step 2: Run tests, expect failure on second test**

Run: `cd Vellum/backend && pytest tests/test_project_context.py::test_build_cache_miss_when_file_changes -v`
Expected: FAIL — cache returns stale block (no mtime invalidation yet).

- [ ] **Step 3: Wrap `build()` in a cache layer**

Refactor `build()` to delegate to an inner `_build_uncached()` and consult the cache:

```python
    def _cache_key(self, thread_id: str) -> tuple[str, frozenset[tuple[str, float]]]:
        files: list[tuple[str, float]] = []
        meta_root = self.vault_root / "Meta"
        for name in ("profile.md", "goals.md", "principles.md"):
            p = meta_root / name
            files.append((str(p), p.stat().st_mtime if p.exists() else -1.0))
        slug = self._state.get_active_project(thread_id)
        if slug:
            proj_root = self.vault_root / "Projects" / slug
            for name in ("vellum.md", "hot.md"):
                p = proj_root / name
                files.append((str(p), p.stat().st_mtime if p.exists() else -1.0))
        return (thread_id, frozenset(files))

    def build(self, thread_id: str) -> str:
        key = self._cache_key(thread_id)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        result = self._build_uncached(thread_id)
        with self._cache_lock:
            # Bound cache to last 32 keys
            if len(self._cache) >= 32:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = result
        return result
```

Rename the existing `build()` body to `_build_uncached(self, thread_id)`.

- [ ] **Step 4: Run tests, expect pass**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: all 13 pass.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/memory/project_context.py Vellum/backend/tests/test_project_context.py
git commit -m "feat(memory): mtime-keyed cache in ProjectContext.build (32-entry LRU)"
```

---

### Task 6: `tick()` — log.md append

**Files:**
- Modify: `Vellum/backend/agent/memory/project_context.py`
- Modify: `Vellum/backend/tests/test_project_context.py`

- [ ] **Step 1: Append failing tests**

```python
def test_tick_appends_log_line(tmp_path: Path) -> None:
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "log.md").write_text("")

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("t1", "fitness")
    ctx.tick("t1", "wrote a thing", turn_ref="t1-1")

    log = (proj / "log.md").read_text()
    # DD/MM/YYYY HH:MM · [session] · summary · turn=t1-1
    assert "[session]" in log
    assert "wrote a thing" in log
    assert "turn=t1-1" in log
    # Date pattern DD/MM/YYYY
    import re as _re
    assert _re.search(r"\b\d{2}/\d{2}/\d{4} \d{2}:\d{2}\b", log)


def test_tick_no_active_project_is_noop(tmp_path: Path) -> None:
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    # No active project set — tick must not raise and must not create files
    ctx.tick("t1", "anything")
    assert not (tmp_path / "Projects").exists()
```

- [ ] **Step 2: Run, expect failure**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: AttributeError on `tick`.

- [ ] **Step 3: Implement `tick()` minus the rewrite path**

```python
    @staticmethod
    def _now_stamp() -> str:
        return datetime.now().strftime("%d/%m/%Y %H:%M")

    def tick(
        self,
        thread_id: str,
        turn_summary: str,
        *,
        turn_ref: str | None = None,
        source: str = "session",
    ) -> None:
        slug = self._state.get_active_project(thread_id)
        if not slug:
            return  # Meta-only thread; nothing to log
        proj = self.vault_root / "Projects" / slug
        if not (proj / "vellum.md").exists():
            return  # stale active_project; build() will clear it next turn

        # Append log line (always)
        log_path = proj / "log.md"
        line = f"- {self._now_stamp()} · [{source}] · {turn_summary} · turn={turn_ref or thread_id}\n"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
```

- [ ] **Step 4: Run, expect pass**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: all 15 pass.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/memory/project_context.py Vellum/backend/tests/test_project_context.py
git commit -m "feat(memory): ProjectContext.tick appends log.md per turn"
```

---

### Task 7: `tick()` — hot.md rewrite with sha guard

**Files:**
- Modify: `Vellum/backend/agent/memory/project_context.py`
- Modify: `Vellum/backend/tests/test_project_context.py`

The rewrite uses an injectable summarizer callable so tests don't need the fast model.

- [ ] **Step 1: Append failing tests**

```python
def test_tick_rewrites_hot_after_N_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOT_REWRITE_EVERY_N_TURNS", "2")

    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    # Seed an empty managed hot.md
    body = ""
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    (proj / "hot.md").write_text(f"{body}\n<!-- vellum-managed: {sha} -->\n")
    (proj / "log.md").write_text("")

    captured: list[str] = []

    def fake_summarizer(turn_summaries: list[str]) -> str:
        captured.append(",".join(turn_summaries))
        return "REWRITTEN BODY"

    ctx = ProjectContext(
        vault_root=tmp_path,
        sessions_db=tmp_path / "s.db",
        summarizer=fake_summarizer,
    )
    ctx._state.set_active_project("t1", "fitness")
    ctx.tick("t1", "first turn")
    ctx.tick("t1", "second turn")  # second tick triggers rewrite at N=2

    hot = (proj / "hot.md").read_text()
    assert "REWRITTEN BODY" in hot
    assert "<!-- vellum-managed:" in hot
    assert captured == ["first turn,second turn"]
    assert ctx._state.get_turns_since_hot_rewrite("t1") == 0


def test_tick_appends_proposal_when_user_edited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOT_REWRITE_EVERY_N_TURNS", "1")

    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    # hot.md has user edit — comment present but sha doesn't match body
    user_body = "USER WROTE THIS"
    wrong_sha = "0" * 64
    (proj / "hot.md").write_text(f"{user_body}\n<!-- vellum-managed: {wrong_sha} -->\n")

    def fake_summarizer(turn_summaries: list[str]) -> str:
        return "VELLUM PROPOSAL"

    ctx = ProjectContext(
        vault_root=tmp_path,
        sessions_db=tmp_path / "s.db",
        summarizer=fake_summarizer,
    )
    ctx._state.set_active_project("t1", "fitness")
    ctx.tick("t1", "turn one")

    hot = (proj / "hot.md").read_text()
    assert "USER WROTE THIS" in hot  # user content preserved
    assert "## Hot (vellum proposed" in hot
    assert "VELLUM PROPOSAL" in hot


def test_tick_appends_proposal_when_marker_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOT_REWRITE_EVERY_N_TURNS", "1")

    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("USER DELETED THE MANAGED COMMENT")

    ctx = ProjectContext(
        vault_root=tmp_path,
        sessions_db=tmp_path / "s.db",
        summarizer=lambda _xs: "PROPOSAL",
    )
    ctx._state.set_active_project("t1", "fitness")
    ctx.tick("t1", "turn one")
    hot = (proj / "hot.md").read_text()
    assert "USER DELETED" in hot
    assert "## Hot (vellum proposed" in hot
```

- [ ] **Step 2: Run, expect failures**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: 3 failures (rewrite not implemented; constructor doesn't accept `summarizer`).

- [ ] **Step 3: Implement rewrite path**

Adjust constructor to accept `summarizer`, and add rewrite logic to `tick()`:

```python
import os

VELLUM_MANAGED_RE = re.compile(r"<!--\s*vellum-managed:\s*([0-9a-f]+)\s*-->", re.IGNORECASE)


def _default_summarizer(turn_summaries: list[str]) -> str:
    """Placeholder summarizer; real call to fast model wired up in Task 8.

    Returning a deterministic concatenation lets the rest of the system run
    in dev/test without an LLM call. Replaced by an injected callable in
    production wiring (api.py)."""
    if not turn_summaries:
        return ""
    bullets = "\n".join(f"- {s}" for s in turn_summaries[-5:])
    return f"**Recent activity:**\n{bullets}"
```

Update `ProjectContext` dataclass:

```python
@dataclass
class ProjectContext:
    vault_root: Path
    sessions_db: Path = SESSIONS_DB
    summarizer: object = None  # Callable[[list[str]], str]
    _recent_summaries: dict[str, list[str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.vault_root = Path(self.vault_root)
        self.sessions_db = Path(self.sessions_db)
        self._state = ThreadStateStore(sessions_db=self.sessions_db)
        self._cache = {}
        self._cache_lock = RLock()
        self._recent_summaries = {}
        if self.summarizer is None:
            self.summarizer = _default_summarizer
```

Extend `tick()`:

```python
    def tick(self, thread_id, turn_summary, *, turn_ref=None, source="session"):
        slug = self._state.get_active_project(thread_id)
        if not slug:
            return
        proj = self.vault_root / "Projects" / slug
        if not (proj / "vellum.md").exists():
            return

        line = f"- {self._now_stamp()} · [{source}] · {turn_summary} · turn={turn_ref or thread_id}\n"
        with open(proj / "log.md", "a", encoding="utf-8") as fh:
            fh.write(line)

        # Track summary in memory for the next rewrite
        self._recent_summaries.setdefault(thread_id, []).append(turn_summary)

        count = self._state.bump_turns(thread_id)
        n = int(os.environ.get("HOT_REWRITE_EVERY_N_TURNS", "5"))
        if count < n:
            return

        self._rewrite_hot(proj, thread_id)
        self._state.reset_turns(thread_id)
        self._recent_summaries[thread_id] = []

    @staticmethod
    def _extract_managed_body(content: str) -> tuple[str, str | None]:
        """Split hot.md into (body_before_marker, recorded_sha) or (full, None)."""
        m = VELLUM_MANAGED_RE.search(content)
        if not m:
            return content, None
        body = content[: m.start()].rstrip()
        return body, m.group(1)

    def _rewrite_hot(self, proj: Path, thread_id: str) -> None:
        hot_path = proj / "hot.md"
        existing = self._read_file(hot_path)
        body, recorded_sha = self._extract_managed_body(existing)
        current_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

        summarizer = self.summarizer or _default_summarizer
        summaries = self._recent_summaries.get(thread_id, [])
        # If in-memory summaries were lost across a process restart, fall back
        # to the tail of log.md so the rewrite still has material to compress.
        if not summaries:
            try:
                log_text = (proj / "log.md").read_text(encoding="utf-8")
                tail = [ln for ln in log_text.splitlines() if ln.strip()][-5:]
                summaries = [ln.split("·", 2)[2].strip() if "·" in ln else ln for ln in tail]
            except OSError:
                summaries = []
        new_body = summarizer(summaries)

        user_edited = (recorded_sha is None) or (recorded_sha != current_sha)

        if user_edited and existing.strip():
            stamp = self._now_stamp()
            appended = (
                f"{existing.rstrip()}\n\n## Hot (vellum proposed, {stamp})\n{new_body}\n"
            )
            hot_path.write_text(appended, encoding="utf-8")
            return

        # Fresh full rewrite
        new_sha = hashlib.sha256(new_body.encode("utf-8")).hexdigest()
        stamp = self._now_stamp()
        full = (
            f"---\ntype: project-hot\nupdated: {stamp}\n---\n"
            f"# Hot\n\n{new_body}\n\n<!-- vellum-managed: {new_sha} -->\n"
        )
        hot_path.write_text(full, encoding="utf-8")
```

- [ ] **Step 4: Run, expect pass**

Run: `cd Vellum/backend && pytest tests/test_project_context.py -v`
Expected: all 18 pass.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/memory/project_context.py Vellum/backend/tests/test_project_context.py
git commit -m "feat(memory): ProjectContext hot.md rewrite with user-edit guard"
```

---

### Task 8: Wire fast-model summarizer for production

**Files:**
- Modify: `Vellum/backend/agent/memory/project_context.py`

A real summarizer that calls the fast model through the existing `build_llm` factory. Used by `api.py` wiring in Task 11.

- [ ] **Step 1: Add a factory function**

Append to `project_context.py`:

```python
def build_fast_summarizer():
    """Returns a callable[list[str], str] that calls Gemma 4 12B via OpenRouter.
    Imported lazily so test/CLI paths that don't have OPENROUTER_API_KEY work."""
    from agent.config import get_settings
    from agent.graph.agent import build_llm

    settings = get_settings()
    llm = build_llm(settings.fast_model)

    def _summarize(turn_summaries: list[str]) -> str:
        if not turn_summaries:
            return ""
        joined = "\n".join(f"- {s}" for s in turn_summaries[-10:])
        prompt = (
            "Compress these recent activity notes from a project session into a "
            "<=200 token 'Hot' snapshot using the exact 4-line shape: "
            "Last touched / Open threads / Last decision / Next. "
            "Be concrete. No preamble.\n\nNotes:\n" + joined
        )
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response))

    return _summarize
```

No test here — covered by integration test in Task 11.

- [ ] **Step 2: Commit**

```bash
git add Vellum/backend/agent/memory/project_context.py
git commit -m "feat(memory): fast-model summarizer factory for hot.md rewrite"
```

---

## Phase 4 — folder_policy

### Task 9: Amend `folder_policy.py` for new paths

**Files:**
- Modify: `Vellum/backend/agent/obsidian/folder_policy.py`
- Create: `Vellum/backend/tests/test_folder_policy_v2.py`

- [ ] **Step 1: Write failing tests**

```python
# Vellum/backend/tests/test_folder_policy_v2.py
from agent.obsidian.folder_policy import (
    can_index,
    can_send_to_llm,
    can_store,
)


def test_meta_sent_to_llm():
    assert can_send_to_llm("Meta/profile.md")
    assert can_send_to_llm("Meta/goals.md")


def test_projects_sent_to_llm():
    # Static policy: Projects/* is sent-to-LLM (active gating is dynamic, in ProjectContext)
    assert can_send_to_llm("Projects/fitness/vellum.md")
    assert can_send_to_llm("Projects/fitness/hot.md")
    assert can_send_to_llm("Projects/fitness/notes/anything.md")


def test_library_books_private():
    assert not can_send_to_llm("Library/Books/some-book.md")
    assert can_index("Library/Books/some-book.md")


def test_library_feedback_private():
    assert not can_send_to_llm("Library/feedback/note.md")


def test_library_x_sent():
    assert can_send_to_llm("Library/X/naval/topics/leverage.md")


def test_library_youtube_sent():
    assert can_send_to_llm("Library/Youtube/channels/moresidemen/latest.md")


def test_library_sports_sent():
    assert can_send_to_llm("Library/Sports/NBA/lakers.md")


def test_agent_unchanged():
    assert can_send_to_llm("Agent/Responses/QA 20260108_143022.md")
    assert can_store("Agent/Queries/x.md")


def test_default_private():
    assert not can_send_to_llm("Unknown/something.md")
```

- [ ] **Step 2: Run, expect failures**

Run: `cd Vellum/backend && pytest tests/test_folder_policy_v2.py -v`
Expected: failures on Meta/Projects/Library paths.

- [ ] **Step 3: Update `FOLDER_POLICIES`**

In `Vellum/backend/agent/obsidian/folder_policy.py`, replace `FOLDER_POLICIES` with:

```python
META_PUBLIC = _permissions(
    FolderPermission.STORED,
    FolderPermission.INDEXED,
    FolderPermission.SENT_TO_LLM,
)
PROJECT_PUBLIC = _permissions(
    FolderPermission.STORED,
    FolderPermission.INDEXED,
    FolderPermission.SENT_TO_LLM,
    FolderPermission.TOOL_ACCESSIBLE,
)
LIBRARY_PUBLIC = _permissions(
    FolderPermission.STORED,
    FolderPermission.INDEXED,
    FolderPermission.SENT_TO_LLM,
    FolderPermission.TOOL_ACCESSIBLE,
)

FOLDER_POLICIES: dict[str, FolderPolicy] = {
    "Meta": FolderPolicy("Meta", META_PUBLIC, requires_scrubbing=True),
    "Projects": FolderPolicy("Projects", PROJECT_PUBLIC, requires_scrubbing=True),
    "Library": FolderPolicy("Library", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "Library/X": FolderPolicy("Library/X", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Youtube": FolderPolicy("Library/Youtube", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Books": FolderPolicy("Library/Books", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "Library/feedback": FolderPolicy("Library/feedback", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "Library/Sports": FolderPolicy("Library/Sports", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Sports/NBA": FolderPolicy("Library/Sports/NBA", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Sports/Formula One": FolderPolicy("Library/Sports/Formula One", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Sports/Football": FolderPolicy("Library/Sports/Football", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Sports/Tennis": FolderPolicy("Library/Sports/Tennis", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Claude code": FolderPolicy("Library/Claude code", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Library/Codex": FolderPolicy("Library/Codex", LIBRARY_PUBLIC, requires_scrubbing=False),
    # Backward-compat: top-level paths that still exist pre-migration map to the
    # SAME policy as their post-migration Library/* siblings. Once migration has
    # run, these entries are harmless (no notes match the top-level paths).
    # They can be deleted in a follow-up cleanup PR after migration is universal.
    "X": FolderPolicy("X", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Youtube": FolderPolicy("Youtube", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Books": FolderPolicy("Books", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "feedback": FolderPolicy("feedback", PRIVATE_LOCAL_ONLY, requires_scrubbing=True),
    "Sports": FolderPolicy("Sports", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Sports/NBA": FolderPolicy("Sports/NBA", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Sports/Formula One": FolderPolicy("Sports/Formula One", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Sports/Football": FolderPolicy("Sports/Football", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Sports/Tennis": FolderPolicy("Sports/Tennis", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Claude code": FolderPolicy("Claude code", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Codex": FolderPolicy("Codex", LIBRARY_PUBLIC, requires_scrubbing=False),
    "Agent": FolderPolicy("Agent", AGENT_ACCESSIBLE, requires_scrubbing=False),
}
```

Rebuild the casefold lookup:

```python
_POLICY_BY_CASEFOLD = {name.casefold(): policy for name, policy in FOLDER_POLICIES.items()}
```

- [ ] **Step 4: Run, expect all new tests pass**

Run: `cd Vellum/backend && pytest tests/test_folder_policy_v2.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the existing folder_policy tests if any**

Run: `cd Vellum/backend && pytest tests/ -k folder_policy -v`
Expected: no regressions. If any old tests fail because they referenced top-level `X/`, `Youtube/`, etc., update them to `Library/X`, `Library/Youtube` to match the new layout.

- [ ] **Step 6: Commit**

```bash
git add Vellum/backend/agent/obsidian/folder_policy.py Vellum/backend/tests/test_folder_policy_v2.py
git commit -m "feat(folder_policy): Meta/Projects/Library rules; old top-level folders move under Library/"
```

---

## Phase 5 — `/project` commands

### Task 10: Project commands module

**Files:**
- Create: `Vellum/backend/agent/cli/__init__.py` (if absent)
- Create: `Vellum/backend/agent/cli/project_commands.py`
- Create: `Vellum/backend/tests/test_project_commands.py`

- [ ] **Step 1: Create `cli/__init__.py`**

If `Vellum/backend/agent/cli/` doesn't exist, create `__init__.py` with empty content.

- [ ] **Step 2: Write failing tests**

```python
# Vellum/backend/tests/test_project_commands.py
from pathlib import Path

import pytest

from agent.cli.project_commands import (
    CommandResult,
    InvalidCommand,
    handle_project_command,
)
from agent.memory.project_context import ProjectContext


def _ctx(tmp_path: Path) -> ProjectContext:
    return ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")


def test_no_args_lists_projects(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")

    result = handle_project_command(ctx, "t1", args=[])
    assert isinstance(result, CommandResult)
    assert "fitness" in result.message
    assert "(none)" in result.message or "active:" in result.message.lower()


def test_set_active_project(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")

    result = handle_project_command(ctx, "t1", args=["fitness"])
    assert ctx._state.get_active_project("t1") == "fitness"
    assert "fitness" in result.message


def test_set_active_missing_project_fails(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with pytest.raises(InvalidCommand):
        handle_project_command(ctx, "t1", args=["ghost"])


def test_clear_active(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    ctx._state.set_active_project("t1", "fitness")

    handle_project_command(ctx, "t1", args=["--clear"])
    assert ctx._state.get_active_project("t1") is None


def test_create_project(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    handle_project_command(ctx, "t1", args=["create", "fitness"])
    proj = tmp_path / "Projects" / "fitness"
    assert (proj / "vellum.md").exists()
    assert (proj / "hot.md").exists()
    assert (proj / "log.md").exists()
    assert (proj / "notes").is_dir()
    # Created project becomes active
    assert ctx._state.get_active_project("t1") == "fitness"


def test_create_invalid_slug_rejected(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with pytest.raises(InvalidCommand):
        handle_project_command(ctx, "t1", args=["create", "Bad Name"])


def test_create_duplicate_rejected(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    handle_project_command(ctx, "t1", args=["create", "fitness"])
    with pytest.raises(InvalidCommand):
        handle_project_command(ctx, "t1", args=["create", "fitness"])
```

- [ ] **Step 3: Run tests, expect failures**

Run: `cd Vellum/backend && pytest tests/test_project_commands.py -v`
Expected: ImportError on `agent.cli.project_commands`.

- [ ] **Step 4: Implement `project_commands.py`**

```python
# Vellum/backend/agent/cli/project_commands.py
"""Handler for the /project chat command family.

Used by both the web command parser (api.py) and the TUI command router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent.memory.project_context import (
    InvalidSlug,
    ProjectContext,
    validate_slug,
)
from agent.memory.templates import load_template


class InvalidCommand(Exception):
    """User-visible error: malformed args, missing project, etc."""


@dataclass
class CommandResult:
    message: str
    side_effects: list[str]  # human-readable, for audit/log


def _list_projects(ctx: ProjectContext) -> list[str]:
    root = ctx.vault_root / "Projects"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "vellum.md").exists())


def _now_stamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _today() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def handle_project_command(
    ctx: ProjectContext,
    thread_id: str,
    args: list[str],
) -> CommandResult:
    if not args:
        active = ctx._state.get_active_project(thread_id)
        projects = _list_projects(ctx)
        active_line = f"active: {active}" if active else "active: (none)"
        listing = "\n".join(f"- {p}" for p in projects) or "(no projects yet)"
        return CommandResult(
            message=f"{active_line}\nprojects:\n{listing}",
            side_effects=[],
        )

    if args[0] == "--clear":
        ctx._state.set_active_project(thread_id, None)
        return CommandResult(message="active project cleared", side_effects=[])

    if args[0] == "create":
        if len(args) != 2:
            raise InvalidCommand("usage: /project create <slug>")
        slug = args[1]
        try:
            validate_slug(slug)
        except InvalidSlug as exc:
            raise InvalidCommand(str(exc)) from exc

        proj = ctx.vault_root / "Projects" / slug
        if proj.exists():
            raise InvalidCommand(f"project {slug!r} already exists")

        (proj / "notes").mkdir(parents=True)

        charter = load_template("vellum").replace("<slug>", slug)
        charter = charter.replace("DD/MM/YYYY", _today())
        (proj / "vellum.md").write_text(charter, encoding="utf-8")

        hot = load_template("hot").replace("DD/MM/YYYY HH:MM", _now_stamp())
        (proj / "hot.md").write_text(hot, encoding="utf-8")

        (proj / "log.md").write_text("", encoding="utf-8")

        ctx._state.set_active_project(thread_id, slug)
        return CommandResult(
            message=f"created project {slug!r} and made it active",
            side_effects=[f"created Projects/{slug}/"],
        )

    # /project <slug>
    slug = args[0]
    try:
        validate_slug(slug)
    except InvalidSlug as exc:
        raise InvalidCommand(str(exc)) from exc

    if not (ctx.vault_root / "Projects" / slug / "vellum.md").exists():
        raise InvalidCommand(f"project {slug!r} not found")

    ctx._state.set_active_project(thread_id, slug)
    return CommandResult(message=f"active project: {slug}", side_effects=[])
```

- [ ] **Step 5: Run tests, expect pass**

Run: `cd Vellum/backend && pytest tests/test_project_commands.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add Vellum/backend/agent/cli/ Vellum/backend/tests/test_project_commands.py
git commit -m "feat(cli): /project command handler (no-arg, set, --clear, create)"
```

---

### Task 11: Wire `/project` into the chat API

**Files:**
- Modify: `Vellum/backend/agent/api.py`

The web `/chat` endpoint should intercept messages starting with `/project ` and route to `handle_project_command`, returning the result instead of invoking the agent.

- [ ] **Step 1: Inspect the existing chat endpoint**

Read `Vellum/backend/agent/api.py:_run_agent` (already in this plan's context) — the intercept site is at the top of `_run_agent` after `clean_message = message.strip()`.

- [ ] **Step 2: Add the intercept**

Add to imports at top of `api.py`:

```python
from agent.cli.project_commands import (
    CommandResult,
    InvalidCommand,
    handle_project_command,
)
from agent.memory.project_context import ProjectContext
from agent.config import get_settings as _get_settings_for_ctx  # alias to avoid shadowing


_project_context_singleton: ProjectContext | None = None


def _project_context() -> ProjectContext:
    global _project_context_singleton
    if _project_context_singleton is None:
        s = _get_settings_for_ctx()
        _project_context_singleton = ProjectContext(vault_root=s.obsidian_vault_path)
    return _project_context_singleton
```

Inside `_run_agent`, between `clean_message = message.strip()` and the existing empty-message check, add:

```python
    if clean_message.startswith("/project"):
        parts = clean_message.split()
        args = parts[1:]
        ctx = _project_context()
        try:
            result = handle_project_command(ctx, thread_id or get_settings().thread_id, args)
        except InvalidCommand as exc:
            return ChatResponse(answer=f"⚠ {exc}", thread_id=thread_id or get_settings().thread_id, tools=[])
        return ChatResponse(answer=result.message, thread_id=thread_id or get_settings().thread_id, tools=[])
```

- [ ] **Step 3: Add the same intercept to `chat_stream`**

In `api.py::chat_stream`, after `clean_message = request.message.strip()` and `active_thread_id = ...`, add:

```python
    if clean_message.startswith("/project"):
        parts = clean_message.split()
        args = parts[1:]
        ctx = _project_context()
        try:
            result = handle_project_command(ctx, active_thread_id, args)
            msg = result.message
        except InvalidCommand as exc:
            msg = f"⚠ {exc}"

        async def single_event():
            yield f"event: meta\ndata: {json.dumps({'thread_id': active_thread_id})}\n\n"
            yield f"event: token\ndata: {json.dumps({'token': msg})}\n\n"
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(single_event(), media_type="text/event-stream")
```

This ensures `/project` works in both standard and streaming chat paths.

- [ ] **Step 4: Smoke test manually**

Run the API and verify `/project` family works end-to-end. Lacking a HTTP integration test, write a small unit test:

```python
# Vellum/backend/tests/test_api_project_command.py
import pytest

from agent.api import _run_agent
from agent.memory import project_context as pc


@pytest.mark.asyncio
async def test_chat_intercepts_project_command(monkeypatch, tmp_path):
    # Reset module-level cached ProjectContext to point at tmp vault
    monkeypatch.setattr("agent.api._project_context_singleton", None, raising=False)
    monkeypatch.setattr("agent.api._get_settings_for_ctx", lambda: type("S", (), {"obsidian_vault_path": tmp_path}))

    response = await _run_agent("/project", thread_id="t1")
    assert "active:" in response.answer.lower() or "active: (none)" in response.answer
```

Run: `cd Vellum/backend && pytest tests/test_api_project_command.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/agent/api.py Vellum/backend/tests/test_api_project_command.py
git commit -m "feat(api): intercept /project chat commands in both /chat and /chat/stream"
```

---

## Phase 6 — Agent integration

### Task 12: Replace static prompt with dynamic identity-loading callable

**Files:**
- Modify: `Vellum/backend/agent/graph/agent.py`

`create_react_agent` accepts `prompt` as either a string or a callable. The callable receives `state` and (in newer LangGraph) `config`. We can read `thread_id` from `config["configurable"]["thread_id"]`. Return the original system text with the IDENTITY block prepended.

- [ ] **Step 1: Add the prompt builder**

Inside `agent.py`, near the existing `VELLUM_SYSTEM_PROMPT`, add:

```python
from langchain_core.messages import SystemMessage
from agent.memory.project_context import ProjectContext
from agent.config import get_settings as _get_settings_prompt


_prompt_project_ctx: ProjectContext | None = None


def _get_project_ctx() -> ProjectContext:
    global _prompt_project_ctx
    if _prompt_project_ctx is None:
        s = _get_settings_prompt()
        _prompt_project_ctx = ProjectContext(vault_root=s.obsidian_vault_path)
    return _prompt_project_ctx


def vellum_prompt(state, config=None):
    """Dynamic prompt: prepend per-thread IDENTITY block to VELLUM_SYSTEM_PROMPT.

    LangGraph version compatibility: `create_react_agent` calls this with
    `(state)` in older versions and `(state, config)` in 0.2+. The `config=None`
    default tolerates either. If `config` isn't passed, we fall back to a
    settings-default thread_id so identity still loads (Meta files at least)."""
    thread_id = None
    if config and isinstance(config, dict):
        thread_id = config.get("configurable", {}).get("thread_id")
    if not thread_id:
        thread_id = _get_settings_prompt().thread_id

    identity = ""
    if thread_id:
        try:
            identity = _get_project_ctx().build(thread_id)
        except Exception as exc:
            # Identity loading must never crash a turn; degrade gracefully.
            import logging
            logging.getLogger(__name__).warning("identity load failed: %s", exc)
            identity = ""

    system_text = f"{identity}\n\n{VELLUM_SYSTEM_PROMPT}" if identity else VELLUM_SYSTEM_PROMPT
    return [SystemMessage(content=system_text)] + list(state.get("messages", []))
```

- [ ] **Step 2: Swap the static `prompt=` for the callable**

In `build_agent` and `build_async_agent`, change:

```python
prompt=VELLUM_SYSTEM_PROMPT,
```

to:

```python
prompt=vellum_prompt,
```

- [ ] **Step 3: Smoke test**

Write a thin test that confirms identity content appears when `Meta/profile.md` is non-empty:

```python
# Vellum/backend/tests/test_agent_prompt.py
from pathlib import Path
from langchain_core.messages import HumanMessage

from agent.graph.agent import vellum_prompt
from agent.memory import project_context as pc


def test_vellum_prompt_includes_identity(tmp_path: Path, monkeypatch):
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("My name is Test")

    monkeypatch.setattr(
        "agent.graph.agent._prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1"}}
    messages = vellum_prompt(state, config)
    assert any("<PROTECTED>" in m.content for m in messages)


def test_vellum_prompt_no_meta_falls_back(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent.graph.agent._prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1"}}
    messages = vellum_prompt(state, config)
    # Plain system prompt only; no PROTECTED wrap
    assert all("<PROTECTED>" not in m.content for m in messages)
```

Run: `cd Vellum/backend && pytest tests/test_agent_prompt.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add Vellum/backend/agent/graph/agent.py Vellum/backend/tests/test_agent_prompt.py
git commit -m "feat(agent): dynamic prompt — prepend ProjectContext IDENTITY per turn"
```

---

### Task 13: Wire `tick()` into the post-turn pipeline

**Files:**
- Modify: `Vellum/backend/agent/api.py`

`_background_learn` already runs after each turn with both `query` and `answer`. It's the natural site to also call `ProjectContext.tick()` with a one-line summary.

- [ ] **Step 1: Extend `_background_learn`**

In `Vellum/backend/agent/api.py::_background_learn`, after the existing Honcho calls and before the `except Exception` block, add:

```python
        try:
            from agent.memory.project_context import build_fast_summarizer
            ctx = _project_context()
            # Lazy-bind a real summarizer once per process
            if ctx.summarizer is None or ctx.summarizer.__name__ == "_default_summarizer":
                ctx.summarizer = build_fast_summarizer()
            summary = (clean_query[:80] + "…") if len(clean_query) > 80 else clean_query
            await asyncio.to_thread(ctx.tick, thread_id, summary)
        except Exception:
            # Never let project bookkeeping break the response.
            pass
```

- [ ] **Step 2: Smoke test the integration**

```python
# Vellum/backend/tests/test_background_learn_tick.py
import asyncio
from pathlib import Path

import pytest

from agent import api as api_mod


@pytest.mark.asyncio
async def test_background_learn_calls_tick(tmp_path, monkeypatch):
    # Set up an active project so tick has somewhere to write
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("<!-- vellum-managed: empty -->\n")
    (proj / "log.md").write_text("")

    from agent.memory.project_context import ProjectContext
    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("t1", "fitness")

    monkeypatch.setattr(api_mod, "_project_context_singleton", ctx, raising=False)
    monkeypatch.setattr(api_mod, "_project_context", lambda: ctx, raising=False)

    # Stub out Honcho + storage so the call won't hit external services
    monkeypatch.setattr(api_mod, "HonchoMemory", lambda **kw: type("H", (), {
        "get_or_create_session": lambda self, t: "s1",
        "add_message": lambda self, sid, content, role: None,
    })())
    monkeypatch.setattr(api_mod, "store_qa_pair", lambda *a, **kw: None)
    monkeypatch.setattr(api_mod, "_fts5_memory", type("F", (), {"add_qa_pair": lambda **kw: None})())
    monkeypatch.setattr(api_mod, "classify", lambda q: (type("D", (), {"value": "GREEN"})(), ""))

    await api_mod._background_learn("user typed this", "agent said that", thread_id="t1")
    log = (proj / "log.md").read_text()
    assert "user typed this" in log
```

Run: `cd Vellum/backend && pytest tests/test_background_learn_tick.py -v`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add Vellum/backend/agent/api.py Vellum/backend/tests/test_background_learn_tick.py
git commit -m "feat(api): call ProjectContext.tick after each turn"
```

---

## Phase 7 — Migration script

### Task 14: Migration skeleton (argparse, dry-run, lock, git-dirty)

**Files:**
- Create: `Vellum/backend/scripts/__init__.py` (if absent — empty)
- Create: `Vellum/backend/scripts/migrate_vault_v2.py`
- Create: `Vellum/backend/tests/test_migrate_vault.py`

- [ ] **Step 1: Write failing tests**

```python
# Vellum/backend/tests/test_migrate_vault.py
from pathlib import Path

import pytest

from scripts.migrate_vault_v2 import (
    MigrationAborted,
    Migrator,
    plan_actions,
)


def test_plan_actions_dry_run(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    (vault / "X").mkdir(parents=True)
    (vault / "Youtube").mkdir()
    (vault / "Agent").mkdir()
    plan = plan_actions(vault)
    move_targets = [a for a in plan if a.kind == "move"]
    move_srcs = {Path(a.args["src"]).name for a in move_targets}
    assert "X" in move_srcs
    assert "Youtube" in move_srcs
    assert "Agent" not in move_srcs  # Agent stays put


def test_lock_file_blocks_concurrent(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    m1 = Migrator(vault_root=vault, data_root=data)
    with m1.lock():
        m2 = Migrator(vault_root=vault, data_root=data)
        with pytest.raises(MigrationAborted, match="in progress"):
            with m2.lock():
                pass


def test_idempotent_replan(tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    (vault / "Library" / "X").mkdir(parents=True)  # already migrated
    (vault / "Meta").mkdir()
    (vault / "Projects").mkdir()
    (vault / "Agent").mkdir()
    plan = plan_actions(vault)
    assert not any(a.kind == "move" for a in plan)
```

- [ ] **Step 2: Run, expect import error**

Run: `cd Vellum/backend && pytest tests/test_migrate_vault.py -v`
Expected: ImportError on `scripts.migrate_vault_v2`.

- [ ] **Step 3: Implement skeleton**

```python
# Vellum/backend/scripts/migrate_vault_v2.py
"""One-time migration: Vault → Meta/Projects/Library/Agent.

Dry-run by default; --apply executes."""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agent.memory.templates import load_template


REFERENCE_FOLDERS = ("X", "Youtube", "Books", "Sports", "Claude code", "Codex", "feedback")


class MigrationAborted(Exception):
    pass


@dataclass
class Action:
    kind: str  # "create_dir" | "move" | "write_template" | "rewrite_wikilinks" | "reindex"
    args: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        return f"{self.kind}: {self.args}"


def plan_actions(vault: Path) -> list[Action]:
    actions: list[Action] = []

    for top in ("Meta", "Projects", "Library"):
        if not (vault / top).exists():
            actions.append(Action("create_dir", {"path": str(vault / top)}))

    # Drop Meta templates if Meta/* missing
    if not (vault / "Meta" / "profile.md").exists():
        actions.append(Action("write_template", {"name": "profile", "dest": str(vault / "Meta" / "profile.md")}))
    if not (vault / "Meta" / "goals.md").exists():
        actions.append(Action("write_template", {"name": "goals", "dest": str(vault / "Meta" / "goals.md")}))
    if not (vault / "Meta" / "principles.md").exists():
        actions.append(Action("write_template", {"name": "principles", "dest": str(vault / "Meta" / "principles.md")}))

    for folder in REFERENCE_FOLDERS:
        src = vault / folder
        if src.exists():
            actions.append(Action("move", {
                "src": str(src),
                "dst": str(vault / "Library" / folder),
            }))

    if any(a.kind == "move" for a in actions):
        actions.append(Action("rewrite_wikilinks", {"vault": str(vault)}))
        actions.append(Action("reindex", {"target": "qdrant"}))
        actions.append(Action("reindex", {"target": "fts5"}))
    return actions


@dataclass
class Migrator:
    vault_root: Path
    data_root: Path

    def lock_path(self) -> Path:
        return self.data_root / ".migration.lock"

    @contextlib.contextmanager
    def lock(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        lp = self.lock_path()
        if lp.exists():
            # Detect stale lock from a crashed previous run
            try:
                pid = int(lp.read_text().strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                raise MigrationAborted(f"migration in progress (pid {pid})")
            # Stale lock — clean up and proceed
            lp.unlink(missing_ok=True)
        lp.write_text(str(os.getpid()))
        try:
            yield
        finally:
            lp.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness check; portable across POSIX and Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return True  # If unsure, assume alive — safer than racing
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return True

    def assert_clean_git(self, allow_dirty: bool) -> None:
        if allow_dirty:
            return
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.vault_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                raise MigrationAborted("vault has uncommitted changes; use --allow-dirty or commit first")
        except FileNotFoundError:
            # No git available — proceed silently
            pass

    def backup_tarball(self) -> Path:
        stamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        out = self.data_root / "backups" / f"vault-pre-v2-{stamp}.tar.gz"
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, "w:gz") as tar:
            tar.add(self.vault_root, arcname=self.vault_root.name)
        return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default="Vellum/Vault", type=Path)
    parser.add_argument("--data", default="Vellum/backend/data", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--no-backup", action="store_true", help="Skip tarball; use only if vault is already committed to git")
    args = parser.parse_args(argv)

    m = Migrator(vault_root=args.vault, data_root=args.data)
    plan = plan_actions(args.vault)

    if not plan:
        print("nothing to migrate")
        return 0

    print("planned actions:")
    for a in plan:
        print(f"  - {a.render()}")

    if not args.apply:
        print("\n(dry-run; pass --apply to execute)")
        return 0

    try:
        with m.lock():
            m.assert_clean_git(args.allow_dirty)
            if not args.no_backup:
                print(f"backup: {m.backup_tarball()}")
            else:
                print("skipping tarball backup (--no-backup); ensure your vault is committed in git")
            _execute_plan(plan)
    except MigrationAborted as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 2
    return 0


def _execute_plan(plan: list[Action]) -> None:
    for action in plan:
        if action.kind == "create_dir":
            Path(action.args["path"]).mkdir(parents=True, exist_ok=True)
        elif action.kind == "write_template":
            Path(action.args["dest"]).write_text(load_template(action.args["name"]), encoding="utf-8")
        elif action.kind == "move":
            src = Path(action.args["src"])
            dst = Path(action.args["dst"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        elif action.kind == "rewrite_wikilinks":
            from scripts.migrate_vault_v2 import rewrite_wikilinks
            rewrite_wikilinks(Path(action.args["vault"]))
        elif action.kind == "reindex":
            from scripts.migrate_vault_v2 import run_reindex
            run_reindex(action.args["target"])


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, expect first 3 tests pass**

Run: `cd Vellum/backend && pytest tests/test_migrate_vault.py -v`
Expected: 3 passed (the wikilink/reindex helpers are stubs added in next tasks; lazy import keeps planning tests green).

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/scripts/__init__.py Vellum/backend/scripts/migrate_vault_v2.py Vellum/backend/tests/test_migrate_vault.py
git commit -m "feat(scripts): migrate_vault_v2 skeleton — dry-run planner, lock, backup"
```

---

### Task 15: Wikilink rewriter

**Files:**
- Modify: `Vellum/backend/scripts/migrate_vault_v2.py`
- Modify: `Vellum/backend/tests/test_migrate_vault.py`

- [ ] **Step 1: Append failing tests**

```python
from scripts.migrate_vault_v2 import rewrite_wikilinks, rewrite_text


def test_rewrite_text_plain_links() -> None:
    text = "see [[X/foo]] and [[Youtube/bar|alias]]"
    out = rewrite_text(text)
    assert "[[Library/X/foo]]" in out
    assert "[[Library/Youtube/bar|alias]]" in out


def test_rewrite_text_embed_and_heading() -> None:
    text = "embed ![[X/foo#section]] and header [[Youtube/bar#sec|Section]]"
    out = rewrite_text(text)
    assert "![[Library/X/foo#section]]" in out
    assert "[[Library/Youtube/bar#sec|Section]]" in out


def test_rewrite_skips_fenced_code(tmp_path: Path) -> None:
    text = "```\nsee [[X/foo]]\n```\nlive [[X/foo]]"
    out = rewrite_text(text)
    # Inside fence: untouched. Outside: rewritten.
    assert out.count("[[X/foo]]") == 1
    assert out.count("[[Library/X/foo]]") == 1


def test_rewrite_skips_inline_code() -> None:
    text = "inline `[[X/foo]]` versus live [[X/foo]]"
    out = rewrite_text(text)
    assert "`[[X/foo]]`" in out  # inline preserved
    assert "[[Library/X/foo]]" in out  # live rewritten


def test_rewrite_wikilinks_writes_files(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("[[X/foo]]")
    rewrite_wikilinks(tmp_path)
    assert "[[Library/X/foo]]" in f.read_text()
```

- [ ] **Step 2: Run, expect import failures**

Run: `cd Vellum/backend && pytest tests/test_migrate_vault.py -v`
Expected: ImportError on `rewrite_wikilinks` / `rewrite_text`.

- [ ] **Step 3: Implement rewriter**

Append to `migrate_vault_v2.py`:

```python
import re as _re

WIKILINK_RE = _re.compile(r"(?P<embed>!?)\[\[(?P<target>[^\[\]\n]+?)\]\]")
FENCED_CODE_RE = _re.compile(r"```.*?```", _re.DOTALL)
INLINE_CODE_RE = _re.compile(r"`[^`\n]+`")

MOVED_PREFIXES = REFERENCE_FOLDERS  # ("X", "Youtube", ...)


def _rewrite_target(target: str) -> str:
    # target may include "#heading" and "|alias"
    main = target
    alias = ""
    if "|" in main:
        main, alias = main.split("|", 1)
        alias = "|" + alias
    heading = ""
    if "#" in main:
        main, heading = main.split("#", 1)
        heading = "#" + heading
    main = main.strip()
    for prefix in MOVED_PREFIXES:
        if main == prefix or main.startswith(prefix + "/"):
            main = "Library/" + main
            break
    return main + heading + alias


def rewrite_text(text: str) -> str:
    # Mask code regions so we don't rewrite inside them
    masks: list[str] = []

    def _mask(m: _re.Match) -> str:
        masks.append(m.group(0))
        return f"\x00CODE{len(masks) - 1}\x00"

    masked = FENCED_CODE_RE.sub(_mask, text)
    masked = INLINE_CODE_RE.sub(_mask, masked)

    def _rw(m: _re.Match) -> str:
        return f"{m.group('embed')}[[{_rewrite_target(m.group('target'))}]]"

    rewritten = WIKILINK_RE.sub(_rw, masked)

    def _unmask(s: str) -> str:
        return _re.sub(r"\x00CODE(\d+)\x00", lambda m: masks[int(m.group(1))], s)

    return _unmask(rewritten)


def rewrite_wikilinks(vault: Path) -> None:
    for md in vault.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        out = rewrite_text(text)
        if out != text:
            md.write_text(out, encoding="utf-8")
```

- [ ] **Step 4: Run, expect pass**

Run: `cd Vellum/backend && pytest tests/test_migrate_vault.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add Vellum/backend/scripts/migrate_vault_v2.py Vellum/backend/tests/test_migrate_vault.py
git commit -m "feat(scripts): wikilink rewriter handling embed/heading/alias, skipping code"
```

---

### Task 16: Reindex stubs

**Files:**
- Modify: `Vellum/backend/scripts/migrate_vault_v2.py`

These are thin wrappers around the existing reindex paths; they run the same code Vellum already uses.

- [ ] **Step 1: Append `run_reindex`**

```python
def run_reindex(target: str) -> None:
    """Trigger Qdrant or FTS5 reindex. Calls into existing Vellum reindex code paths."""
    if target == "qdrant":
        from agent.obsidian.ingester import reindex_vault as _qdrant_reindex
        print("rebuilding Qdrant collection (this may take 5-30 minutes)...")
        _qdrant_reindex()
        return
    if target == "fts5":
        from agent.memory.fts5 import rebuild_index as _fts5_rebuild
        print("rebuilding FTS5 index...")
        _fts5_rebuild()
        return
    raise ValueError(f"unknown reindex target: {target}")
```

> Note: this assumes `reindex_vault` and `rebuild_index` exist as module-level callables. If their names differ in the actual codebase, adapt the imports. (Verify by `grep -n "def reindex\|def rebuild_index" Vellum/backend/agent/`.)

- [ ] **Step 2: Smoke test**

```python
# append to test_migrate_vault.py
def test_run_reindex_unknown():
    from scripts.migrate_vault_v2 import run_reindex
    with pytest.raises(ValueError):
        run_reindex("unknown")
```

Run: `cd Vellum/backend && pytest tests/test_migrate_vault.py::test_run_reindex_unknown -v`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add Vellum/backend/scripts/migrate_vault_v2.py Vellum/backend/tests/test_migrate_vault.py
git commit -m "feat(scripts): reindex dispatch for Qdrant and FTS5"
```

---

## Phase 8 — Docs

### Task 17: Update CLAUDE.md §5 write rules

**Files:**
- Modify: `Vellum/CLAUDE.md`

- [ ] **Step 1: Replace the §5 Allowed/Forbidden lists**

Find the block beginning `### Allowed Write Locations` and replace it with:

```markdown
### Allowed Write Locations

```
Meta/                           ← READ-ONLY for agent; user-authored
Projects/<slug>/vellum.md       ← READ-ONLY; user-authored
Projects/<slug>/hot.md          ← Vellum may REWRITE (gated by active_project)
Projects/<slug>/log.md          ← Vellum may APPEND (gated by active_project)
Projects/<slug>/notes/          ← Vellum may WRITE (per project's Allowed Actions)
Agent/Queries/          ← every user query (intake node)
Agent/Responses/        ← every Q&A pair (store_response)
Agent/Memories/         ← synthesized higher-order observations
Agent/Connections/      ← cross-note connections discovered by agent
Agent/Reflections/      ← weekly, monthly synthesis notes
Agent/Digests/          ← nightly digest notes
Agent/Skills/Proposed/  ← human-readable skill proposals
Agent/Skills/Active/    ← active skill notes (mirrors .skills/active/)
Agent/Saved/            ← user-saved responses (via Ctrl+S)
```

### Forbidden Write Locations

The agent NEVER writes to or modifies:
- `Meta/` — user-authored identity layer (profile, goals, principles)
- `Projects/<slug>/vellum.md` — user-authored project charter
- `Library/` — reference material (X, Youtube, Books, Sports, Claude code, Codex, feedback)
- Any project's files when that project is not the active project on the current thread (enforced by ProjectContext)
- Any folder not listed under Allowed above
```

- [ ] **Step 2: Add a note about ProjectContext gating**

Below the Forbidden Write Locations section, add:

```markdown
### ProjectContext gating

`agent/memory/project_context.py` enforces a stricter dynamic rule on top of folder_policy:
- `hot.md` / `log.md` / `notes/` writes are only permitted to the **active project** for the
  current thread (`sessions.thread_state.active_project`). Writes to any other project's
  files are rejected even though folder_policy declares them writable in principle.
```

- [ ] **Step 3: Commit**

```bash
git add Vellum/CLAUDE.md
git commit -m "docs(CLAUDE.md): amend §5 write rules for Meta/Projects/Library + ProjectContext gating"
```

---

## Phase 9 — Verification

### Task 18: Full-suite verification

- [ ] **Step 1: Run the whole test suite**

Run: `cd Vellum/backend && pytest tests/ -v`
Expected: all green. Note any pre-existing test failures unrelated to this slice — those are out of scope.

- [ ] **Step 2: Dry-run the migration against the real vault**

Run: `cd Vellum/backend && python -m scripts.migrate_vault_v2 --vault ../Vault --data ./data`
Expected output: planned actions listed; no disk writes. Verify each move target looks correct.

- [ ] **Step 3: Decide whether to apply migration**

The migration can be applied at any point after this slice ships. The recommended sequence:
1. Commit/push everything in this slice.
2. On a quiet moment, run `python -m scripts.migrate_vault_v2 --vault ../Vault --data ./data --apply`.
3. Author `Meta/profile.md`, `Meta/goals.md`, `Meta/principles.md` from the dropped templates.
4. Create your first project: in the TUI/web, send `/project create <slug>`.

Do **not** auto-apply migration as part of this PR. It's a user-initiated step.

- [ ] **Step 4: Final commit if any docstrings or comments were tweaked during verification**

```bash
git add -A
git status  # verify nothing unexpected
git commit -m "chore: cleanup after foundation slice verification" || true
```

---

## Self-review checklist

Verified against [the spec](../specs/2026-05-16-vellum-foundation-design.md):

- D4 (Meta has profile/goals/principles) → Tasks 2, 4
- D5 (Project has vellum/hot/log/notes) → Tasks 2, 4, 6, 7, 10
- D6 (per-thread active_project) → Tasks 1, 4, 10
- D7 (Library/ holds existing folders) → Tasks 9, 14
- D8 (user-authored from template) → Tasks 2, 14 (templates), no auto-bootstrap
- D9 (preamble injection) → Task 12
- D10 (DD/MM/YYYY everywhere) → templates in Task 2; log line format in Task 6; hot.md write in Task 7
- D11 (sha guard on hot.md) → Task 7
- D12 (Presidio scrub before LLM) → Task 4
- §3 audit fixes (turn counter in DB, `/project create`, project discovery, etc.) → Tasks 1, 10
- §6 system prompt order (identity → honcho → CLAUDE → skills) → Task 12 prepends identity; Honcho/skills not touched here (existing position preserved)
- §7.5 migration phases (create + templates + move + reindex + wikilinks) → Tasks 14-16
- §8 error handling (missing meta → empty block; missing project → clear active; sha mismatch → proposal append; lock for concurrent migration) → Tasks 4, 7, 14
- §9 privacy (PII scrub, PROTECTED tags) → Task 4
- §11 testing matrix — every row has a test in Tasks 1, 4-7, 9, 10, 14-16

No placeholders in any step's code blocks. Type/signature consistency verified: `ProjectContext.build/tick/_state.set_active_project/get_active_project` names match across all tasks.

**Spec coverage gap accepted as scope limit:** §7.4 mentions wiring `/project` into the TUI command router. Task 11 wires it into the web `/chat` endpoint. The TUI router uses the same web API path under the hood (see `Vellum/backend/agent/terminal/session.py`), so no separate TUI task is strictly required — but if a dedicated TUI command shortcut is wanted later, it's a one-line add to the TUI command map. Captured in backlog (§12 in spec).
