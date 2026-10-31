"""Task-local projection into chat activity; no second execution or storage owner."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from agent.contracts.chat_activity import activity_detail

_SINK: ContextVar[Callable | None] = ContextVar('chat_activity_sink', default=None)
_PARENT: ContextVar[str] = ContextVar('chat_activity_parent', default='')


@contextmanager
def observe_activity(sink):
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


@contextmanager
def activity_parent(parent_id):
    token = _PARENT.set(parent_id)
    try:
        yield
    finally:
        _PARENT.reset(token)


def emit_activity(kind, name, *, item_id='', label='', status='in_progress', detail='', source=None, **metadata):
    sink = _SINK.get()
    if sink is None:
        return
    sink(dict(id=item_id or str(uuid4()), type=kind, name=name, label=label or name,
              status=status, detail=str(activity_detail(detail)),
              source=activity_detail(source) if source is not None else None,
              metadata=activity_detail({'parent_id':_PARENT.get(), **metadata}),
              at=datetime.now(timezone.utc).isoformat(timespec='milliseconds')))
