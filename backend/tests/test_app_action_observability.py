import json

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.observability import (
    OBSERVABILITY_ACTION_IDS,
    OBSERVABILITY_OPEN_ACTION_ID,
    OBSERVABILITY_REFRESH_ACTION_ID,
    OBSERVABILITY_STATUS_ACTION_ID,
    OBSERVABILITY_STREAM_SET_ACTION_ID,
    ObservabilityActionService,
)
from agent.app_actions.runtime import AppActionRuntime


def _snapshot(_period: str) -> dict:
    return {
        "schema_version": 1,
        "source": "vellum-native",
        "generated_at": "2026-09-15T00:00:00Z",
        "period": "7d",
        "freshness": {"state": "live", "updated_at": "2026-09-15T00:00:00Z"},
        "usage": {
            "input_tokens": 12,
            "output_tokens": 8,
            "total_tokens": 20,
            "cost_usd": 0.01,
            "calls": 1,
            "sessions": 1,
            "state": "ready",
            "models": [{"model": "test-model", "input_tokens": 12, "output_tokens": 8, "cost_usd": 0.01, "calls": 1}],
            "daily": [{"day": "2026-09-15", "input_tokens": 12, "output_tokens": 8, "cost_usd": 0.01}],
            "recent": [{
                "id": 1,
                "ts": "2026-09-15T00:00:00Z",
                "thread_id": "chat-1",
                "model": "test-model",
                "input_tokens": 12,
                "output_tokens": 8,
                "cost_usd": 0.01,
                "source": "chat",
            }],
        },
        "runs": {
            "total": 1,
            "completed": 0,
            "failed": 0,
            "active": 1,
            "success_rate": 0.0,
            "active_run": {
                "response_id": "resp-1",
                "thread_id": "chat-1",
                "status": "in_progress",
                "started_at": "2026-09-15T00:00:00Z",
                "completed_at": None,
                "event_count": 2,
                "tool_count": 1,
                "source_count": 0,
            },
        },
        "recent_runs": [{
            "response_id": "resp-1",
            "thread_id": "chat-1",
            "status": "in_progress",
            "started_at": "2026-09-15T00:00:00Z",
            "completed_at": None,
            "event_count": 2,
            "tool_count": 1,
            "source_count": 0,
        }],
    }


def _runtime(provider=_snapshot) -> AppActionRuntime:
    service = ObservabilityActionService(provider)
    return AppActionRuntime(observability_handler=service.execute)


def _dispatch(runtime: AppActionRuntime, action_id: str, arguments: dict | None = None):
    return runtime.dispatch(
        AppActionRequest(action_id=action_id, arguments=arguments or {}),
        AppActionContext(source="nlp", invocation_conversation_id="chat-1"),
    )


def test_catalog_exposes_typed_observability_actions_only_when_owner_is_wired() -> None:
    wired = {definition.id: definition for definition in _runtime().catalog().actions}
    unwired = {definition.id for definition in AppActionRuntime().catalog().actions}

    assert OBSERVABILITY_ACTION_IDS <= wired.keys()
    assert OBSERVABILITY_ACTION_IDS.isdisjoint(unwired)
    assert wired[OBSERVABILITY_OPEN_ACTION_ID].executor_location == "client"
    assert wired[OBSERVABILITY_STATUS_ACTION_ID].access_class == "read"
    assert wired[OBSERVABILITY_STREAM_SET_ACTION_ID].idempotent is True


def test_nlp_matching_is_explicit_and_keeps_explanatory_questions_in_chat() -> None:
    runtime = _runtime()

    assert runtime.match_submission("open observability").action_id == OBSERVABILITY_OPEN_ACTION_ID
    assert runtime.match_submission("what is the observability status?").action_id == OBSERVABILITY_STATUS_ACTION_ID
    assert runtime.match_submission("pause observability").arguments == {"enabled": False}
    assert runtime.match_submission("run observability").arguments == {"enabled": True}
    assert runtime.match_submission("reconnect the observability stream").arguments == {"enabled": True, "reconnect": True}
    assert runtime.match_submission("refresh observability").action_id == OBSERVABILITY_REFRESH_ACTION_ID
    assert runtime.match_submission("What does observability mean in software?") is None


def test_open_and_repeated_stream_controls_return_the_same_client_contract() -> None:
    runtime = _runtime()

    opened = _dispatch(runtime, OBSERVABILITY_OPEN_ACTION_ID)
    first_pause = _dispatch(runtime, OBSERVABILITY_STREAM_SET_ACTION_ID, {"enabled": False})
    second_pause = _dispatch(runtime, OBSERVABILITY_STREAM_SET_ACTION_ID, {"enabled": False})
    first_resume = _dispatch(runtime, OBSERVABILITY_STREAM_SET_ACTION_ID, {"enabled": True})
    second_resume = _dispatch(runtime, OBSERVABILITY_STREAM_SET_ACTION_ID, {"enabled": True})

    assert opened.result["navigation"] == {"view": "ledger"}
    assert first_pause.result["observability_control_patch"] == second_pause.result["observability_control_patch"]
    assert first_resume.result["observability_control_patch"] == second_resume.result["observability_control_patch"]
    assert first_pause.message == "Observability paused."
    assert first_resume.message == "Observability resumed."


def test_status_and_refresh_receipts_allow_only_operational_metadata() -> None:
    raw = _snapshot("7d")
    raw["prompt"] = "PRIVATE QUERY"
    raw["response_text"] = "PRIVATE ANSWER"
    raw["local_path"] = "D:\\Private\\notes.md"
    raw["usage"]["recent"][0]["tool_arguments"] = {"path": "D:\\Private\\secret.txt"}
    raw["runs"]["active_run"]["source_content"] = "PRIVATE SOURCE"
    runtime = _runtime(lambda _period: raw)

    status = _dispatch(runtime, OBSERVABILITY_STATUS_ACTION_ID)
    refreshed = _dispatch(runtime, OBSERVABILITY_REFRESH_ACTION_ID)
    serialized = json.dumps([status.model_dump(mode="json"), refreshed.model_dump(mode="json")])

    assert status.result["status"]["active_runs"] == 1
    assert refreshed.result["observability_snapshot"]["usage"]["total_tokens"] == 20
    assert "PRIVATE" not in serialized
    assert "notes.md" not in serialized
    assert "secret.txt" not in serialized
    assert "tool_arguments" not in serialized
    assert "source_content" not in serialized


def test_unavailable_collectors_and_refresh_failures_are_truthful() -> None:
    unavailable = _dispatch(
        _runtime(lambda _period: (_ for _ in ()).throw(OSError("offline"))),
        OBSERVABILITY_STATUS_ACTION_ID,
    )
    failed = _dispatch(
        _runtime(lambda _period: (_ for _ in ()).throw(RuntimeError("bad row: PRIVATE ANSWER"))),
        OBSERVABILITY_REFRESH_ACTION_ID,
    )

    assert unavailable.status == "unavailable"
    assert unavailable.error_code == "OBSERVABILITY_UNAVAILABLE"
    assert failed.status == "failed"
    assert failed.error_code == "OBSERVABILITY_REFRESH_FAILED"
    assert "PRIVATE ANSWER" not in failed.message
