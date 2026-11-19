import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.contracts.observability import RunTrace, ThreadContext
from agent.observability import ObservabilityService
from agent.telemetry.turn_audit import summarize_turns


def _event(event_type: str, response_id: str = "resp-1", thread_id: str = "thread-1", **extra):
    return {"type": event_type, "response_id": response_id, "thread_id": thread_id,
            "created_at": "2026-07-17T10:00:00+00:00", **extra}


def _activity(kind: str, name: str = "", status: str = "in_progress", **extra):
    return _event("agent.activity", activity={"type": kind, "name": name, "label": kind, "status": status, **extra})


CONTEXT = {"context": {"window": 32000, "used": 9100, "limit": 27000, "output_reserved": 3400, "margin": 1600,
                       "layers": {"instructions": 4000, "tool_schemas": 3000, "personal_memory": 600,
                                  "recent_conversation": 1500, "secret_layer": 7},
                       "compacted": False, "removed_messages": 0}}


def test_context_window_is_kept_as_numbers_per_conversation(tmp_path: Path) -> None:
    service = ObservabilityService(tmp_path / "obs.db")
    service.capture(_event("response.created"))
    service.capture(_activity("context_ready", "conversation_context", "completed",
                              metadata={**CONTEXT, "prompt": "private prompt text"}))

    view = ThreadContext.model_validate(service.thread_context("thread-1"))
    assert view.latest.context_window == 32000
    assert view.latest.input_used == 9100
    assert view.latest.layers["instructions"] == 4000
    assert "secret_layer" not in view.latest.layers
    assert "private prompt text" not in repr(service.raw_event_rows())
    summary = service.context_summary(days=None)
    assert summary["turns"] == 1 and summary["latest"]["input_limit"] == 27000


def test_run_trace_pairs_spans_and_nests_tools_under_agents(tmp_path: Path) -> None:
    service = ObservabilityService(tmp_path / "obs.db")
    for payload in [
        _event("response.created"),
        _activity("thinking_started"),
        _activity("sub_agent_started", "MusicAgent"),
        _activity("tool_call_started", "spotify_playback"),
        _activity("tool_call_completed", "spotify_playback", "completed"),
        _activity("source_discovered", status="completed"),
        _activity("source_discovered", status="completed"),
        _activity("sub_agent_completed", "MusicAgent", "completed"),
        _activity("sub_agent_completed", "MusicAgent", "completed"),
        _activity("final_answer_started"),
        _activity("final_answer_completed", status="completed"),
        _event("response.completed", response={"tools": ["spotify_playback"], "sources": []}),
    ]:
        service.capture(payload)

    trace = RunTrace.model_validate(service.run_trace("resp-1"))
    kinds = [span.kind for span in trace.spans]
    assert kinds == ["thinking", "agent", "tool", "source", "answer"]
    agent, tool, source = trace.spans[1], trace.spans[2], trace.spans[3]
    assert tool.parent == agent.id and source.parent == agent.id
    assert source.count == 2 and source.label == "Found 2 sources"
    assert all(span.status == "completed" for span in trace.spans)
    assert trace.precise is True
    assert trace.stats.tool_calls == 1 and trace.stats.agents == 1
    assert service.run_trace("missing") is None


def test_turn_summary_reports_latency_outcomes_and_skips_fixture_models(tmp_path: Path) -> None:
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    log = tmp_path / "audit.jsonl"
    rows = [
        {"timestamp": (now - timedelta(days=1)).isoformat(), "model": "ollama/gemma4:12b", "provider": "ollama",
         "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost_usd": 0,
         "latency_first_token_ms": 500, "latency_total_ms": 900, "tools_called": ["web_search", "web_search"],
         "privacy_class": "GREEN", "outcome": "completed"},
        {"timestamp": (now - timedelta(days=2)).isoformat(), "model": "ollama/gemma4:12b", "provider": "ollama",
         "prompt_tokens": 50, "completion_tokens": 0, "total_tokens": 50, "cost_usd": 0,
         "latency_first_token_ms": None, "latency_total_ms": 3000, "tools_called": [],
         "privacy_class": "YELLOW", "outcome": "failed"},
        {"timestamp": (now - timedelta(days=9)).isoformat(), "model": "ollama/gemma4:12b", "provider": "ollama",
         "total_tokens": 70, "outcome": "completed"},
        {"timestamp": (now - timedelta(days=1)).isoformat(), "model": "test/model", "outcome": "completed"},
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\nnot json\n", encoding="utf-8")

    summary = summarize_turns(log, days=7, now=now)
    assert summary["turns"] == 2 and summary["previous_turns"] == 1
    assert summary["tokens"] == 170 and summary["previous_tokens"] == 70
    assert summary["outcomes"] == {"completed": 1, "failed": 1}
    assert summary["success_rate"] == 0.5
    assert summary["latency"]["first_token_p50_ms"] == 500
    assert summary["tools"] == [{"name": "web_search", "turns": 1}]
    assert summary["privacy"] == {"GREEN": 1, "YELLOW": 1}
    assert summary["models"][0]["turns"] == 2
    assert summarize_turns(tmp_path / "missing.jsonl", days=7, now=now)["turns"] == 0


def test_context_report_survives_activity_redaction_into_the_store(tmp_path: Path) -> None:
    from agent.api import _context_meter
    from agent.contracts.chat_activity import activity_detail

    report = {"context_budget": {"context_window": 32768, "estimated_input_tokens": 12000, "input_limit": 27000,
                                 "output_reserved": 4096, "safety_margin": 1639, "compacted": True, "removed_messages": 3,
                                 "layers": {"instructions": 5000, "tool_schemas": 4000, "personal_memory": 800,
                                            "retrieved_history": 0, "compacted_history": 700, "recent_conversation": 1500}}}
    metadata = activity_detail(_context_meter(report))  # what the SSE activity carries
    service = ObservabilityService(tmp_path / "obs.db")
    service.capture(_event("response.created"))
    service.capture(_activity("context_ready", "conversation_context", "completed", metadata=metadata))

    latest = service.thread_context("thread-1")["latest"]
    assert latest["input_used"] == 12000 and latest["context_window"] == 32768
    assert latest["layers"]["tool_schemas"] == 4000 and latest["compacted"] is True
    assert _context_meter({"context_budget": {}}) is None and _context_meter(None) is None
