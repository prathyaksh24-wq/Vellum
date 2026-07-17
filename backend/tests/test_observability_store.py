from pathlib import Path

from agent.observability import ObservabilityService


def _payload(event_type: str, **extra):
    return {
        "type": event_type,
        "response_id": "resp-1",
        "thread_id": "thread-1",
        "created_at": "2026-07-17T10:00:00+00:00",
        **extra,
    }


def test_run_lifecycle_is_durable_and_summarized(tmp_path: Path) -> None:
    service = ObservabilityService(tmp_path / "observability.db")
    service.capture(_payload("response.created"))
    service.capture(_payload("agent.activity", activity={
        "type": "tool_call_started",
        "label": "Using web_search...",
        "name": "web_search",
        "status": "in_progress",
        "detail": "private query text",
    }))
    service.capture(_payload("response.completed", response={
        "status": "completed",
        "output_text": "private answer text",
        "tools": ["web_search"],
        "sources": [{"url": "https://example.com/private"}],
    }))

    summary = service.summary(days=None)
    assert summary["total"] == 1
    assert summary["completed"] == 1
    assert summary["active"] == 0
    assert summary["success_rate"] == 1
    run = service.recent_runs(limit=1)[0]
    assert run["tool_count"] == 1
    assert run["source_count"] == 1


def test_persisted_events_exclude_content_and_arguments(tmp_path: Path) -> None:
    service = ObservabilityService(tmp_path / "observability.db")
    service.capture(_payload("response.created"))
    service.capture(_payload("agent.activity", activity={
        "type": "tool_call_delta",
        "label": "Using shell...",
        "name": "shell",
        "status": "in_progress",
        "detail": "password=hunter2 C:/Users/Private/file.txt",
        "metadata": {"arguments": {"secret": "hunter2"}},
    }))

    serialized = repr(service.raw_event_rows())
    assert "hunter2" not in serialized
    assert "C:/Users" not in serialized
    assert "arguments" not in serialized


def test_events_can_resume_from_last_event_id(tmp_path: Path) -> None:
    service = ObservabilityService(tmp_path / "observability.db")
    first = service.capture(_payload("response.created"))
    second = service.capture(_payload("agent.activity", activity={
        "type": "thinking_started",
        "label": "Thinking...",
    }))

    events = service.events_since(first["id"])
    assert [item["id"] for item in events] == [second["id"]]
    assert events[0]["type"] == "thinking_started"
