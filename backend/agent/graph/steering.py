"""Follow-up steering for a running turn.

A follow-up sent while a turn runs is held here instead of interrupting it, as
Codex's ``turn/steer`` does. The model node drains the inbox before its next
model call, so the message joins the same turn as a user message and the run
continues with it. A message the run never reached (the turn ended first) is
reclaimed by the client and sent as a normal turn, so nothing is lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
import time
from uuid import uuid4


STEER_PREFIX = "[Follow-up sent while you were working. Take it into account and continue.]\n"


@dataclass
class SteerMessage:
    id: str
    text: str
    created_at: float = field(default_factory=time.time)


class SteeringInbox:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[str, int] = {}
        self._pending: dict[str, list[SteerMessage]] = {}

    def begin(self, thread_id: str) -> None:
        with self._lock:
            self._active[thread_id] = self._active.get(thread_id, 0) + 1

    def end(self, thread_id: str) -> None:
        with self._lock:
            count = self._active.get(thread_id, 0) - 1
            if count > 0:
                self._active[thread_id] = count
            else:
                self._active.pop(thread_id, None)

    def is_active(self, thread_id: str) -> bool:
        with self._lock:
            return self._active.get(thread_id, 0) > 0

    def submit(self, thread_id: str, text: str, message_id: str = "") -> SteerMessage | None:
        """Hold a follow-up for the running turn; None when no turn is running."""
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("A steer message cannot be empty.")
        with self._lock:
            if self._active.get(thread_id, 0) <= 0:
                return None
            message = SteerMessage(id=message_id or uuid4().hex, text=clean)
            self._pending.setdefault(thread_id, []).append(message)
            return message

    def drain(self, thread_id: str) -> list[SteerMessage]:
        with self._lock:
            return self._pending.pop(thread_id, [])

    def reclaim(self, thread_id: str, message_id: str) -> SteerMessage | None:
        """Take back a follow-up the turn never reached."""
        with self._lock:
            pending = self._pending.get(thread_id, [])
            for index, message in enumerate(pending):
                if message.id == message_id:
                    pending.pop(index)
                    if not pending:
                        self._pending.pop(thread_id, None)
                    return message
        return None


_INBOX = SteeringInbox()


def get_steering_inbox() -> SteeringInbox:
    return _INBOX
