from pathlib import Path
import json
import sqlite3

import pytest

from agent.coding.events import event_name, sse
from agent.coding.models import AccessMode, CodingSessionCreate, ProviderName
from agent.coding import storage as coding_storage
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
