from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

from agent.coding.adapters.base import CodingProviderAdapter
from agent.coding.adapters.claude import ClaudeAdapter
from agent.coding.adapters.codex import CodexAdapter
from agent.coding.checkpoints import CodingCheckpoint
from agent.coding.models import (
    CodingEvent,
    CodingSession,
    CodingSessionCreate,
    CodingTurn,
    CodingTurnLimits,
    ProviderHealth,
    ProviderName,
    utc_now,
)
from agent.coding.storage import CodingSessionStore, CodingTurnConflictError
from agent.coding.workspace import (
    CodingWorkspaceError,
    CodingWorkspaceManager,
    WorkspaceProvision,
    WorkspaceSnapshot,
)


class CodingServiceError(RuntimeError):
    pass


class CodingRunLimitReached(RuntimeError):
    def __init__(self, *, reason: str, limit: int) -> None:
        self.reason = reason
        self.limit = limit
        super().__init__(f"Coding turn reached its {reason} limit ({limit}).")


class CodingSessionService:
    def __init__(
        self,
        store: CodingSessionStore | None = None,
        adapters: dict[ProviderName, CodingProviderAdapter] | None = None,
        workspace_manager: CodingWorkspaceManager | None = None,
    ) -> None:
        self.store = store or CodingSessionStore()
        self.adapters = adapters if adapters is not None else {
            ProviderName.codex: CodexAdapter(),
            ProviderName.claude: ClaudeAdapter(),
        }
        self.workspace_manager = workspace_manager or CodingWorkspaceManager()
        self._checkpoint_git_capability: dict[str, bool] = {}
        self._cleanup_stale_running_state()

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
        adapter = self._adapter(request.provider)
        session = self.store.create_session(request)
        workspace: WorkspaceProvision | None = None
        try:
            workspace = await asyncio.to_thread(
                self.workspace_manager.provision,
                session_id=session.id,
                source_cwd=str(cwd),
                access_mode=request.access_mode,
            )
            session = self.store.set_session_workspace(
                session.id,
                source_cwd=workspace.source_cwd,
                cwd=workspace.cwd,
                workspace_kind=workspace.kind,
                workspace_root=workspace.workspace_root,
                workspace_repository_root=workspace.repository_root,
                workspace_branch=workspace.branch,
                workspace_base_commit=workspace.base_commit,
            )
            provider_session_id = await adapter.start_session(replace(request, cwd=session.cwd))
            if provider_session_id:
                session = self.store.set_provider_session_id(session.id, provider_session_id)
            self.store.record_event(
                session_id=session.id,
                provider=session.provider,
                event_type="session.started",
                message="Coding session started",
                payload={
                    "cwd": session.cwd,
                    "source_cwd": session.source_cwd,
                    "provider_session_id": session.provider_session_id,
                    "workspace": {
                        "kind": session.workspace_kind.value,
                        "root": session.workspace_root,
                        "branch": session.workspace_branch,
                        "base_commit": session.workspace_base_commit,
                    },
                },
            )
        except CodingWorkspaceError as exc:
            self.store.delete_session(session.id)
            raise CodingServiceError(str(exc)) from exc
        except Exception as exc:
            if workspace is not None:
                try:
                    await asyncio.to_thread(
                        self.workspace_manager.release,
                        workspace,
                        force=True,
                        delete_branch=True,
                    )
                except Exception:
                    pass
            self.store.delete_session(session.id)
            raise CodingServiceError("Coding session failed to start.") from exc
        return session

    async def close_session(self, session_id: str, *, discard_changes: bool = False) -> CodingSession:
        session = self.get_session(session_id)
        if session.status == "running" or self.store.get_running_turn(session.id) is not None:
            raise CodingServiceError("Stop the running coding turn before closing this session.")
        if session.status == "closed":
            return session
        provision = WorkspaceProvision(
            source_cwd=session.source_cwd or session.cwd,
            cwd=session.cwd,
            kind=session.workspace_kind,
            workspace_root=session.workspace_root or session.cwd,
            repository_root=session.workspace_repository_root,
            branch=session.workspace_branch,
            base_commit=session.workspace_base_commit,
        )
        try:
            await asyncio.to_thread(
                self.workspace_manager.release,
                provision,
                force=discard_changes,
                delete_branch=False,
            )
        except CodingWorkspaceError as exc:
            raise CodingServiceError(
                "Workspace has uncommitted changes. Review them or explicitly discard changes before closing."
            ) from exc
        session = self.store.set_session_status(session.id, "closed")
        self.store.record_event(
            session_id=session.id,
            provider=session.provider,
            event_type="session.closed",
            message="Coding session closed",
            payload={
                "discarded_uncommitted_changes": discard_changes,
                "preserved_branch": session.workspace_branch,
            },
        )
        self._checkpoint_git_capability.pop(session.id, None)
        return session

    async def run_turn(
        self,
        session_id: str,
        prompt: str,
        *,
        limits: CodingTurnLimits | None = None,
    ) -> AsyncIterator[CodingEvent]:
        session = self.get_session(session_id)
        if session.status == "closed":
            raise CodingServiceError("Coding session is closed. Start a new session for more changes.")
        if session.status == "running":
            raise CodingServiceError("Coding session already has a running turn.")
        adapter = self._adapter(session.provider)
        try:
            turn = self.store.create_turn(session.id, prompt, limits=limits)
        except CodingTurnConflictError as exc:
            raise CodingServiceError(str(exc)) from exc
        final_text = ""
        turn_finished = False
        try:
            checkpoint = await self._start_checkpoint(session, turn)
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.started",
                message="Coding turn started",
                payload={
                    "prompt": prompt,
                    "trace_id": turn.trace_id,
                    "checkpoint_id": checkpoint.id,
                    "limits": {
                        "max_runtime_seconds": turn.max_runtime_seconds,
                        "max_provider_events": turn.max_provider_events,
                    },
                },
            )
            async with asyncio.timeout(turn.max_runtime_seconds):
                async for raw_event in adapter.run_turn(session, prompt, turn.id):
                    current_turn = self.store.get_turn(turn.id)
                    if current_turn is not None and current_turn.status == "stopped":
                        turn_finished = True
                        return
                    if not self.store.claim_provider_event(turn.id):
                        raise CodingRunLimitReached(
                            reason="provider_event_count",
                            limit=turn.max_provider_events,
                        )
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
            current_turn = self.store.get_turn(turn.id)
            if current_turn is not None and current_turn.status == "stopped":
                turn_finished = True
                return
            completed_turn = self.store.finish_running_turn(turn.id, status="completed", final_response=final_text)
            if completed_turn is None:
                turn_finished = True
                return
            self.store.set_session_status(session.id, "idle")
            checkpoint = await self._finalize_checkpoint(session, turn, status="completed")
            turn_finished = True
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.completed",
                message="Coding turn completed",
                payload={
                    "final_response": final_text,
                    "checkpoint": checkpoint.payload(include_patch=False) if checkpoint else None,
                },
            )
        except TimeoutError:
            limit_event = await self._finish_limited_turn(
                session=session,
                turn=turn,
                adapter=adapter,
                reason="runtime_seconds",
                limit=turn.max_runtime_seconds,
            )
            turn_finished = True
            if limit_event is not None:
                yield limit_event
        except CodingRunLimitReached as exc:
            limit_event = await self._finish_limited_turn(
                session=session,
                turn=turn,
                adapter=adapter,
                reason=exc.reason,
                limit=exc.limit,
            )
            turn_finished = True
            if limit_event is not None:
                yield limit_event
        except Exception as exc:
            current_turn = self.store.get_turn(turn.id)
            if current_turn is not None and current_turn.status == "stopped":
                turn_finished = True
                return
            message = str(exc) or exc.__class__.__name__
            errored_turn = self.store.finish_running_turn(turn.id, status="error", error=message)
            if errored_turn is None:
                turn_finished = True
                return
            self.store.set_session_status(session.id, "error")
            checkpoint = await self._finalize_checkpoint(session, turn, status="error")
            turn_finished = True
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.error",
                message=message,
                payload={
                    "error": message,
                    "checkpoint": checkpoint.payload(include_patch=False) if checkpoint else None,
                },
            )
        finally:
            if not turn_finished:
                stopped_turn = self.store.finish_running_turn(
                    turn.id,
                    status="stopped",
                    error="Coding turn cancelled.",
                )
                if stopped_turn is not None:
                    self.store.set_session_status(session.id, "stopped")
                    await self._finalize_checkpoint(session, turn, status="stopped")

    async def stop_turn(self, session_id: str, turn_id: str | None = None) -> None:
        session = self.get_session(session_id)
        active_turn = self.store.get_turn(turn_id) if turn_id else self.store.get_running_turn(session.id)
        if turn_id is not None and active_turn is None:
            raise CodingServiceError("Coding turn is not running.")
        if active_turn and active_turn.session_id != session.id:
            raise CodingServiceError("Coding turn does not belong to session.")
        if active_turn and active_turn.status != "running":
            raise CodingServiceError("Coding turn is not running.")
        active_turn_id = active_turn.id if active_turn else (turn_id or "")
        if active_turn:
            stopped_turn = self.store.finish_running_turn(
                active_turn.id,
                status="stopped",
                error="Coding turn stopped.",
            )
            if stopped_turn is None:
                return
            self.store.set_session_status(session.id, "stopped")
        else:
            self.store.set_session_status(session.id, "stopped")
        stop_error: Exception | None = None
        try:
            await self._adapter(session.provider).stop_turn(session, active_turn_id)
        except Exception as exc:
            stop_error = exc
        if active_turn:
            checkpoint = await self._finalize_checkpoint(session, active_turn, status="stopped")
            payload = {
                "turn_id": active_turn.id,
                "checkpoint": checkpoint.payload(include_patch=False) if checkpoint else None,
            }
            if stop_error is not None:
                payload["provider_stop_error"] = str(stop_error) or stop_error.__class__.__name__
            self.store.record_event(
                session_id=session.id,
                turn_id=active_turn.id,
                provider=session.provider,
                event_type="turn.stopped",
                message="Coding turn stopped",
                payload=payload,
            )
        if stop_error is not None:
            raise stop_error

    def list_events(self, session_id: str, *, after_sequence: int = 0) -> list[CodingEvent]:
        self.get_session(session_id)
        return self.store.list_events(session_id, after_sequence=after_sequence)

    def list_checkpoints(self, session_id: str) -> list[CodingCheckpoint]:
        self.get_session(session_id)
        return self.store.list_checkpoints(session_id)

    def get_checkpoint(self, session_id: str, checkpoint_id: str) -> CodingCheckpoint:
        self.get_session(session_id)
        checkpoint = self.store.get_checkpoint(checkpoint_id)
        if checkpoint is None or checkpoint.session_id != session_id:
            raise CodingServiceError("Coding checkpoint not found.")
        return checkpoint

    async def _finish_limited_turn(
        self,
        *,
        session: CodingSession,
        turn: CodingTurn,
        adapter: CodingProviderAdapter,
        reason: str,
        limit: int,
    ) -> CodingEvent | None:
        message = f"Coding turn stopped after reaching its {reason} limit ({limit})."
        stopped_turn = self.store.finish_running_turn(turn.id, status="stopped", error=message)
        if stopped_turn is None:
            return None
        self.store.set_session_status(session.id, "stopped")

        stop_error = ""
        try:
            await asyncio.wait_for(adapter.stop_turn(session, turn.id), timeout=5.0)
        except Exception as exc:
            stop_error = str(exc) or exc.__class__.__name__

        payload = {
            "reason": reason,
            "limit": limit,
            "provider_event_count": stopped_turn.provider_event_count,
        }
        if stop_error:
            payload["provider_stop_error"] = stop_error
        checkpoint = await self._finalize_checkpoint(session, turn, status="stopped")
        payload["checkpoint"] = checkpoint.payload(include_patch=False) if checkpoint else None
        return self.store.record_event(
            session_id=session.id,
            turn_id=turn.id,
            provider=session.provider,
            event_type="turn.limit_reached",
            message=message,
            payload=payload,
        )

    async def _start_checkpoint(self, session: CodingSession, turn: CodingTurn) -> CodingCheckpoint:
        before = await self._capture_snapshot(session)
        return self.store.create_checkpoint(
            session_id=session.id,
            turn_id=turn.id,
            before=before,
        )

    async def _finalize_checkpoint(
        self,
        session: CodingSession,
        turn: CodingTurn,
        *,
        status: str,
    ) -> CodingCheckpoint | None:
        existing = self.store.get_checkpoint_for_turn(turn.id)
        if existing is None or existing.finalized_at is not None:
            return existing
        after = await self._capture_snapshot(session)
        return self.store.finish_checkpoint(turn.id, status=status, after=after)

    async def _capture_snapshot(self, session: CodingSession) -> WorkspaceSnapshot:
        git_available = self._checkpoint_git_capability.get(session.id)
        if git_available is None:
            git_available = bool(session.workspace_repository_root) or await asyncio.to_thread(
                self.workspace_manager.is_git_workspace,
                session.workspace_root or session.cwd,
            )
            self._checkpoint_git_capability[session.id] = git_available
        if not git_available:
            return WorkspaceSnapshot(
                captured_at=utc_now(),
                capture_error="Git checkpoint unavailable because this project is not a Git repository.",
            )
        try:
            return await asyncio.to_thread(
                self.workspace_manager.capture_snapshot,
                session.workspace_root or session.cwd,
            )
        except Exception as exc:
            return WorkspaceSnapshot(
                captured_at=utc_now(),
                capture_error=str(exc) or exc.__class__.__name__,
            )

    def _adapter(self, provider: ProviderName) -> CodingProviderAdapter:
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise CodingServiceError("Provider is not configured.")
        return adapter

    def _cleanup_stale_running_state(self) -> None:
        stale_session_ids = set()
        for turn in self.store.list_running_turns():
            self.store.finish_turn(turn.id, status="stopped", error="Coding turn interrupted by restart.")
            self.store.finish_checkpoint(
                turn.id,
                status="stopped",
                after=WorkspaceSnapshot(
                    captured_at=utc_now(),
                    capture_error="Backend restarted before the after-turn checkpoint could be captured.",
                ),
            )
            stale_session_ids.add(turn.session_id)
        for session in self.store.list_sessions():
            if session.status == "running" or session.id in stale_session_ids:
                self.store.set_session_status(session.id, "stopped")
