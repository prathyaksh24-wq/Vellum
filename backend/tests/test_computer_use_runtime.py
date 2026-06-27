from agent.computer_use_runtime import ComputerUseRuntime


def test_computer_use_runtime_persists_mode_state(tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )

    enabled = runtime.enable(source="ui", thread_id="thread-1", task="check a page")

    assert enabled["enabled"] is True
    assert enabled["status"] == "ready"
    assert enabled["thread_id"] == "thread-1"
    assert enabled["task"] == "check a page"

    restored = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )

    assert restored.status()["enabled"] is True
    assert restored.status()["status"] == "ready"

    disabled = restored.disable(source="voice")

    assert disabled["enabled"] is False
    assert disabled["status"] == "disabled"


def test_computer_use_runtime_records_events_to_jsonl(tmp_path):
    runtime = ComputerUseRuntime(
        state_path=tmp_path / "mode.json",
        event_log_path=tmp_path / "events.jsonl",
    )

    event = runtime.record_event(
        "tool_start",
        "computer_use desktop click started",
        tool="computer_use",
        data={"mode": "desktop", "action": "click"},
    )

    assert event["kind"] == "tool_start"
    assert event["tool"] == "computer_use"
    assert runtime.recent_events()[-1]["data"]["action"] == "click"
    assert "tool_start" in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
