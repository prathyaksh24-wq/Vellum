"""Capture helpers that turn LangChain message usage into ledger rows."""

from __future__ import annotations

import logging
from typing import Any

from agent.telemetry.usage_ledger import UsageLedger

logger = logging.getLogger(__name__)


def _extract_usage(obj: Any) -> dict[str, Any] | None:
    """Pull a usage_metadata dict off an AIMessage-like object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        usage = obj.get("usage_metadata")
    else:
        usage = getattr(obj, "usage_metadata", None)
    if not usage:
        return None
    return dict(usage)


def _record_one(
    *,
    ledger: UsageLedger,
    usage: dict[str, Any],
    thread_id: str,
    fallback_model: str,
    source: str,
) -> None:
    in_tokens = int(usage.get("input_tokens") or 0)
    out_tokens = int(usage.get("output_tokens") or 0)
    if in_tokens == 0 and out_tokens == 0:
        return
    model = str(usage.get("model_name") or fallback_model)
    try:
        ledger.record(
            thread_id=thread_id,
            model=model,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            source=source,
        )
    except Exception as exc:  # never block the chat path
        logger.warning("ledger write failed: %s", exc)


def capture_from_invoke_result(
    *,
    ledger: UsageLedger,
    result: dict[str, Any],
    thread_id: str,
    fallback_model: str,
    source: str,
) -> None:
    """Scan a LangGraph `ainvoke` result for AIMessages with usage_metadata."""
    messages = result.get("messages", []) if isinstance(result, dict) else []
    for msg in messages:
        usage = _extract_usage(msg)
        if usage:
            _record_one(
                ledger=ledger, usage=usage, thread_id=thread_id,
                fallback_model=fallback_model, source=source,
            )


def capture_from_stream_event(
    *,
    ledger: UsageLedger,
    event: dict[str, Any],
    thread_id: str,
    fallback_model: str,
    source: str,
) -> None:
    """Handle a single `astream_events` event; only fires on chat-model-end."""
    if event.get("event") != "on_chat_model_end":
        return
    # LangGraph exposes the routed facade and its nested provider run. They
    # carry the same usage payload, so recording both silently doubles every
    # observability total. Synthetic/legacy events may omit a name.
    event_name = str(event.get("name") or "").strip()
    if event_name and event_name != "RoutedChatModel":
        return
    output = event.get("data", {}).get("output")
    usage = _extract_usage(output)
    if usage:
        _record_one(
            ledger=ledger, usage=usage, thread_id=thread_id,
            fallback_model=fallback_model, source=source,
        )
