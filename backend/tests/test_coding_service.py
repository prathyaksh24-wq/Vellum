from collections.abc import AsyncIterator
import asyncio
from pathlib import Path
import subprocess

from agent.coding.models import (
    AccessMode,
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    CodingTurnLimits,
    ProviderHealth,
    ProviderName,
    utc_now,
)
from agent.coding.service import CodingServiceError, CodingSessionService
from agent.coding.storage import CodingSessionStore
from agent.coding.workspace import CodingWorkspaceManager


class FakeAdapter:
    provider = ProviderName.codex

    def health(self):
        return ProviderHealth(self.provider, True, True, "ready")

    async def start_session(self, request: CodingSessionCreate):
        return "provider-thread-1"

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        yield CodingEvent(
            "",
            session.id,
            turn_id,
            self.provider,
            "assistant.final",
            "done",
            {"text": f"answer: {prompt}"},
            utc_now(),
        )

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        return None


class FailingStartAdapter(FakeAdapter):
    async def start_session(self, request: CodingSessionCreate):
        raise RuntimeError("sdk unavailable")


class RequestRecordingAdapter(FakeAdapter):
    def __init__(self) -> None:
        self.requests: list[CodingSessionCreate] = []

    async def start_session(self, request: CodingSessionCreate):
        self.requests.append(request)
        return await super().start_session(request)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "Vellum Tests")
    _git(path, "config", "user.email", "vellum-tests@example.invalid")
    (path / "app.py").write_text("print('ready')\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


class ResumingAdapter(FakeAdapter):
    async def start_session(self, request: CodingSessionCreate):
        return None

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        yield CodingEvent(
            "",
            session.id,
            turn_id,
            self.provider,
            "session.resumed",
            "resumed",
            {"provider_session_id": "provider-thread-2"},
            utc_now(),
        )
        yield CodingEvent("", session.id, turn_id, self.provider, "assistant.final", "done", {"text": "ok"}, utc_now())


class FailingTurnAdapter(FakeAdapter):
    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        raise RuntimeError("turn failed")
        yield


class WritingAdapter(FakeAdapter):
    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        (Path(session.cwd) / "app.py").write_text("print('agent changed this')\n", encoding="utf-8")
        yield CodingEvent(
            "",
            session.id,
            turn_id,
            self.provider,
            "assistant.final",
            "done",
            {"text": "updated"},
            utc_now(),
        )


class StopRecordingAdapter(FakeAdapter):
    def __init__(self):
        self.stopped = []

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        self.stopped.append((session.id, turn_id))


class GatedAdapter(FakeAdapter):
    def __init__(self):
        self.release = asyncio.Event()

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        await self.release.wait()
        yield CodingEvent("", session.id, turn_id, self.provider, "assistant.final", "done", {"text": "late"}, utc_now())


class FailingAfterStopAdapter(FakeAdapter):
    def __init__(self):
        self.release = asyncio.Event()

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        await self.release.wait()
        raise RuntimeError("provider cancelled")
        yield


class QuietAfterStopAdapter(StopRecordingAdapter):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        await self.release.wait()
        if False:
            yield CodingEvent("", session.id, turn_id, self.provider, "assistant.final", "done", {}, utc_now())

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        await super().stop_turn(session, turn_id)
        self.release.set()


class CompletingDuringStopAdapter(StopRecordingAdapter):
    def __init__(self):
        super().__init__()
        self.stop_started = asyncio.Event()
        self.stop_release = asyncio.Event()

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        await self.stop_started.wait()
        yield CodingEvent("", session.id, turn_id, self.provider, "assistant.final", "done", {"text": "late"}, utc_now())

    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        await super().stop_turn(session, turn_id)
        self.stop_started.set()
        await self.stop_release.wait()


class FailingStopAdapter(StopRecordingAdapter):
    async def stop_turn(self, session: CodingSession, turn_id: str) -> None:
        await super().stop_turn(session, turn_id)
        raise RuntimeError("stop failed")


class BurstAdapter(StopRecordingAdapter):
    def __init__(self, event_count: int):
        super().__init__()
        self.event_count = event_count

    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        for index in range(self.event_count):
            yield CodingEvent(
                "",
                session.id,
                turn_id,
                self.provider,
                "assistant.delta",
                str(index),
                {"text": str(index)},
                utc_now(),
            )


class SlowAdapter(StopRecordingAdapter):
    async def run_turn(self, session: CodingSession, prompt: str, turn_id: str) -> AsyncIterator[CodingEvent]:
        await asyncio.sleep(60)
        if False:
            yield CodingEvent("", session.id, turn_id, self.provider, "assistant.final", "done", {}, utc_now())


def test_service_creates_session_and_records_provider_id(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )

    session = asyncio.run(
        service.create_session(
            CodingSessionCreate(
                provider=ProviderName.codex,
                cwd=str(tmp_path),
                access_mode=AccessMode.read_only,
            )
        )
    )

    assert session.provider_session_id == "provider-thread-1"
    assert session.cwd == str(tmp_path.resolve())
    [event] = service.list_events(session.id)
    assert event.type == "session.started"
    assert event.payload == {
        "cwd": str(tmp_path.resolve()),
        "source_cwd": str(tmp_path.resolve()),
        "provider_session_id": "provider-thread-1",
        "workspace": {
            "kind": "direct",
            "root": str(tmp_path.resolve()),
            "branch": "",
            "base_commit": "",
        },
    }


def test_service_provisions_writable_git_worktree_before_starting_provider(tmp_path: Path):
    repository = _git_repository(tmp_path / "project")
    adapter = RequestRecordingAdapter()
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: adapter},
        workspace_manager=CodingWorkspaceManager(tmp_path / "worktrees"),
    )

    session = asyncio.run(
        service.create_session(
            CodingSessionCreate(
                provider=ProviderName.codex,
                cwd=str(repository),
                access_mode=AccessMode.workspace_write,
            )
        )
    )

    assert session.source_cwd == str(repository.resolve())
    assert session.workspace_kind.value == "git_worktree"
    assert session.workspace_branch == f"vellum/session/{session.id}"
    assert session.workspace_base_commit == _git(repository, "rev-parse", "HEAD")
    assert Path(session.cwd).parent == (tmp_path / "worktrees").resolve()
    assert adapter.requests[0].cwd == session.cwd


def test_service_rejects_writable_non_git_project_without_persisting_session(tmp_path: Path):
    source = tmp_path / "project"
    source.mkdir()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(
        store=store,
        adapters={ProviderName.codex: FakeAdapter()},
        workspace_manager=CodingWorkspaceManager(tmp_path / "worktrees"),
    )

    try:
        asyncio.run(
            service.create_session(
                CodingSessionCreate(
                    provider=ProviderName.codex,
                    cwd=str(source),
                    access_mode=AccessMode.workspace_write,
                )
            )
        )
    except CodingServiceError as exc:
        assert "require a Git repository" in str(exc)
    else:
        raise AssertionError("expected writable non-Git project failure")

    assert store.list_sessions() == []


def test_service_close_requires_discard_for_dirty_worktree_and_preserves_branch(tmp_path: Path):
    repository = _git_repository(tmp_path / "project")
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(
        store=store,
        adapters={ProviderName.codex: FakeAdapter()},
        workspace_manager=CodingWorkspaceManager(tmp_path / "worktrees"),
    )
    session = asyncio.run(
        service.create_session(
            CodingSessionCreate(
                provider=ProviderName.codex,
                cwd=str(repository),
                access_mode=AccessMode.workspace_write,
            )
        )
    )
    (Path(session.cwd) / "agent-change.txt").write_text("pending\n", encoding="utf-8")

    try:
        asyncio.run(service.close_session(session.id))
    except CodingServiceError as exc:
        assert "uncommitted changes" in str(exc)
    else:
        raise AssertionError("expected dirty workspace close failure")

    assert Path(session.workspace_root).exists()
    closed = asyncio.run(service.close_session(session.id, discard_changes=True))

    assert closed.status == "closed"
    assert not Path(session.workspace_root).exists()
    assert _git(repository, "branch", "--list", session.workspace_branch) == f"{session.workspace_branch}"
    assert store.list_events(session.id)[-1].type == "session.closed"

    async def collect_closed_turn():
        return [event async for event in service.run_turn(session.id, "continue")]

    try:
        asyncio.run(collect_closed_turn())
    except CodingServiceError as exc:
        assert "session is closed" in str(exc)
    else:
        raise AssertionError("expected closed session turn failure")


def test_service_reports_health_from_configured_adapters(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )

    [health] = service.health()

    assert health.provider == ProviderName.codex
    assert health.available is True
    assert health.configured is True
    assert health.message == "ready"


def test_service_lists_sessions_from_store(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )
    first = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    second = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    sessions = service.list_sessions()

    assert [session.id for session in sessions] == [second.id, first.id]


def test_service_get_session_rejects_missing_session(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )

    try:
        service.get_session("missing-session")
    except CodingServiceError as exc:
        assert str(exc) == "Coding session not found."
    else:
        raise AssertionError("expected missing session failure")


def test_service_create_session_rejects_missing_project(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )

    try:
        asyncio.run(
            service.create_session(
                CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path / "missing-project"))
            )
        )
    except CodingServiceError as exc:
        assert str(exc) == "Project not found."
    else:
        raise AssertionError("expected missing project failure")


def test_service_list_events_rejects_missing_session(tmp_path: Path):
    service = CodingSessionService(
        store=CodingSessionStore(tmp_path / "coding.db"),
        adapters={ProviderName.codex: FakeAdapter()},
    )

    try:
        service.list_events("missing-session")
    except CodingServiceError as exc:
        assert str(exc) == "Coding session not found."
    else:
        raise AssertionError("expected missing session failure")


def test_service_does_not_persist_session_when_provider_start_fails(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FailingStartAdapter()})

    try:
        asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    except CodingServiceError as exc:
        assert str(exc) == "Coding session failed to start."
        assert exc.__cause__ is not None
        assert str(exc.__cause__) == "sdk unavailable"
    else:
        raise AssertionError("expected provider start failure")

    assert store.list_sessions() == []


def test_service_releases_created_worktree_when_provider_start_fails(tmp_path: Path):
    repository = _git_repository(tmp_path / "project")
    worktree_root = tmp_path / "worktrees"
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(
        store=store,
        adapters={ProviderName.codex: FailingStartAdapter()},
        workspace_manager=CodingWorkspaceManager(worktree_root),
    )

    try:
        asyncio.run(
            service.create_session(
                CodingSessionCreate(
                    provider=ProviderName.codex,
                    cwd=str(repository),
                    access_mode=AccessMode.workspace_write,
                )
            )
        )
    except CodingServiceError as exc:
        assert str(exc) == "Coding session failed to start."
    else:
        raise AssertionError("expected provider start failure")

    assert store.list_sessions() == []
    assert list(worktree_root.iterdir()) == []
    assert _git(repository, "branch", "--list", "vellum/session/*") == ""


def test_service_honors_empty_adapter_map(tmp_path: Path):
    service = CodingSessionService(store=CodingSessionStore(tmp_path / "coding.db"), adapters={})

    try:
        asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    except CodingServiceError as exc:
        assert str(exc) == "Provider is not configured."
    else:
        raise AssertionError("expected missing provider failure")


def test_service_streams_turn_and_persists_events(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [event async for event in service.run_turn(session.id, "hello")]

    events = asyncio.run(collect())

    assert [event.type for event in events] == ["turn.started", "assistant.final", "turn.completed"]
    persisted = store.list_events(session.id)
    assert [event.type for event in persisted] == [
        "session.started",
        "turn.started",
        "assistant.final",
        "turn.completed",
    ]
    assistant_event = next(event for event in persisted if event.type == "assistant.final")
    assert assistant_event.payload == {"text": "answer: hello"}


def test_service_captures_before_and_after_workspace_checkpoint(tmp_path: Path):
    repository = _git_repository(tmp_path / "project")
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(
        store=store,
        adapters={ProviderName.codex: WritingAdapter()},
        workspace_manager=CodingWorkspaceManager(tmp_path / "worktrees"),
    )
    session = asyncio.run(
        service.create_session(
            CodingSessionCreate(
                provider=ProviderName.codex,
                cwd=str(repository),
                access_mode=AccessMode.workspace_write,
            )
        )
    )

    async def collect():
        return [event async for event in service.run_turn(session.id, "Update app")]

    events = asyncio.run(collect())
    checkpoint_id = events[0].payload["checkpoint_id"]
    checkpoint = service.get_checkpoint(session.id, checkpoint_id)

    assert checkpoint.status == "completed"
    assert checkpoint.before.changed_files == ()
    assert checkpoint.after is not None
    assert checkpoint.after.changed_files == ("app.py",)
    assert "agent changed this" in checkpoint.after.patch
    assert events[-1].payload["checkpoint"]["id"] == checkpoint_id
    assert "patch" not in events[-1].payload["checkpoint"]["after"]
    assert service.list_checkpoints(session.id) == [checkpoint]


def test_service_rejects_concurrent_turn_for_session(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    store.set_session_status(session.id, "running")

    async def collect():
        return [event async for event in service.run_turn(session.id, "hello")]

    try:
        asyncio.run(collect())
    except CodingServiceError as exc:
        assert str(exc) == "Coding session already has a running turn."
    else:
        raise AssertionError("expected concurrent turn failure")


def test_service_persists_provider_id_from_session_resumed_event(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: ResumingAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [event async for event in service.run_turn(session.id, "hello")]

    events = asyncio.run(collect())

    assert [event.type for event in events] == [
        "turn.started",
        "session.resumed",
        "assistant.final",
        "turn.completed",
    ]
    assert service.get_session(session.id).provider_session_id == "provider-thread-2"


def test_service_persists_turn_error_and_status(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FailingTurnAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [event async for event in service.run_turn(session.id, "hello")]

    events = asyncio.run(collect())

    assert [event.type for event in events] == ["turn.started", "turn.error"]
    assert events[-1].payload["error"] == "turn failed"
    assert events[-1].payload["checkpoint"]["status"] == "error"
    assert service.get_session(session.id).status == "error"


def test_service_stop_turn_calls_adapter_and_marks_stopped(tmp_path: Path):
    adapter = StopRecordingAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    turn = store.create_turn(session.id, "hello")
    store.set_session_status(session.id, "running")

    asyncio.run(service.stop_turn(session.id))

    assert adapter.stopped == [(session.id, turn.id)]
    assert service.get_session(session.id).status == "stopped"
    stopped_turn = store.get_turn(turn.id)
    assert stopped_turn is not None
    assert stopped_turn.status == "stopped"
    assert stopped_turn.error == "Coding turn stopped."
    assert store.list_events(session.id)[-1].type == "turn.stopped"


def test_service_stop_turn_prevents_live_stream_from_overwriting_stopped_state(tmp_path: Path):
    adapter = GatedAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def run_stop_then_release():
        stream = service.run_turn(session.id, "hello")
        first = await anext(stream)
        await service.stop_turn(session.id)
        adapter.release.set()
        remaining = [event async for event in stream]
        return first, remaining

    first, remaining = asyncio.run(run_stop_then_release())

    assert first.type == "turn.started"
    assert remaining == []
    turn = store.get_turn(first.turn_id)
    assert turn is not None
    assert turn.status == "stopped"
    assert service.get_session(session.id).status == "stopped"
    assert [event.type for event in store.list_events(session.id)] == [
        "session.started",
        "turn.started",
        "turn.stopped",
    ]


def test_service_stop_turn_prevents_late_provider_error_from_overwriting_stopped_state(tmp_path: Path):
    adapter = FailingAfterStopAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def run_stop_then_release():
        stream = service.run_turn(session.id, "hello")
        first = await anext(stream)
        await service.stop_turn(session.id)
        adapter.release.set()
        remaining = [event async for event in stream]
        return first, remaining

    first, remaining = asyncio.run(run_stop_then_release())

    assert first.type == "turn.started"
    assert remaining == []
    turn = store.get_turn(first.turn_id)
    assert turn is not None
    assert turn.status == "stopped"
    assert service.get_session(session.id).status == "stopped"
    assert [event.type for event in store.list_events(session.id)] == [
        "session.started",
        "turn.started",
        "turn.stopped",
    ]


def test_service_stop_turn_handles_provider_quiet_exit_without_completion(tmp_path: Path):
    adapter = QuietAfterStopAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def run_stop_then_collect():
        stream = service.run_turn(session.id, "hello")
        first = await anext(stream)
        await service.stop_turn(session.id)
        remaining = [event async for event in stream]
        return first, remaining

    first, remaining = asyncio.run(run_stop_then_collect())

    assert first.type == "turn.started"
    assert remaining == []
    turn = store.get_turn(first.turn_id)
    assert turn is not None
    assert turn.status == "stopped"
    assert turn.final_response == ""
    assert adapter.stopped == [(session.id, first.turn_id)]
    assert [event.type for event in store.list_events(session.id)] == [
        "session.started",
        "turn.started",
        "turn.stopped",
    ]


def test_service_stop_turn_wins_when_provider_completes_while_stop_is_pending(tmp_path: Path):
    adapter = CompletingDuringStopAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def run_race():
        stream = service.run_turn(session.id, "hello")
        first = await anext(stream)
        stop_task = asyncio.create_task(service.stop_turn(session.id))
        await adapter.stop_started.wait()
        remaining = [event async for event in stream]
        adapter.stop_release.set()
        await stop_task
        return first, remaining

    first, remaining = asyncio.run(run_race())

    assert first.type == "turn.started"
    assert remaining == []
    turn = store.get_turn(first.turn_id)
    assert turn is not None
    assert turn.status == "stopped"
    assert turn.final_response == ""
    assert service.get_session(session.id).status == "stopped"
    assert [event.type for event in store.list_events(session.id)] == [
        "session.started",
        "turn.started",
        "turn.stopped",
    ]


def test_service_stop_turn_keeps_local_stopped_state_when_provider_stop_fails(tmp_path: Path):
    adapter = FailingStopAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    turn = store.create_turn(session.id, "hello")
    store.set_session_status(session.id, "running")

    try:
        asyncio.run(service.stop_turn(session.id))
    except RuntimeError as exc:
        assert str(exc) == "stop failed"
    else:
        raise AssertionError("expected provider stop failure")

    stopped_turn = store.get_turn(turn.id)
    assert stopped_turn is not None
    assert stopped_turn.status == "stopped"
    assert service.get_session(session.id).status == "stopped"
    assert store.list_events(session.id)[-1].type == "turn.stopped"


def test_service_stop_turn_rejects_turn_from_another_session(tmp_path: Path):
    adapter = StopRecordingAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    first = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    second = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    turn = store.create_turn(first.id, "hello")

    try:
        asyncio.run(service.stop_turn(second.id, turn.id))
    except CodingServiceError as exc:
        assert str(exc) == "Coding turn does not belong to session."
    else:
        raise AssertionError("expected cross-session stop failure")

    assert store.get_turn(turn.id).status == "running"
    assert adapter.stopped == []


def test_service_stop_turn_rejects_missing_turn_id(tmp_path: Path):
    adapter = StopRecordingAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    try:
        asyncio.run(service.stop_turn(session.id, "missing-turn"))
    except CodingServiceError as exc:
        assert str(exc) == "Coding turn is not running."
    else:
        raise AssertionError("expected missing turn stop failure")

    assert service.get_session(session.id).status == "idle"
    assert adapter.stopped == []


def test_service_stop_turn_without_running_turn_stops_session(tmp_path: Path):
    adapter = StopRecordingAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    asyncio.run(service.stop_turn(session.id))

    assert service.get_session(session.id).status == "stopped"
    assert adapter.stopped == [(session.id, "")]


def test_service_initialization_marks_stale_running_turns_stopped(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))
    turn = store.create_turn(session.id, "hello")
    store.set_session_status(session.id, "running")

    restarted = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})

    stopped_turn = store.get_turn(turn.id)
    assert stopped_turn is not None
    assert stopped_turn.status == "stopped"
    assert stopped_turn.error == "Coding turn interrupted by restart."
    assert restarted.get_session(session.id).status == "stopped"


def test_service_marks_turn_stopped_when_stream_is_closed(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def read_one_then_close():
        stream = service.run_turn(session.id, "hello")
        first = await anext(stream)
        await stream.aclose()
        return first

    first = asyncio.run(read_one_then_close())

    assert first.type == "turn.started"
    assert service.get_session(session.id).status == "stopped"
    turn = store.get_turn(first.turn_id)
    assert turn is not None
    assert turn.status == "stopped"
    assert turn.error == "Coding turn cancelled."


def test_service_propagates_trace_and_sequence_across_turn_events(tmp_path: Path):
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: FakeAdapter()})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [event async for event in service.run_turn(session.id, "hello")]

    events = asyncio.run(collect())
    persisted = store.list_events(session.id)
    turn_events = [event for event in persisted if event.turn_id == events[0].turn_id]

    assert len({event.trace_id for event in turn_events}) == 1
    assert turn_events[0].trace_id.startswith("trace_")
    assert [event.sequence for event in persisted] == list(range(1, len(persisted) + 1))
    assert events[0].payload["trace_id"] == turn_events[0].trace_id


def test_service_stops_provider_at_event_limit(tmp_path: Path):
    adapter = BurstAdapter(event_count=3)
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [
            event
            async for event in service.run_turn(
                session.id,
                "hello",
                limits=CodingTurnLimits(max_runtime_seconds=30, max_provider_events=2),
            )
        ]

    events = asyncio.run(collect())
    turn = store.get_turn(events[0].turn_id)

    assert [event.type for event in events] == [
        "turn.started",
        "assistant.delta",
        "assistant.delta",
        "turn.limit_reached",
    ]
    assert events[-1].payload["reason"] == "provider_event_count"
    assert events[-1].payload["limit"] == 2
    assert events[-1].payload["provider_event_count"] == 2
    assert events[-1].payload["checkpoint"]["status"] == "stopped"
    assert turn is not None
    assert turn.status == "stopped"
    assert turn.provider_event_count == 2
    assert service.get_session(session.id).status == "stopped"
    assert adapter.stopped == [(session.id, turn.id)]


def test_service_stops_provider_at_runtime_limit(tmp_path: Path):
    adapter = SlowAdapter()
    store = CodingSessionStore(tmp_path / "coding.db")
    service = CodingSessionService(store=store, adapters={ProviderName.codex: adapter})
    session = asyncio.run(service.create_session(CodingSessionCreate(provider=ProviderName.codex, cwd=str(tmp_path))))

    async def collect():
        return [
            event
            async for event in service.run_turn(
                session.id,
                "hello",
                limits=CodingTurnLimits(max_runtime_seconds=1, max_provider_events=10),
            )
        ]

    events = asyncio.run(collect())
    turn = store.get_turn(events[0].turn_id)

    assert [event.type for event in events] == ["turn.started", "turn.limit_reached"]
    assert events[-1].payload["reason"] == "runtime_seconds"
    assert events[-1].payload["limit"] == 1
    assert turn is not None
    assert turn.status == "stopped"
    assert service.get_session(session.id).status == "stopped"
    assert adapter.stopped == [(session.id, turn.id)]
