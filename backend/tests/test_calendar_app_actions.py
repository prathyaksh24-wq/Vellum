from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins import google_calendar_controls as controls
from agent.plugins.contributions import PluginContributionActionError
from agent.plugins.registry import PluginRegistry
from agent.tools.capabilities.calendar_service import CalendarConflictError


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(controls, "google_calendar_status", lambda: {"configured": True, "connected": True})
    registry = PluginRegistry(Path(__file__).resolve().parents[2] / "plugins", state_path=tmp_path / "plugin-state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(controls.google_calendar_plugin_contribution())
    return runtime, registry


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_calendar_mutations_require_bound_confirmation(runtime, monkeypatch, operation):
    app, registry = runtime
    service = Mock()
    getattr(service, operation + "_event").return_value = {"event": {"id": "test"}}
    monkeypatch.setattr(controls, "google_calendar_service", lambda: service)
    context = AppActionContext(source="ui", invocation_conversation_id="qa-chat")
    request = AppActionRequest(action_id="calendar.event." + operation, arguments={
        "summary": "QA", "start": "2026-10-02T15:00:00+05:30", "end": "2026-10-02T15:30:00+05:30",
        "event_id": "test", "confirm": True,
    })
    receipt = app.dispatch(request, context)
    assert receipt.status == "confirmation_required"
    assert not service.mock_calls
    confirmed = app.confirm(receipt.confirmation.token, request, context)
    assert confirmed.status == "applied"
    assert confirmed.result["changed"] is True
    assert getattr(service, operation + "_event").call_args.args[0]["confirm"] is True
    registry.set_enabled("google-calendar", False)
    assert app.dispatch(request, context).status == "unavailable"


def test_late_conflict_is_a_no_change_receipt(runtime, monkeypatch):
    app, _registry = runtime
    availability = {"available": False, "proposed": {"start": "2026-10-02T16:00:00+05:30"}}
    service = Mock()
    service.create_event.side_effect = CalendarConflictError(availability)
    monkeypatch.setattr(controls, "google_calendar_service", lambda: service)
    context = AppActionContext(source="ui")
    request = AppActionRequest(action_id="calendar.event.create", arguments={
        "summary": "QA", "start": "2026-10-02T15:00:00+05:30", "end": "2026-10-02T15:30:00+05:30",
    })
    receipt = app.dispatch(request, context)
    confirmed = app.confirm(receipt.confirmation.token, request, context)
    assert confirmed.result == {"changed": False, "availability": availability}


def test_connection_start_reuses_oauth_flow(runtime, monkeypatch):
    app, _registry = runtime
    from agent.plugins.google_calendar_api import CalendarOAuthStartResponse
    monkeypatch.setattr(controls, "start_connection", lambda: CalendarOAuthStartResponse(
        authorization_url="https://accounts.google.com/oauth", redirect_uri="http://127.0.0.1:8000", scopes=[]))
    receipt = app.dispatch(AppActionRequest(action_id="calendar.connection.start"), AppActionContext(source="ui"))
    assert receipt.status == "applied"
    assert receipt.result["connection"]["authorization_url"].startswith("https://accounts.google.com")


def test_disconnect_requires_confirmation(runtime, monkeypatch):
    app, _registry = runtime
    store = Mock()
    monkeypatch.setattr(controls, "google_calendar_store", lambda: store)
    context = AppActionContext(source="ui")
    request = AppActionRequest(action_id="calendar.connection.disconnect")
    receipt = app.dispatch(request, context)
    assert not store.mock_calls
    assert app.confirm(receipt.confirmation.token, request, context).result["disconnected"] is True
    store.clear.assert_called_once()


def test_adapter_cannot_bypass_confirmation():
    with pytest.raises(PluginContributionActionError, match="Confirm"):
        controls.execute_calendar_control("calendar.event.create", {"confirm": True})
