"""Foreground first: background model work waits while the user is chatting.

On a single local GPU, Ollama runs one request at a time. Background learning
and memory sync each hold the model for tens of seconds, so a chat message
sent meanwhile queued behind them (and could time out). Chat requests mark the
user as active; background jobs check ``user_is_active()`` before each unit of
model work and pause until the user has been quiet for a while.
"""
from __future__ import annotations

import time

QUIET_SECONDS = 120.0
_last_active = -1e12


def mark_user_active() -> None:
    global _last_active
    _last_active = time.monotonic()


def user_is_active(quiet_seconds: float = QUIET_SECONDS) -> bool:
    return time.monotonic() - _last_active < quiet_seconds
