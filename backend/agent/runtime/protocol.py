from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


MESSAGE_TYPES = frozenset(
    {
        "run", "progress", "heartbeat", "tool_request", "tool_result",
        "model_request", "model_result", "message", "memory_proposal",
        "result", "error", "cancel",
    }
)


class ProtocolMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    type: Literal[
        "run", "progress", "heartbeat", "tool_request", "tool_result",
        "model_request", "model_result", "message", "memory_proposal",
        "result", "error", "cancel",
    ]
    run_id: str
    task_id: str
    payload: dict[str, Any]


def parse_message(value: str | bytes | dict[str, Any]) -> ProtocolMessage:
    if isinstance(value, (str, bytes)):
        return ProtocolMessage.model_validate_json(value)
    return ProtocolMessage.model_validate(value)


def validate_envelope(message: ProtocolMessage, *, run_id: str, task_id: str) -> ProtocolMessage:
    if message.run_id != run_id or message.task_id != task_id:
        raise ValueError("message identity mismatch")
    return message


def encode_message(message_type: str, run_id: str, task_id: str, payload: dict[str, Any]) -> str:
    return ProtocolMessage(version=1, type=message_type, run_id=run_id, task_id=task_id, payload=payload).model_dump_json()
