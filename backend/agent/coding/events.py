from __future__ import annotations

import json
from typing import Any

from agent.coding.models import CodingEvent


EVENT_NAME_BY_TYPE = {
    "session.started": "session",
    "session.resumed": "session",
    "turn.started": "turn",
    "assistant.delta": "assistant_delta",
    "assistant.final": "assistant_final",
    "tool.started": "tool",
    "tool.completed": "tool",
    "file.changed": "file_change",
    "turn.completed": "done",
    "turn.error": "error",
}


def event_name(event_type: str) -> str:
    return EVENT_NAME_BY_TYPE.get(event_type, "coding")


def event_payload(event: CodingEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "session_id": event.session_id,
        "turn_id": event.turn_id,
        "provider": event.provider.value,
        "type": event.type,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def sse(event: CodingEvent) -> str:
    return f"event: {event_name(event.type)}\ndata: {json.dumps(event_payload(event))}\n\n"
