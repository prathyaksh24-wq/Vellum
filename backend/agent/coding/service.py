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
        self.adapters = adapters if adapters is not None else {
            ProviderName.codex: CodexAdapter(),
            ProviderName.claude: ClaudeAdapter(),
        }
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
        try:
            provider_session_id = await adapter.start_session(request)
            if provider_session_id:
                session = self.store.set_provider_session_id(session.id, provider_session_id)
            self.store.record_event(
                session_id=session.id,
                provider=session.provider,
                event_type="session.started",
                message="Coding session started",
                payload={"cwd": session.cwd, "provider_session_id": session.provider_session_id},
            )
        except Exception:
            self.store.delete_session(session.id)
            raise CodingServiceError("Coding session failed to start.") from None
        return session

    async def run_turn(self, session_id: str, prompt: str) -> AsyncIterator[CodingEvent]:
        session = self.get_session(session_id)
        if session.status == "running":
            raise CodingServiceError("Coding session already has a running turn.")
        adapter = self._adapter(session.provider)
        turn = self.store.create_turn(session.id, prompt)
        self.store.set_session_status(session.id, "running")
        final_text = ""
        turn_finished = False
        try:
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.started",
                message="Coding turn started",
                payload={"prompt": prompt},
            )
            async for raw_event in adapter.run_turn(session, prompt, turn.id):
                current_turn = self.store.get_turn(turn.id)
                if current_turn is not None and current_turn.status == "stopped":
                    turn_finished = True
                    return
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
            turn_finished = True
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.completed",
                message="Coding turn completed",
                payload={"final_response": final_text},
            )
        except (CodingAdapterError, Exception) as exc:
            current_turn = self.store.get_turn(turn.id)
            if current_turn is not None and current_turn.status == "stopped":
                turn_finished = True
                return
            message = str(exc) or exc.__class__.__name__
            self.store.complete_turn(turn.id, error=message)
            self.store.set_session_status(session.id, "error")
            turn_finished = True
            yield self.store.record_event(
                session_id=session.id,
                turn_id=turn.id,
                provider=session.provider,
                event_type="turn.error",
                message=message,
                payload={"error": message},
            )
        finally:
            if not turn_finished:
                self.store.finish_turn(turn.id, status="stopped", error="Coding turn cancelled.")
                self.store.set_session_status(session.id, "stopped")

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
        await self._adapter(session.provider).stop_turn(session, active_turn_id)
        if active_turn:
            self.store.finish_turn(active_turn.id, status="stopped", error="Coding turn stopped.")
            self.store.record_event(
                session_id=session.id,
                turn_id=active_turn.id,
                provider=session.provider,
                event_type="turn.stopped",
                message="Coding turn stopped",
                payload={"turn_id": active_turn.id},
            )
        self.store.set_session_status(session.id, "stopped")

    def list_events(self, session_id: str) -> list[CodingEvent]:
        self.get_session(session_id)
        return self.store.list_events(session_id)

    def _adapter(self, provider: ProviderName) -> CodingProviderAdapter:
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise CodingServiceError("Provider is not configured.")
        return adapter

    def _cleanup_stale_running_state(self) -> None:
        stale_session_ids = set()
        for turn in self.store.list_running_turns():
            self.store.finish_turn(turn.id, status="stopped", error="Coding turn interrupted by restart.")
            stale_session_ids.add(turn.session_id)
        for session in self.store.list_sessions():
            if session.status == "running" or session.id in stale_session_ids:
                self.store.set_session_status(session.id, "stopped")
