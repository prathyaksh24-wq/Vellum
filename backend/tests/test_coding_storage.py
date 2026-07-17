from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3

import pytest

from agent.coding.events import event_name, sse
from agent.coding.models import AccessMode, CodingSessionCreate, ProviderName, WorkspaceKind
from agent.coding import storage as coding_storage
from agent.coding.storage import CodingSessionStore, CodingTurnConflictError
from agent.coding.workspace import WorkspaceSnapshot


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
    assert session.source_cwd == str(tmp_path.resolve())
    assert session.workspace_kind == WorkspaceKind.direct
    assert session.workspace_root == str(tmp_path.resolve())

    listed = store.list_sessions()
    assert [item.id for item in listed] == [session.id]


def test_coding_store_updates_session_workspace_metadata(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))
    isolated = tmp_path / "worktrees" / session.id

    updated = store.set_session_workspace(
        session.id,
        source_cwd=str(tmp_path.resolve()),
        cwd=str(isolated),
        workspace_kind=WorkspaceKind.git_worktree,
        workspace_root=str(isolated),
        workspace_repository_root=str(tmp_path.resolve()),
        workspace_branch=f"vellum/session/{session.id}",
        workspace_base_commit="abc123",
    )

    assert updated.cwd == str(isolated)
    assert updated.source_cwd == str(tmp_path.resolve())
    assert updated.workspace_kind == WorkspaceKind.git_worktree
    assert updated.workspace_repository_root == str(tmp_path.resolve())
    assert updated.workspace_branch == f"vellum/session/{session.id}"
    assert updated.workspace_base_commit == "abc123"


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


def test_coding_store_finish_running_turn_only_allows_one_terminal_transition(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))
    turn = store.create_turn(session.id, "Run tests")

    first = store.finish_running_turn(turn.id, status="stopped", error="first stop")
    second = store.finish_running_turn(turn.id, status="stopped", error="second stop")

    assert first is not None
    assert first.status == "stopped"
    assert first.error == "first stop"
    assert second is None
    persisted = store.get_turn(turn.id)
    assert persisted is not None
    assert persisted.status == "stopped"
    assert persisted.error == "first stop"


def test_coding_store_persists_bounded_checkpoint_lifecycle(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))
    turn = store.create_turn(session.id, "Change app")
    before = WorkspaceSnapshot(captured_at="t0", git_head="abc", changed_files=(), patch="")
    checkpoint = store.create_checkpoint(session_id=session.id, turn_id=turn.id, before=before)
    after = WorkspaceSnapshot(
        captured_at="t1",
        git_head="abc",
        changed_files=("app.py",),
        patch="diff --git a/app.py b/app.py\n",
        patch_truncated=True,
    )

    finalized = store.finish_checkpoint(turn.id, status="completed", after=after)

    assert finalized is not None
    assert finalized.id == checkpoint.id
    assert finalized.status == "completed"
    assert finalized.after == after
    assert store.get_checkpoint(checkpoint.id) == finalized
    assert store.get_checkpoint_for_turn(turn.id) == finalized
    assert store.list_checkpoints(session.id) == [finalized]
    summary = finalized.payload(include_patch=False)
    assert "patch" not in summary["after"]
    assert summary["after"]["patch_bytes"] == len(after.patch.encode("utf-8"))


def test_coding_store_prunes_old_checkpoints_per_session(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))
    checkpoint_ids = []
    for index in range(3):
        turn = store.create_turn(session.id, f"Turn {index}")
        checkpoint = store.create_checkpoint(
            session_id=session.id,
            turn_id=turn.id,
            before=WorkspaceSnapshot(captured_at=f"t{index}"),
            max_per_session=2,
        )
        checkpoint_ids.append(checkpoint.id)
        store.finish_checkpoint(
            turn.id,
            status="completed",
            after=WorkspaceSnapshot(captured_at=f"t{index}-after"),
        )
        store.finish_turn(turn.id, status="completed")
        store.set_session_status(session.id, "idle")

    retained = store.list_checkpoints(session.id)

    assert [checkpoint.id for checkpoint in retained] == list(reversed(checkpoint_ids[-2:]))
    assert store.get_checkpoint(checkpoint_ids[0]) is None


def test_coding_store_rejects_orphan_turns_and_events(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")

    with pytest.raises(sqlite3.IntegrityError):
        store.create_turn("missing-session", "Run tests")

    with pytest.raises(sqlite3.IntegrityError):
        store.record_event(
            session_id="missing-session",
            turn_id=None,
            provider=ProviderName.codex,
            event_type="assistant.final",
            message="Done",
            payload={},
        )


def test_coding_store_rejects_event_turn_from_another_session(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    first = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path), title="First"))
    second = store.create_session(CodingSessionCreate(provider=ProviderName.claude, cwd=str(tmp_path), title="Second"))
    first_turn = store.create_turn(first.id, "Run tests")

    with pytest.raises(sqlite3.IntegrityError):
        store.record_event(
            session_id=second.id,
            turn_id=first_turn.id,
            provider=ProviderName.claude,
            event_type="assistant.final",
            message="Done",
            payload={},
        )


def test_coding_store_lists_newest_sessions_first_when_timestamps_match(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(coding_storage, "utc_now", lambda: "2026-06-06T00:00:00+00:00")
    store = CodingSessionStore(tmp_path / "coding.db")
    first = store.create_session(
        CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path), title="First")
    )
    second = store.create_session(
        CodingSessionCreate(provider=ProviderName.claude, cwd=str(tmp_path), title="Second")
    )

    assert [session.id for session in store.list_sessions()] == [second.id, first.id]


def test_coding_event_helpers_serialize_provider_neutral_sse(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))
    event = store.record_event(
        session_id=session.id,
        turn_id=None,
        provider=ProviderName.codex,
        event_type="assistant.final",
        message="Done",
        payload={"text": "All tests pass"},
    )

    assert event_name("unknown.type") == "coding"
    encoded = sse(event)
    assert encoded.startswith("event: assistant_final\n")
    data_line = next(line for line in encoded.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["id"] == event.id
    assert payload["provider"] == "codex"
    assert payload["type"] == "assistant.final"
    assert payload["payload"] == {"text": "All tests pass"}
    assert payload["trace_id"] == event.trace_id
    assert payload["sequence"] == 1


def test_coding_store_scopes_sessions_and_replays_events_by_sequence(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    local = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))
    other = store.create_session(
        CodingSessionCreate(
            provider=ProviderName.claude,
            cwd=str(tmp_path),
            tenant_id="beta-tenant",
            principal_id="beta-user",
        )
    )
    turn = store.create_turn(local.id, "Inspect")
    first = store.record_event(
        session_id=local.id,
        turn_id=turn.id,
        provider=ProviderName.codex,
        event_type="assistant.delta",
        message="one",
        payload={},
    )
    second = store.record_event(
        session_id=local.id,
        turn_id=turn.id,
        provider=ProviderName.codex,
        event_type="assistant.final",
        message="two",
        payload={},
    )

    assert [session.id for session in store.list_sessions(tenant_id="local")] == [local.id]
    assert [session.id for session in store.list_sessions(principal_id="beta-user")] == [other.id]
    assert first.sequence == 1
    assert second.sequence == 2
    assert first.trace_id == turn.trace_id == second.trace_id
    assert [event.id for event in store.list_events(local.id, after_sequence=1)] == [second.id]


def test_coding_store_serializes_concurrent_event_sequences(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))

    def record(index: int):
        return store.record_event(
            session_id=session.id,
            provider=ProviderName.codex,
            event_type="tool.completed",
            message=str(index),
            payload={"index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        recorded = list(executor.map(record, range(40)))

    assert sorted(event.sequence for event in recorded) == list(range(1, 41))
    assert [event.sequence for event in store.list_events(session.id)] == list(range(1, 41))


def test_coding_store_allows_only_one_concurrent_turn_start(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    session = store.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path)))

    def start(index: int):
        try:
            return store.create_turn(session.id, f"turn {index}")
        except CodingTurnConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start, range(2)))

    turns = [result for result in results if not isinstance(result, Exception)]
    conflicts = [result for result in results if isinstance(result, CodingTurnConflictError)]
    assert len(turns) == 1
    assert len(conflicts) == 1
    assert store.get_session(session.id).status == "running"


def test_coding_store_migrates_legacy_database_without_losing_events(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE coding_sessions (
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
            CREATE TABLE coding_turns (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                final_response TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX idx_coding_turns_id_session_id ON coding_turns(id, session_id);
            CREATE TABLE coding_events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT,
                provider TEXT NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO coding_sessions VALUES (
                'code_old', 'codex', NULL, 'D:\\Vellum', 'read_only', 'Legacy', 'idle', 't0', 't0'
            );
            INSERT INTO coding_turns VALUES (
                'turn_old', 'code_old', 'Inspect', 'completed', 't1', 't2', 'Done', ''
            );
            INSERT INTO coding_events VALUES (
                'evt_old_1', 'code_old', 'turn_old', 'codex', 'assistant.delta', 'One', '{}', 't1'
            );
            INSERT INTO coding_events VALUES (
                'evt_old_2', 'code_old', 'turn_old', 'codex', 'assistant.final', 'Two', '{}', 't2'
            );
            """
        )

    store = CodingSessionStore(db_path)

    session = store.get_session("code_old")
    turn = store.get_turn("turn_old")
    events = store.list_events("code_old")
    assert session is not None
    assert session.tenant_id == "local"
    assert session.principal_id == "local-user"
    assert session.source_cwd == "D:\\Vellum"
    assert session.workspace_kind == WorkspaceKind.direct
    assert session.workspace_root == "D:\\Vellum"
    assert session.trace_id.startswith("trace_")
    assert turn is not None
    assert turn.trace_id.startswith("trace_")
    assert [event.sequence for event in events] == [1, 2]
    assert {event.trace_id for event in events} == {turn.trace_id}

    reopened = CodingSessionStore(db_path)
    assert reopened.get_session("code_old").trace_id == session.trace_id
    assert reopened.get_turn("turn_old").trace_id == turn.trace_id
    assert [event.sequence for event in reopened.list_events("code_old")] == [1, 2]
