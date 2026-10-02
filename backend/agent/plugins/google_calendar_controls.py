"""Calendar controls contributed to the existing App Action runtime."""

from typing import Any

from fastapi import HTTPException

from agent.app_actions.models import AppActionDefinition
from agent.plugins.contributions import (
    PluginActionContribution, PluginContribution, PluginContributionActionError,
)
from agent.plugins.google_calendar_api import (
    CalendarEventBody, CalendarEventPatch, CalendarConfirmBody, start_connection,
)
from agent.plugins.google_calendar_runtime import (
    GoogleCalendarAuthError, GoogleCalendarAPIError, google_calendar_service,
    google_calendar_status, google_calendar_store,
)
from agent.tools.capabilities.calendar_service import CalendarConflictError


def execute_calendar_control(action_id: str, arguments: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
    try:
        if action_id == "calendar.connection.start":
            return {"changed": True, "connection": start_connection().model_dump(),
                    "_message": "Google Calendar authorization is ready."}
        if not confirmed:
            raise PluginContributionActionError("CONFIRMATION_REQUIRED", "Confirm this Calendar change.")
        if action_id == "calendar.connection.disconnect":
            google_calendar_store().clear()
            return {"changed": True, "disconnected": True, "_message": "Google Calendar disconnected."}
        operation = action_id.rsplit(".", 1)[-1]
        models = {"create": CalendarEventBody, "update": CalendarEventPatch, "delete": CalendarConfirmBody}
        if operation not in models:
            raise PluginContributionActionError("ACTION_UNAVAILABLE", "Unknown Calendar action.", unavailable=True)
        payload = models[operation].model_validate({**arguments, "confirm": True}).model_dump(exclude_none=True)
        if operation != "create":
            payload["event_id"] = str(arguments.get("event_id") or "")
            if not payload["event_id"]:
                raise ValueError("An event ID is required.")
        result = getattr(google_calendar_service(), operation + "_event")(payload)
        return {"changed": True, **result, "_message": f"Calendar event {operation} completed."}
    except CalendarConflictError as exc:
        return {"changed": False, "availability": exc.availability, "_message": str(exc)}
    except HTTPException as exc:
        raise PluginContributionActionError("CALENDAR_CONNECTION_FAILED", str(exc.detail)) from exc
    except (GoogleCalendarAuthError, GoogleCalendarAPIError) as exc:
        raise PluginContributionActionError("CALENDAR_CONNECTION_FAILED", "Google Calendar could not complete this action. Refresh the connection status.") from exc


def google_calendar_plugin_contribution() -> PluginContribution:
    common = dict(version="1", owner="google-calendar", plugin_id="google-calendar", scope="user",
                  executor_location="server", supports_undo=False, idempotent=False,
                  result_schema={"type": "object", "required": ["changed"]}, ui_reference="calendar.workspace")
    specs = [("calendar.connection.start", "Connect Google Calendar", "external_write", None),
             ("calendar.connection.disconnect", "Disconnect Google Calendar", "destructive", None),
             ("calendar.event.create", "Create Calendar event", "external_write", CalendarEventBody),
             ("calendar.event.update", "Update Calendar event", "external_write", CalendarEventPatch),
             ("calendar.event.delete", "Delete Calendar event", "destructive", CalendarConfirmBody)]
    actions = []
    for identifier, title, access, model in specs:
        schema = model.model_json_schema() if model else {"type": "object", "properties": {}}
        schema["additionalProperties"] = False
        schema["properties"].pop("confirm", None)
        if identifier in {"calendar.event.update", "calendar.event.delete"}:
            schema["properties"]["event_id"] = {"type": "string", "minLength": 1, "maxLength": 1024}
            schema.setdefault("required", []).append("event_id")
        def available(_context, registered=identifier):
            status = google_calendar_status()
            return bool(status.get("configured") if registered.endswith(".start") else status.get("connected"))
        actions.append(PluginActionContribution(
            definition=AppActionDefinition(id=identifier, title=title, description=title + " through the canonical Google Calendar connector.",
                access_class=access, confirmation_rule="oauth_consent" if identifier.endswith(".start") else "operation_bound",
                argument_schema=schema, audit_label=identifier, required_permissions=[identifier], **common),
            availability=available,
            adapter=lambda payload, registered=identifier: execute_calendar_control(
                registered, dict(payload.get("arguments") or {}), confirmed=payload.get("confirmed") is True),
        ))
    return PluginContribution(owner="google-calendar", actions=tuple(actions))
