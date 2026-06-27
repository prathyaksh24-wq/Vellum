# Coding Assistant SDK MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real Coding Assistant mode that runs Codex and Claude Code through Python SDK-backed Vellum coding sessions, with no fake coding data in the production path.

**Architecture:** Add a provider-neutral `agent.coding` backend package with SQLite session storage, SDK adapters, and `/api/coding/*` SSE routes. Then wire a Vellum workspace UI, visually based on `design/Velllum/uploads/vellum-workspace.html`, to the real coding API, terminal websocket, and workspace browser routes.

**Tech Stack:** FastAPI, pytest, SQLite, SSE, optional `openai-codex`, optional `claude-agent-sdk`, vanilla frontend modules under `frontend/ui`, Tauri window shell.

---

## File Structure

### Backend

- Create `backend/agent/coding/__init__.py`: public exports for the coding package.
- Create `backend/agent/coding/models.py`: dataclasses and enums for sessions, turns, events, provider health, and requests.
- Create `backend/agent/coding/events.py`: conversion helpers for provider-neutral SSE events.
- Create `backend/agent/coding/storage.py`: SQLite schema and CRUD for coding sessions, turns, and events.
- Create `backend/agent/coding/service.py`: orchestration layer between API routes, storage, and adapters.
- Create `backend/agent/coding/adapters/__init__.py`: adapter exports.
- Create `backend/agent/coding/adapters/base.py`: provider adapter protocol and errors.
- Create `backend/agent/coding/adapters/codex.py`: Codex SDK adapter and sandbox mapping.
- Create `backend/agent/coding/adapters/claude.py`: Claude Agent SDK adapter and session-id extraction.
- Modify `backend/agent/api.py`: mount `/api/coding/*` routes and one process-wide `CodingSessionService`.
- Modify `backend/pyproject.toml`: add SDK dependencies after adapter tests pass.
- Modify `backend/requirements.txt`: mirror the SDK dependency additions if this file is still used by runtime scripts.

### Backend Tests

- Create `backend/tests/test_coding_storage.py`.
- Create `backend/tests/test_coding_adapters.py`.
- Create `backend/tests/test_coding_service.py`.
- Create `backend/tests/test_coding_api.py`.
- Create `backend/tests/test_coding_project_tree.py`.

### Frontend/Desktop

- Create `frontend/ui/coding-api.js`: API client for provider health, sessions, session turns, events, and project tree.
- Create `frontend/ui/coding-api.test.js`: Vitest coverage for SSE parsing and API client behavior.
- Create `frontend/ui/vellum-workspace.html`: production workspace page copied from `design/Velllum/uploads/vellum-workspace.html`, with production coding data sourced from `/api/coding/*`.
- Modify `desktop/src-tauri/src/lib.rs`: point the Vellum desktop window at `/ui/vellum-workspace.html?desktop=1`.

---

## Task 1: Coding Models, Events, And SQLite Storage

**Files:**
- Create: `backend/agent/coding/__init__.py`
- Create: `backend/agent/coding/models.py`
- Create: `backend/agent/coding/events.py`
- Create: `backend/agent/coding/storage.py`
- Test: `backend/tests/test_coding_storage.py`

- [ ] **Step 1: Write the failing storage tests**

Create `backend/tests/test_coding_storage.py`:

```python
from pathlib import Path

from agent.coding.models import AccessMode, CodingSessionCreate, ProviderName
from agent.coding.storage import CodingSessionStore


def test_coding_store_creates_and_lists_sessions(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(
        CodingSessionCreate(
            provider=ProviderName.codex,
            cwd=str(tmp_path),
            access_mode=AccessMode.read_only,
            title="Inspect repo",
        )
    )

    assert session.id.startswith("code_")
    assert session.provider == ProviderName.codex
    assert session.cwd == str(tmp_path.resolve())
    assert session.access_mode == AccessMode.read_only
    assert session.status == "idle"

    listed = store.list_sessions()
    assert [item.id for item in listed] == [session.id]


def test_coding_store_updates_provider_session_and_records_turn_events(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(
        CodingSessionCreate(
            provider=ProviderName.claude,
            cwd=str(tmp_path),
            access_mode=AccessMode.workspace_write,
            title="Fix tests",
        )
    )
    updated = store.set_provider_session_id(session.id, "claude-session-1")
    turn = store.create_turn(session.id, "Run tests")
    event = store.record_event(
        session_id=session.id,
        turn_id=turn.id,
        provider=ProviderName.claude,
        event_type="assistant.final",
        message="Done",
        payload={"text": "All tests pass"},
    )
    completed = store.complete_turn(turn.id, final_response="All tests pass")

    assert updated.provider_session_id == "claude-session-1"
    assert turn.id.startswith("turn_")
    assert event.type == "assistant.final"
    assert event.payload == {"text": "All tests pass"}
    assert completed.status == "completed"
    assert store.list_events(session.id)[0].id == event.id
```

- [ ] **Step 2: Run the failing storage tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_storage.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'agent.coding'`.

- [ ] **Step 3: Create the coding package models**

Create `backend/agent/coding/__init__.py`:

```python
"""SDK-backed coding assistant sessions."""
```

Create `backend/agent/coding/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProviderName(StrEnum):
    codex = "codex"
    claude = "claude"


class AccessMode(StrEnum):
    read_only = "read_only"
    workspace_write = "workspace_write"
    full_access = "full_access"
    ask_every_time = "ask_every_time"


@dataclass(frozen=True)
class ProviderHealth:
    provider: ProviderName
    available: bool
    configured: bool
    message: str


@dataclass(frozen=True)
class CodingSessionCreate:
    provider: ProviderName
    cwd: str
    access_mode: AccessMode = AccessMode.read_only
    title: str = ""

    def resolved_cwd(self) -> str:
        return str(Path(self.cwd).expanduser().resolve())


@dataclass(frozen=True)
class CodingSession:
    id: str
    provider: ProviderName
    cwd: str
    access_mode: AccessMode
    title: str
    status: str = "idle"
    provider_session_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class CodingTurn:
    id: str
    session_id: str
    prompt: str
    status: str
    started_at: str
    completed_at: str | None = None
    final_response: str = ""
    error: str = ""


@dataclass(frozen=True)
class CodingEvent:
    id: str
    session_id: str
    turn_id: str | None
    provider: ProviderName
    type: str
    message: str
    payload: dict[str, Any]
    created_at: str
```

- [ ] **Step 4: Create SSE event helpers**

Create `backend/agent/coding/events.py`:

```python
from __future__ import annotations

import json
from typing import Any

from agent.coding.models import CodingEvent


EVENT_NAME_BY_TYPE = {
    "session.started": "session",
    "session.resumed": "session",
    "turn.started": "turn",
    "assistant.delta": "assistant_delta",
    "assistant.final": "assistant_final",
    "tool.started": "tool",
    "tool.completed": "tool",
    "file.changed": "file_change",
    "turn.completed": "done",
    "turn.error": "error",
}


def event_name(event_type: str) -> str:
    return EVENT_NAME_BY_TYPE.get(event_type, "coding")


def event_payload(event: CodingEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "session_id": event.session_id,
        "turn_id": event.turn_id,
        "provider": event.provider.value,
        "type": event.type,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def sse(event: CodingEvent) -> str:
    return f"event: {event_name(event.type)}\ndata: {json.dumps(event_payload(event))}\n\n"
```

- [ ] **Step 5: Create SQLite storage**

Create `backend/agent/coding/storage.py`:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from agent.coding.models import (
    AccessMode,
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    CodingTurn,
    ProviderName,
    utc_now,
)


class CodingSessionStore:
    def __init__(self, db_path: Path = Path("data/memory/coding_sessions.db")) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS coding_sessions (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    provider_session_id TEXT,
                    cwd TEXT NOT NULL,
                    access_mode TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coding_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    final_response TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(session_id) REFERENCES coding_sessions(id)
                );
                CREATE TABLE IF NOT EXISTS coding_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    provider TEXT NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES coding_sessions(id),
                    FOREIGN KEY(turn_id) REFERENCES coding_turns(id)
                );
                """
            )

    def create_session(self, body: CodingSessionCreate) -> CodingSession:
        cwd = body.resolved_cwd()
        title = body.title.strip() or Path(cwd).name or "Coding session"
        now = utc_now()
        session = CodingSession(
            id=f"code_{uuid4().hex}",
            provider=body.provider,
            cwd=cwd,
            access_mode=body.access_mode,
            title=title,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_sessions
                (id, provider, provider_session_id, cwd, access_mode, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.provider.value,
                    session.provider_session_id,
                    session.cwd,
                    session.access_mode.value,
                    session.title,
                    session.status,
                    session.created_at,
                    session.updated_at,
                ),
            )
        return session

    def get_session(self, session_id: str) -> CodingSession | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM coding_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(self) -> list[CodingSession]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM coding_sessions ORDER BY updated_at DESC").fetchall()
        return [self._session_from_row(row) for row in rows]

    def set_provider_session_id(self, session_id: str, provider_session_id: str) -> CodingSession:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE coding_sessions SET provider_session_id = ?, updated_at = ? WHERE id = ?",
                (provider_session_id, now, session_id),
            )
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def set_session_status(self, session_id: str, status: str) -> CodingSession:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE coding_sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, session_id),
            )
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def create_turn(self, session_id: str, prompt: str) -> CodingTurn:
        now = utc_now()
        turn = CodingTurn(
            id=f"turn_{uuid4().hex}",
            session_id=session_id,
            prompt=prompt,
            status="running",
            started_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_turns
                (id, session_id, prompt, status, started_at, final_response, error)
                VALUES (?, ?, ?, ?, ?, '', '')
                """,
                (turn.id, turn.session_id, turn.prompt, turn.status, turn.started_at),
            )
        return turn

    def complete_turn(self, turn_id: str, final_response: str = "", error: str = "") -> CodingTurn:
        status = "error" if error else "completed"
        completed_at = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE coding_turns
                SET status = ?, completed_at = ?, final_response = ?, error = ?
                WHERE id = ?
                """,
                (status, completed_at, final_response, error, turn_id),
            )
            row = conn.execute("SELECT * FROM coding_turns WHERE id = ?", (turn_id,)).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return self._turn_from_row(row)

    def record_event(
        self,
        *,
        session_id: str,
        provider: ProviderName,
        event_type: str,
        message: str,
        payload: dict,
        turn_id: str | None = None,
    ) -> CodingEvent:
        event = CodingEvent(
            id=f"evt_{uuid4().hex}",
            session_id=session_id,
            turn_id=turn_id,
            provider=provider,
            type=event_type,
            message=message,
            payload=payload,
            created_at=utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO coding_events
                (id, session_id, turn_id, provider, type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.session_id,
                    event.turn_id,
                    event.provider.value,
                    event.type,
                    event.message,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )
        return event

    def list_events(self, session_id: str) -> list[CodingEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM coding_events WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _session_from_row(self, row: sqlite3.Row) -> CodingSession:
        return CodingSession(
            id=row["id"],
            provider=ProviderName(row["provider"]),
            provider_session_id=row["provider_session_id"],
            cwd=row["cwd"],
            access_mode=AccessMode(row["access_mode"]),
            title=row["title"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _turn_from_row(self, row: sqlite3.Row) -> CodingTurn:
        return CodingTurn(
            id=row["id"],
            session_id=row["session_id"],
            prompt=row["prompt"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            final_response=row["final_response"],
            error=row["error"],
        )

    def _event_from_row(self, row: sqlite3.Row) -> CodingEvent:
        return CodingEvent(
            id=row["id"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            provider=ProviderName(row["provider"]),
            type=row["type"],
            message=row["message"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )
```

- [ ] **Step 6: Run storage tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_storage.py -q
```

Expected: `2 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend/agent/coding backend/tests/test_coding_storage.py
git commit -m "feat(coding): add session storage primitives"
```

---

## Task 2: Provider Adapter Contract And Health Checks

**Files:**
- Create: `backend/agent/coding/adapters/__init__.py`
- Create: `backend/agent/coding/adapters/base.py`
- Create: `backend/agent/coding/adapters/codex.py`
- Create: `backend/agent/coding/adapters/claude.py`
- Test: `backend/tests/test_coding_adapters.py`

- [ ] **Step 1: Write failing adapter tests**

Create `backend/tests/test_coding_adapters.py`:

```python
import importlib.util

from agent.coding.adapters.claude import ClaudeAdapter, extract_claude_session_id
from agent.coding.adapters.codex import CodexAdapter, codex_sandbox_name
from agent.coding.models import AccessMode, ProviderName


def test_codex_health_reports_missing_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    health = CodexAdapter().health()

    assert health.provider == ProviderName.codex
    assert health.available is False
    assert health.configured is False
    assert health.message == "Codex SDK is not installed."


def test_claude_health_reports_available_dependency(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    health = ClaudeAdapter().health()

    assert health.provider == ProviderName.claude
    assert health.available is True
    assert health.configured is True


def test_codex_access_mode_mapping_is_explicit():
    assert codex_sandbox_name(AccessMode.read_only) == "read_only"
    assert codex_sandbox_name(AccessMode.workspace_write) == "workspace_write"
    assert codex_sandbox_name(AccessMode.full_access) == "full_access"
    assert codex_sandbox_name(AccessMode.ask_every_time) == "read_only"


def test_claude_session_id_extraction_from_init_message():
    class InitMessage:
        subtype = "init"
        data = {"session_id": "claude-session-1"}

    assert extract_claude_session_id(InitMessage()) == "claude-session-1"
```

- [ ] **Step 2: Run failing adapter tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_adapters.py -q
```

Expected: fail because adapter modules do not exist.

- [ ] **Step 3: Create adapter base**

Create `backend/agent/coding/adapters/__init__.py`:

```python
"""Provider adapters for SDK-backed coding sessions."""
```

Create `backend/agent/coding/adapters/base.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from agent.coding.models import CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName


class CodingAdapterError(RuntimeError):
    pass


class CodingProviderAdapter(Protocol):
    provider: ProviderName

    def health(self) -> ProviderHealth:
        ...

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        ...

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        ...

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        ...
```

- [ ] **Step 4: Create Codex health and sandbox mapping**

Create `backend/agent/coding/adapters/codex.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
import importlib
import importlib.util

from agent.coding.adapters.base import CodingAdapterError
from agent.coding.models import AccessMode, CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName, utc_now


def codex_sandbox_name(access_mode: AccessMode) -> str:
    return {
        AccessMode.read_only: "read_only",
        AccessMode.workspace_write: "workspace_write",
        AccessMode.full_access: "full_access",
        AccessMode.ask_every_time: "read_only",
    }[access_mode]


class CodexAdapter:
    provider = ProviderName.codex

    def health(self) -> ProviderHealth:
        available = importlib.util.find_spec("openai_codex") is not None
        return ProviderHealth(
            provider=self.provider,
            available=available,
            configured=available,
            message="Codex SDK ready." if available else "Codex SDK is not installed.",
        )

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        return None

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        if importlib.util.find_spec("openai_codex") is None:
            raise CodingAdapterError("Codex SDK is not installed.")
        module = importlib.import_module("openai_codex")
        AsyncCodex = getattr(module, "AsyncCodex")
        Sandbox = getattr(module, "Sandbox")
        sandbox = getattr(Sandbox, codex_sandbox_name(session.access_mode))
        async with AsyncCodex() as codex:
            thread = await codex.thread_start(sandbox=sandbox) if not session.provider_session_id else codex.thread_resume(session.provider_session_id)
            result = await thread.run(prompt)
        text = str(getattr(result, "final_response", result) or "")
        yield CodingEvent(
            id="",
            session_id=session.id,
            turn_id=turn_id,
            provider=self.provider,
            type="assistant.final",
            message="Codex final response",
            payload={"text": text},
            created_at=utc_now(),
        )

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        return None
```

- [ ] **Step 5: Create Claude health and session extraction**

Create `backend/agent/coding/adapters/claude.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
import importlib
import importlib.util

from agent.coding.adapters.base import CodingAdapterError
from agent.coding.models import CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName, utc_now


def extract_claude_session_id(message: object) -> str | None:
    subtype = getattr(message, "subtype", None)
    data = getattr(message, "data", None)
    if subtype == "init" and isinstance(data, dict):
        value = data.get("session_id")
        return str(value) if value else None
    return None


def message_result_text(message: object) -> str:
    result = getattr(message, "result", None)
    if result:
        return str(result)
    content = getattr(message, "content", None)
    if content:
        return str(content)
    return ""


class ClaudeAdapter:
    provider = ProviderName.claude

    def health(self) -> ProviderHealth:
        available = importlib.util.find_spec("claude_agent_sdk") is not None
        return ProviderHealth(
            provider=self.provider,
            available=available,
            configured=available,
            message="Claude Agent SDK ready." if available else "Claude Agent SDK is not installed.",
        )

    async def start_session(self, request: CodingSessionCreate) -> str | None:
        return None

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        if importlib.util.find_spec("claude_agent_sdk") is None:
            raise CodingAdapterError("Claude Agent SDK is not installed.")
        module = importlib.import_module("claude_agent_sdk")
        query = getattr(module, "query")
        ClaudeAgentOptions = getattr(module, "ClaudeAgentOptions")
        options = ClaudeAgentOptions(resume=session.provider_session_id) if session.provider_session_id else ClaudeAgentOptions()
        final_text = ""
        async for message in query(prompt=prompt, options=options):
            session_id = extract_claude_session_id(message)
            if session_id:
                yield CodingEvent(
                    id="",
                    session_id=session.id,
                    turn_id=turn_id,
                    provider=self.provider,
                    type="session.resumed",
                    message="Claude session initialized",
                    payload={"provider_session_id": session_id},
                    created_at=utc_now(),
                )
            text = message_result_text(message)
            if text:
                final_text = text
                yield CodingEvent(
                    id="",
                    session_id=session.id,
                    turn_id=turn_id,
                    provider=self.provider,
                    type="assistant.final",
                    message="Claude final response",
                    payload={"text": text},
                    created_at=utc_now(),
                )
        if not final_text:
            raise CodingAdapterError("Claude returned no response.")

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        return None
```

- [ ] **Step 6: Run adapter tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_adapters.py -q
```

Expected: `4 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend/agent/coding/adapters backend/tests/test_coding_adapters.py
git commit -m "feat(coding): add provider adapter contract"
```

---

## Task 3: Coding Session Service

**Files:**
- Create: `backend/agent/coding/service.py`
- Test: `backend/tests/test_coding_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_coding_service.py`:

```python
from collections.abc import AsyncIterator
import asyncio
from pathlib import Path

from agent.coding.models import AccessMode, CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName, utc_now
from agent.coding.service import CodingSessionService
from agent.coding.storage import CodingSessionStore


class FakeAdapter:
    provider = ProviderName.codex

    def health(self):
        return ProviderHealth(self.provider, True, True, "ready")

    async def start_session(self, request: CodingSessionCreate):
        return "provider-thread-1"

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        yield CodingEvent("", session.id, turn_id, self.provider, "assistant.final", "done", {"text": f"answer: {prompt}"}, utc_now())

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        return None


def test_service_creates_session_and_records_provider_id(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )

    session = asyncio.run(service.create_session(CodingSessionCreate(
        provider=ProviderName.codex,
        cwd=str(tmp_path),
        access_mode=AccessMode.read_only,
    )))

    assert session.provider_session_id == "provider-thread-1"
    assert session.cwd == str(tmp_path.resolve())


def test_service_streams_turn_and_persists_events(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [event async for event in service.run_turn(session.id, "hello")]

    events = asyncio.run(collect())

    assert [event.type for event in events] == ["turn.started", "assistant.final", "turn.completed"]
    assert store.list_events(session.id)[1].payload == {"text": "answer: hello"}
```

- [ ] **Step 2: Run failing service tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_service.py -q
```

Expected: fail because `agent.coding.service` does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/agent/coding/service.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from agent.coding.adapters.base import CodingAdapterError, CodingProviderAdapter
from agent.coding.adapters.claude import ClaudeAdapter
from agent.coding.adapters.codex import CodexAdapter
from agent.coding.models import CodingEvent, CodingSession, CodingSessionCreate, ProviderHealth, ProviderName
from agent.coding.storage import CodingSessionStore


class CodingServiceError(RuntimeError):
    pass


class CodingSessionService:
    def __init__(
        self,
        store: CodingSessionStore | None = None,
        adapters: dict[ProviderName, CodingProviderAdapter] | None = None,
    ) -> None:
        self.store = store or CodingSessionStore()
        self.adapters = adapters or {
            ProviderName.codex: CodexAdapter(),
            ProviderName.claude: ClaudeAdapter(),
        }

    def health(self) -> list[ProviderHealth]:
        return [adapter.health() for adapter in self.adapters.values()]

    def list_sessions(self) -> list[CodingSession]:
        return self.store.list_sessions()

    def get_session(self, session_id: str) -> CodingSession:
        session = self.store.get_session(session_id)
        if session is None:
            raise CodingServiceError("Coding session not found.")
        return session

    async def create_session(self, request: CodingSessionCreate) -> CodingSession:
        cwd = Path(request.cwd).expanduser().resolve()
        if not cwd.exists() or not cwd.is_dir():
            raise CodingServiceError("Project not found.")
        session = self.store.create_session(request)
        adapter = self._adapter(session.provider)
        provider_session_id = await adapter.start_session(request)
        if provider_session_id:
            session = self.store.set_provider_session_id(session.id, provider_session_id)
        event = self.store.record_event(
            session_id=session.id,
            provider=session.provider,
            event_type="session.started",
            message="Coding session started",
            payload={"cwd": session.cwd, "provider_session_id": session.provider_session_id},
        )
        void = event
        return session

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[CodingEvent]:
        session = self.get_session(session_id)
        adapter = self._adapter(session.provider)
        turn = self.store.create_turn(session.id, prompt)
        self.store.set_session_status(session.id, "running")
        yield self.store.record_event(
            session_id=session.id,
            turn_id=turn.id,
            provider=session.provider,
            event_type="turn.started",
            message="Coding turn started",
            payload={"prompt": prompt},
        )
        final_text = ""
        try:
            async for raw_event in adapter.run_turn(session, prompt, turn.id):
                event = self.store.record_event(
                    session_id=session.id,
                    turn_id=turn.id,
                    provider=session.provider,
                    event_type=raw_event.type,
                    message=raw_event.message,
                    payload=raw_event.payload,
                )
                if event.type == "session.resumed" and event.payload.get("provider_session_id"):
                    self.store.set_provider_session_id(session.id, str(event.payload["provider_session_id"]))
                if event.type == "assistant.final":
                    final_text = str(event.payload.get("text") or "")
                yield event
            self.store.complete_turn(turn.id, final_response=final_text)
            self.store.set_session_status(session.id, "idle")
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.completed",
                message="Coding turn completed",
                payload={"final_response": final_text},
            )
        except (CodingAdapterError, Exception) as exc:
            message = str(exc) or exc.__class__.__name__
            self.store.complete_turn(turn.id, error=message)
            self.store.set_session_status(session.id, "error")
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.error",
                message=message,
                payload={"error": message},
            )

    async def stop_turn(self, session_id: str, turn_id: str | None = None) -> None:
        session = self.get_session(session_id)
        await self._adapter(session.provider).stop_turn(session, turn_id or "")
        self.store.set_session_status(session.id, "stopped")

    def list_events(self, session_id: str) -> list[CodingEvent]:
        self.get_session(session_id)
        return self.store.list_events(session_id)

    def _adapter(self, provider: ProviderName) -> CodingProviderAdapter:
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise CodingServiceError("Provider is not configured.")
        return adapter
```

- [ ] **Step 4: Run service tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_service.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/coding/service.py backend/tests/test_coding_service.py
git commit -m "feat(coding): add session service"
```

---

## Task 4: Coding API Routes And Project Tree

**Files:**
- Modify: `backend/agent/api.py`
- Test: `backend/tests/test_coding_api.py`
- Test: `backend/tests/test_coding_project_tree.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_coding_api.py`:

```python
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from agent import api
from agent.coding.models import CodingEvent, ProviderHealth, ProviderName, utc_now


class FakeCodingService:
    def health(self):
        return [
            ProviderHealth(ProviderName.codex, True, True, "Codex ready."),
            ProviderHealth(ProviderName.claude, False, False, "Claude Agent SDK is not installed."),
        ]

    async def create_session(self, request):
        return type("Session", (), {
            "id": "code_1",
            "provider": ProviderName.codex,
            "provider_session_id": "thread_1",
            "cwd": request.resolved_cwd(),
            "access_mode": request.access_mode,
            "title": request.title or "repo",
            "status": "idle",
            "created_at": "2026-06-05T00:00:00+00:00",
            "updated_at": "2026-06-05T00:00:00+00:00",
        })()

    def list_sessions(self):
        return []

    def get_session(self, session_id):
        raise AssertionError("not used")

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[CodingEvent]:
        yield CodingEvent("evt_1", session_id, "turn_1", ProviderName.codex, "assistant.final", "done", {"text": prompt}, utc_now())

    def list_events(self, session_id):
        return []


def test_coding_health_endpoint(monkeypatch):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        response = client.get("/api/coding/health")

    assert response.status_code == 200
    assert response.json()["providers"][0]["provider"] == "codex"
    assert response.json()["providers"][1]["available"] is False


def test_coding_session_create_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        response = client.post(
            "/api/coding/sessions",
            json={"provider": "codex", "cwd": str(tmp_path), "access_mode": "read_only", "title": "repo"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == "code_1"
    assert response.json()["provider_session_id"] == "thread_1"


def test_coding_turn_stream_endpoint(monkeypatch):
    monkeypatch.setattr(api, "coding_service", FakeCodingService())

    with TestClient(api.app) as client:
        with client.stream("POST", "/api/coding/sessions/code_1/turns/stream", json={"prompt": "hello"}) as response:
            body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: assistant_final" in body
    assert '"text": "hello"' in body
```

Create `backend/tests/test_coding_project_tree.py`:

```python
from fastapi.testclient import TestClient

from agent import api


def test_coding_project_tree_lists_real_files(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "README.md").write_text("# repo", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(tmp_path)})

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert "backend" in names
    assert "README.md" in names
    assert ".env" not in names


def test_coding_project_tree_rejects_missing_root(tmp_path):
    with TestClient(api.app) as client:
        response = client.get("/api/coding/projects/tree", params={"root": str(tmp_path / "missing")})

    assert response.status_code == 404
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_api.py tests/test_coding_project_tree.py -q
```

Expected: fail because routes do not exist.

- [ ] **Step 3: Add coding route imports and singleton**

Modify `backend/agent/api.py` near existing imports:

```python
from agent.coding.events import event_payload, sse as coding_sse
from agent.coding.models import AccessMode, CodingSession, CodingSessionCreate, ProviderName
from agent.coding.service import CodingServiceError, CodingSessionService
```

Add near other singletons:

```python
coding_service = CodingSessionService()
```

- [ ] **Step 4: Add route models and serializers**

Add before `app.include_router(router)` in `backend/agent/api.py`:

```python
class CodingSessionBody(BaseModel):
    provider: ProviderName
    cwd: str = Field(min_length=1)
    access_mode: AccessMode = AccessMode.read_only
    title: str = ""


class CodingTurnBody(BaseModel):
    prompt: str = Field(min_length=1)


def _coding_session_json(session: CodingSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "provider": session.provider.value,
        "provider_session_id": session.provider_session_id,
        "cwd": session.cwd,
        "access_mode": session.access_mode.value,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _hidden_coding_file(name: str) -> bool:
    lowered = name.casefold()
    return lowered in {".env", ".env.local", ".env.production"} or lowered.endswith(".pem") or lowered.endswith(".key")


def _project_tree(root: str) -> dict[str, Any]:
    base = Path(root).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    items: list[dict[str, Any]] = []
    for path in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
        if _hidden_coding_file(path.name):
            continue
        items.append({
            "name": path.name,
            "path": str(path),
            "kind": "directory" if path.is_dir() else "file",
        })
        if len(items) >= 250:
            break
    return {"root": str(base), "items": items}
```

- [ ] **Step 5: Add `/api/coding/*` routes**

Add below the existing settings routes in `backend/agent/api.py`:

```python
@router.get("/coding/health")
async def coding_health() -> dict[str, Any]:
    return {"providers": [health.__dict__ | {"provider": health.provider.value} for health in coding_service.health()]}


@router.get("/coding/sessions")
async def coding_sessions() -> dict[str, Any]:
    return {"sessions": [_coding_session_json(session) for session in coding_service.list_sessions()]}


@router.post("/coding/sessions")
async def coding_session_create(body: CodingSessionBody) -> dict[str, Any]:
    try:
        session = await coding_service.create_session(CodingSessionCreate(
            provider=body.provider,
            cwd=body.cwd,
            access_mode=body.access_mode,
            title=body.title,
        ))
    except CodingServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _coding_session_json(session)


@router.get("/coding/sessions/{session_id}")
async def coding_session_get(session_id: str) -> dict[str, Any]:
    try:
        return _coding_session_json(coding_service.get_session(session_id))
    except CodingServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/coding/sessions/{session_id}/turns/stream")
async def coding_turn_stream(session_id: str, body: CodingTurnBody) -> StreamingResponse:
    async def events():
        async for event in coding_service.run_turn(session_id, body.prompt):
            yield coding_sse(event)
    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/coding/sessions/{session_id}/stop")
async def coding_session_stop(session_id: str) -> dict[str, Any]:
    await coding_service.stop_turn(session_id)
    return {"ok": True}


@router.get("/coding/sessions/{session_id}/events")
async def coding_session_events(session_id: str) -> dict[str, Any]:
    return {"events": [event_payload(event) for event in coding_service.list_events(session_id)]}


@router.get("/coding/projects/tree")
async def coding_project_tree(root: str) -> dict[str, Any]:
    return _project_tree(root)


@router.get("/coding/projects/recent")
async def coding_recent_projects() -> dict[str, Any]:
    return {"projects": []}
```

- [ ] **Step 6: Run API tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_api.py tests/test_coding_project_tree.py -q
```

Expected: `5 passed`.

- [ ] **Step 7: Run focused existing API regression tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_api.py tests/test_terminal_api.py -q
```

Expected: all selected tests pass. If `test_health_endpoint_reports_service_and_qdrant` fails because the current API now reports `vector` instead of `qdrant`, update only that stale test in a separate commit after verifying current `/api/health` shape.

- [ ] **Step 8: Commit**

```bash
git add backend/agent/api.py backend/tests/test_coding_api.py backend/tests/test_coding_project_tree.py
git commit -m "feat(coding): expose coding session api"
```

---

## Task 5: SDK Dependency Declarations And Real Adapter Probes

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`
- Modify: `backend/tests/test_coding_adapters.py`

- [ ] **Step 1: Add tests for dependency names**

Append to `backend/tests/test_coding_adapters.py`:

```python
def test_adapter_dependency_module_names_are_stable():
    assert CodexAdapter().sdk_module_name == "openai_codex"
    assert ClaudeAdapter().sdk_module_name == "claude_agent_sdk"
```

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_adapters.py::test_adapter_dependency_module_names_are_stable -q
```

Expected: fail because `sdk_module_name` is not defined.

- [ ] **Step 2: Add adapter module-name attributes**

Modify `backend/agent/coding/adapters/codex.py` inside `CodexAdapter`:

```python
class CodexAdapter:
    provider = ProviderName.codex
    sdk_module_name = "openai_codex"
```

Replace direct `"openai_codex"` checks in that file with `self.sdk_module_name`.

Modify `backend/agent/coding/adapters/claude.py` inside `ClaudeAdapter`:

```python
class ClaudeAdapter:
    provider = ProviderName.claude
    sdk_module_name = "claude_agent_sdk"
```

Replace direct `"claude_agent_sdk"` checks in that file with `self.sdk_module_name`.

- [ ] **Step 3: Add dependencies**

Modify `backend/pyproject.toml` dependencies list by adding:

```toml
  "openai-codex>=0.1.0",
  "claude-agent-sdk>=0.1.0",
```

Modify `backend/requirements.txt` by adding:

```text
openai-codex>=0.1.0
claude-agent-sdk>=0.1.0
```

If package resolution shows a different minimum version during install, keep the resolved package names and write the observed versions into the commit body.

- [ ] **Step 4: Run adapter tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_adapters.py -q
```

Expected: all adapter tests pass whether the optional SDKs are installed or not.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/requirements.txt backend/agent/coding/adapters backend/tests/test_coding_adapters.py
git commit -m "feat(coding): declare sdk dependencies"
```

---

## Task 6: Frontend Coding API Client

**Files:**
- Create: `frontend/ui/coding-api.js`
- Create: `frontend/ui/coding-api.test.js`

- [ ] **Step 1: Write failing frontend API tests**

Create `frontend/ui/coding-api.test.js`:

```javascript
import { describe, expect, test, vi } from "vitest";
import { createCodingApi, parseSseBlocks } from "./coding-api.js";

describe("parseSseBlocks", () => {
  test("parses named SSE events", () => {
    const blocks = parseSseBlocks('event: assistant_final\ndata: {"payload":{"text":"ok"}}\n\n');
    expect(blocks).toEqual([{ event: "assistant_final", data: { payload: { text: "ok" } } }]);
  });
});

describe("createCodingApi", () => {
  test("loads provider health", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ providers: [{ provider: "codex", available: true }] }),
    }));
    const api = createCodingApi({ apiBase: "http://127.0.0.1:8000", fetchImpl });

    const health = await api.health();

    expect(health.providers[0].provider).toBe("codex");
    expect(fetchImpl).toHaveBeenCalledWith("http://127.0.0.1:8000/api/coding/health");
  });
});
```

- [ ] **Step 2: Run failing frontend API tests**

Run:

```bash
cd D:\Vellum\frontend
npm test -- ui/coding-api.test.js
```

Expected: fail because `coding-api.js` does not exist.

- [ ] **Step 3: Implement coding API client**

Create `frontend/ui/coding-api.js`:

```javascript
export function parseSseBlocks(text) {
  return text
    .split("\n\n")
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      return { event, data: data ? JSON.parse(data) : null };
    });
}

export function createCodingApi({ apiBase = "http://127.0.0.1:8000", fetchImpl = fetch } = {}) {
  const base = apiBase.replace(/\/$/, "");

  async function json(path, init) {
    const response = await fetchImpl(`${base}${path}`, init);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }

  return {
    health() {
      return json("/api/coding/health");
    },
    listSessions() {
      return json("/api/coding/sessions");
    },
    createSession(body) {
      return json("/api/coding/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    },
    projectTree(root) {
      return json(`/api/coding/projects/tree?root=${encodeURIComponent(root)}`);
    },
    async runTurn(sessionId, prompt, onEvent) {
      const response = await fetchImpl(`${base}/api/coding/sessions/${sessionId}/turns/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (!response.body) {
        const text = await response.text();
        parseSseBlocks(text).forEach(onEvent);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        parts.forEach((part) => {
          parseSseBlocks(`${part}\n\n`).forEach(onEvent);
        });
      }
      if (buffer.trim()) parseSseBlocks(`${buffer}\n\n`).forEach(onEvent);
    },
  };
}
```

- [ ] **Step 4: Run frontend API tests**

Run:

```bash
cd D:\Vellum\frontend
npm test -- ui/coding-api.test.js
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/ui/coding-api.js frontend/ui/coding-api.test.js
git commit -m "feat(ui): add coding api client"
```

---

## Task 7: Production Workspace Page With No Coding Demo Data

**Files:**
- Create: `frontend/ui/vellum-workspace.html`
- Modify: `frontend/package.json` only if test script needs a path fix

- [ ] **Step 1: Copy the visual source into the frontend**

Run:

```bash
Copy-Item 'D:\Vellum\design\Velllum\uploads\vellum-workspace.html' 'D:\Vellum\frontend\ui\vellum-workspace.html'
```

Expected: `frontend/ui/vellum-workspace.html` exists and visually matches the approved desktop workspace reference before production wiring.

- [ ] **Step 2: Remove browser-side provider orchestration**

In `frontend/ui/vellum-workspace.html`, remove or disable these prototype sections from the production coding path:

```javascript
const SUBAGENTS = [
```

```javascript
const MAIN_MSGS = [
```

```javascript
const RAMAN_MSGS = [
```

```javascript
async function planTask(userText, history, signal){
```

```javascript
async function runCodingTurn(chatId, aid, userText, history){
```

Replace initial coding message state with:

```javascript
const initialChatMsgs = {};
```

Replace any use of `MAIN_MSGS` as seed data with:

```javascript
const [chatMsgs, setChatMsgs] = useState(initialChatMsgs);
```

Replace fake `SUBAGENTS` display with a real empty state:

```jsx
<div className="workspace-empty">
  Coding activity appears here when Codex or Claude emits real session events.
</div>
```

- [ ] **Step 3: Wire coding API client into the page**

Add before the Babel app script or import as a classic script if the page remains non-module:

```html
<script type="module">
  import { createCodingApi } from "./coding-api.js";
  window.__vellumCodingApi = createCodingApi({ apiBase: "http://127.0.0.1:8000" });
</script>
```

Inside the app component, add state:

```javascript
const [codingHealth, setCodingHealth] = useState({providers:[]});
const [codingSession, setCodingSession] = useState(null);
const [codingEvents, setCodingEvents] = useState([]);
const [codingProjectRoot, setCodingProjectRoot] = useState("");
const [codingProvider, setCodingProvider] = useState("codex");
const [codingAccessMode, setCodingAccessMode] = useState("read_only");
```

Add a boot effect:

```javascript
useEffect(() => {
  const api = window.__vellumCodingApi;
  if (!api) return;
  api.health().then(setCodingHealth).catch(() => setCodingHealth({providers:[]}));
}, []);
```

Replace the Coding-mode send branch with:

```javascript
else if(activeMode==="coding"){
  runBackendCodingTurn(chatId, aid, t);
}
```

Add:

```javascript
async function ensureCodingSession(){
  if(codingSession) return codingSession;
  const api = window.__vellumCodingApi;
  if(!api) throw new Error("Coding API unavailable");
  if(!codingProjectRoot) throw new Error("Open a project folder first.");
  const session = await api.createSession({
    provider: codingProvider,
    cwd: codingProjectRoot,
    access_mode: codingAccessMode,
    title: chatTitleFor(activeChat) || "Coding session",
  });
  setCodingSession(session);
  return session;
}

async function runBackendCodingTurn(chatId, aid, text){
  try{
    const session = await ensureCodingSession();
    const api = window.__vellumCodingApi;
    let finalText = "";
    await api.runTurn(session.id, text, ({event, data}) => {
      setCodingEvents(prev => [...prev, {event, data}]);
      const payload = data && data.payload ? data.payload : {};
      if(event === "assistant_delta" && payload.text){
        setMsgsFor(chatId, m => m.map(x => x.id===aid ? {...x, text:(x.text||"")+payload.text, thinking:false} : x));
      }
      if(event === "assistant_final" && payload.text){
        finalText = payload.text;
        setMsgsFor(chatId, m => m.map(x => x.id===aid ? {...x, text:payload.text, thinking:false, streaming:false} : x));
      }
      if(event === "error"){
        const msg = (data && data.message) || payload.error || "Coding run failed.";
        setMsgsFor(chatId, m => m.map(x => x.id===aid ? {...x, text:msg, thinking:false, streaming:false} : x));
      }
    });
    setMsgsFor(chatId, m => m.map(x => x.id===aid ? {...x, text:finalText || x.text, thinking:false, streaming:false} : x));
  }catch(e){
    setMsgsFor(chatId, m => m.map(x => x.id===aid ? {...x, text:(e && e.message) || "Coding API unavailable", thinking:false, streaming:false} : x));
  }finally{
    setRunning(false);
  }
}
```

- [ ] **Step 4: Add real Coding Home controls**

In the Coding-mode workspace panel, render:

```jsx
<div className="workspace-empty">
  <div style={{fontSize:14,color:"#aaa",marginBottom:8}}>Coding Assistant</div>
  <div style={{marginBottom:12}}>Open a project folder, then run Codex or Claude Code from this workspace.</div>
  <input
    className="modal-input"
    value={codingProjectRoot}
    onChange={(e)=>setCodingProjectRoot(e.target.value)}
    placeholder="D:\Vellum"
  />
  <div style={{display:"flex",gap:8,justifyContent:"center",marginTop:12,flexWrap:"wrap"}}>
    <button className="modal-btn" onClick={()=>setCodingProvider("codex")}>Codex</button>
    <button className="modal-btn" onClick={()=>setCodingProvider("claude")}>Claude Code</button>
    <button className="modal-btn" onClick={()=>setCodingAccessMode("read_only")}>Read only</button>
    <button className="modal-btn" onClick={()=>setCodingAccessMode("workspace_write")}>Workspace write</button>
  </div>
  <div className="cm-note" style={{marginTop:12}}>
    {codingHealth.providers.map(p => `${p.provider}: ${p.message}`).join(" · ") || "Backend unavailable."}
  </div>
</div>
```

- [ ] **Step 5: Smoke test in browser**

Run:

```bash
cd D:\Vellum\frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173/ui/vellum-workspace.html?desktop=1
```

Expected:

- Vellum workspace loads.
- Coding mode shows empty real state, not fake messages or fake subagents.
- Provider health attempts to load from backend.
- Sending without a project shows "Open a project folder first."

- [ ] **Step 6: Commit**

```bash
git add frontend/ui/vellum-workspace.html
git commit -m "feat(ui): add real coding workspace shell"
```

---

## Task 8: Tauri Opens The Workspace Shell

**Files:**
- Modify: `desktop/src-tauri/src/lib.rs`

- [ ] **Step 1: Change the desktop Vellum URL**

Modify `desktop/src-tauri/src/lib.rs`:

```rust
const VELLUM_CHAT_URL: &str = "http://127.0.0.1:5173/ui/vellum-workspace.html?desktop=1";
```

- [ ] **Step 2: Build-check desktop Rust**

Run:

```bash
cd D:\Vellum\desktop
npm run test
```

Expected: `desktop smoke tests are manual for milestone 1`.

- [ ] **Step 3: Commit**

```bash
git add desktop/src-tauri/src/lib.rs
git commit -m "feat(desktop): open workspace shell"
```

---

## Task 9: End-To-End Verification

**Files:**
- No source edits unless verification exposes a defect.

- [ ] **Step 1: Run backend tests**

Run:

```bash
cd D:\Vellum\backend
pytest tests/test_coding_storage.py tests/test_coding_adapters.py tests/test_coding_service.py tests/test_coding_api.py tests/test_coding_project_tree.py tests/test_terminal_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run frontend tests**

Run:

```bash
cd D:\Vellum\frontend
npm test -- ui/coding-api.test.js ui/terminal/terminal-workspace.test.js
```

Expected: all selected tests pass.

- [ ] **Step 3: Start backend**

Run:

```bash
cd D:\Vellum\backend
python -m uvicorn agent.api:app --host 127.0.0.1 --port 8000
```

Expected: backend starts and `/api/coding/health` returns provider health.

- [ ] **Step 4: Start frontend**

Run in another terminal:

```bash
cd D:\Vellum\frontend
npm run dev
```

Expected: Vite serves `http://127.0.0.1:5173`.

- [ ] **Step 5: Manual MVP check**

Open:

```text
http://127.0.0.1:5173/ui/vellum-workspace.html?desktop=1
```

Expected:

- No fake initial coding transcript.
- No static worker names appear unless real provider events created them.
- Coding health is visible.
- A project path can be entered.
- A Codex run either returns a real SDK response or a truthful missing-SDK/auth message.
- A Claude run either returns a real SDK response or a truthful missing-SDK/auth message.
- Terminal tab still connects through `/api/terminal/ws`.
- Browser tab still uses `/api/computer-use/workspace/action`.

- [ ] **Step 6: Inspect final state after verification**

If no fixes were needed:

```bash
git status --short
```

Expected: clean.

If fixes were made during verification, inspect the exact diff before committing:

```bash
git status --short
git diff -- backend/agent/coding backend/tests/test_coding_storage.py backend/tests/test_coding_adapters.py backend/tests/test_coding_service.py backend/tests/test_coding_api.py backend/tests/test_coding_project_tree.py backend/agent/api.py backend/pyproject.toml backend/requirements.txt frontend/ui/coding-api.js frontend/ui/coding-api.test.js frontend/ui/vellum-workspace.html desktop/src-tauri/src/lib.rs
```

Expected: only files from this plan appear. If unrelated files appear, stop and resolve ownership before committing.

## Spec Coverage Review

- Real SDK-backed session boundary: Tasks 1-5.
- Provider-neutral event contract: Tasks 1, 3, 4, 6, 7.
- Real project folder and file tree: Task 4 and Task 7.
- No fake coding data in production path: Task 7 and Task 9.
- Existing terminal/browser continuity: Task 7 and Task 9.
- Tauri desktop routing: Task 8.
- Tests and manual verification: each task has focused tests; Task 9 closes the loop.
