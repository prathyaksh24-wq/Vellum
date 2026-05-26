"""Durable computer-use session lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from agent.computer_use_runtime import ComputerUseRuntime, computer_use_runtime


class ComputerUseSessionError(RuntimeError):
    """Raised when computer-use session lifecycle cannot proceed."""


class OverlayController(Protocol):
    def start(self) -> str:
        """Show the activity overlay."""

    def stop(self) -> str:
        """Hide the activity overlay."""

    def status(self) -> dict[str, object]:
        """Return overlay health/status."""


class InstructionRouter(Protocol):
    def run_instruction(self, instruction: str, *, session_id: str) -> dict[str, object]:
        """Execute or schedule a computer-use instruction."""


@dataclass
class NoopOverlay:
    """Development fallback used when no desktop shell is attached."""

    active: bool = False

    def start(self) -> str:
        self.active = True
        return "overlay unavailable: using backend session state only"

    def stop(self) -> str:
        self.active = False
        return "overlay stopped"

    def status(self) -> dict[str, object]:
        return {"ready": self.active, "fallback": True}


class NoopInstructionRouter:
    """Records the instruction and lets the existing agent/tool loop handle it."""

    def run_instruction(self, instruction: str, *, session_id: str) -> dict[str, object]:
        return {
            "status": "queued",
            "session_id": session_id,
            "steps": [{"type": "action", "message": f"Queued instruction: {instruction}"}],
        }


class ComputerUseSession:
    """Coordinates explicit computer-use mode, overlay state, and task events."""

    def __init__(
        self,
        *,
        runtime: ComputerUseRuntime = computer_use_runtime,
        overlay: OverlayController | None = None,
        router: InstructionRouter | None = None,
        max_steps: int = 30,
    ) -> None:
        self.runtime = runtime
        self.overlay = overlay or NoopOverlay()
        self.router = router or NoopInstructionRouter()
        self.max_steps = max_steps
        current = self.runtime.status().get("session_id")
        self.session_id: str | None = str(current) if current else None
        self.stop_requested = False

    def status(self) -> dict[str, Any]:
        state = self.runtime.status()
        if self.session_id and not state.get("session_id"):
            state["session_id"] = self.session_id
        state["overlay"] = self.overlay.status()
        return state

    def start(self, *, source: str = "ui", thread_id: str | None = None, task: str | None = None) -> dict[str, Any]:
        self.stop_requested = False
        session_id = self.session_id or uuid4().hex
        try:
            overlay_message = self.overlay.start()
        except Exception as exc:
            self.runtime.record_event(
                "session_start_failed",
                f"Computer-use session failed to start: {exc}",
                tool="computer_use_session",
                data={"source": source, "thread_id": thread_id, "task": task},
            )
            raise ComputerUseSessionError(str(exc)) from exc

        self.session_id = session_id
        state = self.runtime.enable(source=source, thread_id=thread_id, task=task)
        state.update({"session_id": session_id, "overlay": self.overlay.status()})
        self.runtime._save_state(state)
        self.runtime.record_event(
            "session_started",
            "Computer-use session started.",
            tool="computer_use_session",
            data={
                "source": source,
                "thread_id": thread_id,
                "task": task,
                "session_id": session_id,
                "overlay": overlay_message,
            },
            state=state,
        )
        return state

    def stop(self, *, source: str = "ui", reason: str | None = None) -> dict[str, Any]:
        self.stop_requested = True
        overlay_message = self.overlay.stop()
        state = self.runtime.disable(source=source, reason=reason)
        state.update({"session_id": self.session_id, "overlay": self.overlay.status()})
        self.runtime._save_state(state)
        self.runtime.record_event(
            "session_stopped",
            "Computer-use session stopped.",
            tool="computer_use_session",
            data={"source": source, "reason": reason, "session_id": self.session_id, "overlay": overlay_message},
            state=state,
        )
        return state

    def pause(self, *, source: str = "ui") -> dict[str, Any]:
        return self.runtime.pause(source=source)

    def resume(self, *, source: str = "ui") -> dict[str, Any]:
        return self.runtime.resume(source=source)

    def submit_task(self, instruction: str, *, source: str = "text", thread_id: str | None = None) -> dict[str, object]:
        clean = " ".join(instruction.split())
        if not clean:
            raise ComputerUseSessionError("Computer-use task cannot be empty.")
        state = self.runtime.status()
        if not state.get("enabled") or state.get("paused"):
            raise ComputerUseSessionError("Computer use is not enabled.")
        session_id = str(state.get("session_id") or self.session_id or uuid4().hex)
        self.session_id = session_id
        self.runtime.record_event(
            "task_started",
            f"Computer-use task started: {clean}",
            tool="computer_use_session",
            data={"source": source, "thread_id": thread_id, "session_id": session_id, "instruction": clean},
        )
        result = self.router.run_instruction(clean, session_id=session_id)
        for step in list(result.get("steps", []))[: self.max_steps]:
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("type") or "action")
            kind = "observation" if step_type == "screenshot" else "action_finished"
            self.runtime.record_event(
                kind,
                str(step.get("message") or step_type),
                tool="computer_use_session",
                data={"session_id": session_id, "step": step},
            )
        self.runtime.record_event(
            "task_finished",
            "Computer-use task finished.",
            tool="computer_use_session",
            data={"session_id": session_id, "result": result},
        )
        return result


computer_use_session = ComputerUseSession()
