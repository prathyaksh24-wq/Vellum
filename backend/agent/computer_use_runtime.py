"""Runtime state and event feed for explicit computer-use mode."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.config import get_settings


class ComputerUseRuntime:
    """File-backed computer-use mode state with lightweight event broadcast."""

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        event_log_path: Path | None = None,
        recent_limit: int = 100,
    ) -> None:
        base_dir = get_settings().computer_use_screenshot_dir.parent
        self.state_path = state_path or base_dir / "mode.json"
        self.event_log_path = event_log_path or base_dir / "events.jsonl"
        self.recent_limit = recent_limit
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        if not state:
            state = self._default_state()
        return state

    def is_enabled(self) -> bool:
        return bool(self.status().get("enabled"))

    def enable(self, *, source: str = "ui", thread_id: str | None = None, task: str | None = None) -> dict[str, Any]:
        now = _utc_now()
        state = self.status()
        state.update(
            {
                "enabled": True,
                "paused": False,
                "status": "ready",
                "source": source,
                "thread_id": thread_id,
                "task": task,
                "enabled_at": state.get("enabled_at") or now,
                "disabled_at": None,
                "updated_at": now,
            }
        )
        self._save_state(state)
        self.record_event(
            "mode_enabled",
            "Computer use mode enabled.",
            data={"source": source, "thread_id": thread_id, "task": task},
            state=state,
        )
        return state

    def disable(self, *, source: str = "ui", reason: str | None = None) -> dict[str, Any]:
        now = _utc_now()
        state = self.status()
        state.update(
            {
                "enabled": False,
                "paused": False,
                "status": "disabled",
                "source": source,
                "disabled_at": now,
                "updated_at": now,
            }
        )
        self._save_state(state)
        self.record_event(
            "mode_disabled",
            "Computer use mode disabled.",
            data={"source": source, "reason": reason},
            state=state,
        )
        return state

    def pause(self, *, source: str = "ui") -> dict[str, Any]:
        state = self.status()
        if not state.get("enabled"):
            return state
        state.update({"paused": True, "status": "paused", "source": source, "updated_at": _utc_now()})
        self._save_state(state)
        self.record_event("mode_paused", "Computer use mode paused.", data={"source": source}, state=state)
        return state

    def resume(self, *, source: str = "ui") -> dict[str, Any]:
        state = self.status()
        if not state.get("enabled"):
            return state
        state.update({"paused": False, "status": "ready", "source": source, "updated_at": _utc_now()})
        self._save_state(state)
        self.record_event("mode_resumed", "Computer use mode resumed.", data={"source": source}, state=state)
        return state

    def record_event(
        self,
        kind: str,
        message: str,
        *,
        tool: str | None = None,
        data: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": uuid4().hex,
            "ts": _utc_now(),
            "kind": kind,
            "message": message,
            "tool": tool,
            "status": (state or self.status()).get("status", "disabled"),
            "data": data or {},
        }
        self._recent.append(event)
        self._append_event(event)
        self._broadcast(event)
        return event

    def recent_events(self) -> list[dict[str, Any]]:
        if self._recent:
            return list(self._recent)
        if not self.event_log_path.exists():
            return []
        events: deque[dict[str, Any]] = deque(maxlen=self.recent_limit)
        try:
            for line in self.event_log_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            return []
        self._recent.extend(events)
        return list(events)

    async def subscribe(self):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    def _default_state(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "paused": False,
            "status": "disabled",
            "thread_id": None,
            "task": None,
            "source": None,
            "enabled_at": None,
            "disabled_at": None,
            "updated_at": _utc_now(),
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    def _append_event(self, event: dict[str, Any]) -> None:
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _broadcast(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except RuntimeError:
                self._subscribers.discard(queue)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


computer_use_runtime = ComputerUseRuntime()
