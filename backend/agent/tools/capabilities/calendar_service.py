from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


AccountBackend = Callable[[], dict[str, Any]]
CalendarsBackend = Callable[[], list[dict[str, Any]]]
EventsBackend = Callable[..., list[dict[str, Any]]]
EventBackend = Callable[..., dict[str, Any]]
FreeBusyBackend = Callable[..., dict[str, Any]]
CreateBackend = Callable[..., dict[str, Any]]
UpdateBackend = Callable[..., dict[str, Any]]
DeleteBackend = Callable[..., dict[str, Any]]


class CalendarCapabilityService:
    def __init__(
        self,
        *,
        account_backend: AccountBackend | None = None,
        calendars_backend: CalendarsBackend | None = None,
        events_backend: EventsBackend | None = None,
        event_backend: EventBackend | None = None,
        free_busy_backend: FreeBusyBackend | None = None,
        create_backend: CreateBackend | None = None,
        update_backend: UpdateBackend | None = None,
        delete_backend: DeleteBackend | None = None,
    ) -> None:
        self.account_backend = account_backend or self._default_account
        self.calendars_backend = calendars_backend or self._default_calendars
        self.events_backend = events_backend or self._default_events
        self.event_backend = event_backend or self._default_event
        self.free_busy_backend = free_busy_backend or self._default_free_busy
        self.create_backend = create_backend or self._default_create
        self.update_backend = update_backend or self._default_update
        self.delete_backend = delete_backend or self._default_delete

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        allowed = frozenset({"CalendarAgent"})
        for name, label, adapter in (
            ("calendar.account", "Checked Google Calendar", self.account),
            ("calendar.calendars", "Read calendars", self.calendars),
            ("calendar.events", "Read calendar events", self.events),
            ("calendar.event", "Read calendar event", self.event),
            ("calendar.free_busy", "Checked calendar availability", self.free_busy),
        ):
            registry.register(CapabilityRecord(
                name=name,
                namespace="calendar",
                access=CapabilityAccess.READ,
                allowed_agents=allowed,
                stream_label=label,
                adapter=adapter,
            ))
        for name, label, adapter in (
            ("calendar.create_event", "Create calendar event", self.create_event),
            ("calendar.update_event", "Update calendar event", self.update_event),
            ("calendar.delete_event", "Delete calendar event", self.delete_event),
        ):
            registry.register(CapabilityRecord(
                name=name,
                namespace="calendar",
                access=CapabilityAccess.EXTERNAL_WRITE,
                allowed_agents=allowed,
                stream_label=label,
                adapter=adapter,
                requires_confirmation=True,
            ))
        return registry

    def account(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"action": "calendar.account", **dict(self.account_backend())}

    def calendars(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"action": "calendar.calendars", "items": [self._calendar(item) for item in self.calendars_backend()]}

    def events(self, payload: dict[str, Any]) -> dict[str, Any]:
        time_min = self._timestamp(payload.get("time_min"), "time_min")
        time_max = self._timestamp(payload.get("time_max"), "time_max")
        self._ordered(time_min, time_max)
        items = self.events_backend(
            calendar_id=self._calendar_id(payload.get("calendar_id")),
            time_min=time_min,
            time_max=time_max,
            query=str(payload.get("query") or "").strip()[:500],
            max_results=min(max(int(payload.get("max_results") or 50), 1), 250),
        )
        return {"action": "calendar.events", "items": [self._event(item) for item in items]}

    def event(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = self.event_backend(
            calendar_id=self._calendar_id(payload.get("calendar_id")),
            event_id=self._required(payload.get("event_id"), "event_id", 1024),
        )
        return {"action": "calendar.event", "event": self._event(item)}

    def free_busy(self, payload: dict[str, Any]) -> dict[str, Any]:
        time_min = self._timestamp(payload.get("time_min"), "time_min")
        time_max = self._timestamp(payload.get("time_max"), "time_max")
        self._ordered(time_min, time_max)
        raw_ids = payload.get("calendar_ids") if isinstance(payload.get("calendar_ids"), list) else ["primary"]
        calendar_ids = [self._calendar_id(item) for item in raw_ids[:50]]
        return {"action": "calendar.free_busy", **dict(self.free_busy_backend(
            time_min=time_min,
            time_max=time_max,
            calendar_ids=calendar_ids,
        ))}

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._confirmed(payload)
        event = self._event_body(payload)
        created = self.create_backend(calendar_id=self._calendar_id(payload.get("calendar_id")), event=event)
        return {"action": "calendar.create_event", "event": self._event(created)}

    def update_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._confirmed(payload)
        event_id = self._required(payload.get("event_id"), "event_id", 1024)
        patch = self._event_body(payload, require_summary=False)
        if not patch:
            raise ValueError("Calendar event update is empty")
        updated = self.update_backend(
            calendar_id=self._calendar_id(payload.get("calendar_id")),
            event_id=event_id,
            patch=patch,
        )
        return {"action": "calendar.update_event", "event": self._event(updated)}

    def delete_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._confirmed(payload)
        result = self.delete_backend(
            calendar_id=self._calendar_id(payload.get("calendar_id")),
            event_id=self._required(payload.get("event_id"), "event_id", 1024),
        )
        return {"action": "calendar.delete_event", **dict(result)}

    @staticmethod
    def _confirmed(payload: dict[str, Any]) -> None:
        if payload.get("confirm") is not True:
            raise ToolPermissionError("Calendar changes require explicit confirmation")

    def _event_body(self, payload: dict[str, Any], *, require_summary: bool = True) -> dict[str, Any]:
        event: dict[str, Any] = {}
        summary = str(payload.get("summary") or "").strip()
        if require_summary and not summary:
            raise ValueError("summary is required")
        if summary:
            event["summary"] = summary[:1024]
        for key, limit in (("description", 8192), ("location", 1024)):
            if key in payload:
                event[key] = str(payload.get(key) or "").strip()[:limit]
        start = str(payload.get("start") or "").strip()
        end = str(payload.get("end") or "").strip()
        time_zone = str(payload.get("time_zone") or "").strip()
        if start or end:
            if not start or not end:
                raise ValueError("start and end must be provided together")
            start = self._timestamp(start, "start")
            end = self._timestamp(end, "end")
            self._ordered(start, end)
            event["start"] = {"dateTime": start}
            event["end"] = {"dateTime": end}
            if time_zone:
                event["start"]["timeZone"] = time_zone[:100]
                event["end"]["timeZone"] = time_zone[:100]
        attendees = payload.get("attendees")
        if attendees is not None:
            if not isinstance(attendees, list) or len(attendees) > 50:
                raise ValueError("attendees must be a list of at most 50 email addresses")
            event["attendees"] = [{"email": self._required(item, "attendee", 320)} for item in attendees]
        return event

    @staticmethod
    def _timestamp(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a UTC offset")
        return text

    @staticmethod
    def _ordered(start: str, end: str) -> None:
        first = datetime.fromisoformat(start.replace("Z", "+00:00"))
        second = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if second <= first:
            raise ValueError("Calendar end must be after start")

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        return text[:limit]

    @staticmethod
    def _calendar_id(value: Any) -> str:
        return str(value or "primary").strip()[:1024] or "primary"

    @staticmethod
    def _calendar(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(item.get("id") or ""),
            "summary": str(item.get("summary") or ""),
            "primary": item.get("primary") is True,
            "access_role": str(item.get("accessRole") or ""),
            "time_zone": str(item.get("timeZone") or ""),
            "background_color": str(item.get("backgroundColor") or ""),
        }

    @staticmethod
    def _event(item: dict[str, Any]) -> dict[str, Any]:
        start = item.get("start") if isinstance(item.get("start"), dict) else {}
        end = item.get("end") if isinstance(item.get("end"), dict) else {}
        attendees = item.get("attendees") if isinstance(item.get("attendees"), list) else []
        return {
            "id": str(item.get("id") or ""),
            "summary": str(item.get("summary") or ""),
            "description": str(item.get("description") or ""),
            "location": str(item.get("location") or ""),
            "status": str(item.get("status") or ""),
            "html_link": str(item.get("htmlLink") or ""),
            "start": str(start.get("dateTime") or start.get("date") or ""),
            "end": str(end.get("dateTime") or end.get("date") or ""),
            "time_zone": str(start.get("timeZone") or end.get("timeZone") or ""),
            "attendees": [
                {
                    "email": str(attendee.get("email") or ""),
                    "response_status": str(attendee.get("responseStatus") or ""),
                    "self": attendee.get("self") is True,
                }
                for attendee in attendees[:50]
                if isinstance(attendee, dict)
            ],
        }

    @staticmethod
    def _client():
        from agent.plugins.google_calendar_runtime import google_calendar_client

        return google_calendar_client()

    @staticmethod
    def _default_account() -> dict[str, Any]:
        from agent.plugins.google_calendar_runtime import google_calendar_status

        return google_calendar_status()

    def _default_calendars(self) -> list[dict[str, Any]]:
        return self._client().list_calendars()

    def _default_events(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._client().list_events(**kwargs)

    def _default_event(self, **kwargs: Any) -> dict[str, Any]:
        return self._client().get_event(**kwargs)

    def _default_free_busy(self, **kwargs: Any) -> dict[str, Any]:
        return self._client().free_busy(**kwargs)

    def _default_create(self, **kwargs: Any) -> dict[str, Any]:
        return self._client().create_event(**kwargs)

    def _default_update(self, **kwargs: Any) -> dict[str, Any]:
        return self._client().update_event(**kwargs)

    def _default_delete(self, **kwargs: Any) -> dict[str, Any]:
        return self._client().delete_event(**kwargs)
