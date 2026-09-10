from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.registry import ToolRegistry


class CalendarAgent:
    name = "CalendarAgent"
    WRITE_ACTIONS = frozenset({
        "calendar.create_event",
        "calendar.update_event",
        "calendar.delete_event",
    })

    def __init__(self, *, tool_registry: ToolRegistry, now=None) -> None:
        self.tool_registry = tool_registry
        self._now = now or (lambda tz: datetime.now(tz))

    def can_handle(self, query: str) -> bool:
        lowered = str(query or "").casefold()
        if "calendar" in lowered or "agenda" in lowered:
            return True
        return bool(
            re.search(r"\b(?:my|our)\s+(?:schedule|appointments?|meetings?)\b", lowered)
            or re.search(r"\b(?:schedule|reschedule|cancel)\s+(?:a|an|my|the)\s+(?:meeting|appointment|event)\b", lowered)
        )

    def answer(self, query: str) -> SpecialistResponse:
        clean = str(query or "").strip()
        lowered = clean.casefold()
        try:
            account = self._account()
        except Exception as exc:
            return self._error("CalendarAgent could not check Google Calendar.", exc)
        if not account.get("configured"):
            return self._needs_connection("Google Calendar OAuth is not configured in Vellum.")
        if not account.get("connected"):
            return self._needs_connection("Vellum is not connected to Google Calendar.")
        action = self._mutation_action(lowered)
        if action:
            return self._prepare_mutation(clean, action, account)
        if any(term in lowered for term in ("free", "available", "availability", "open time")):
            return self._answer_free_busy(clean, account)
        if any(term in lowered for term in ("event", "events", "schedule", "agenda", "meeting", "appointment")) or (
            "calendar" in lowered
            and not any(term in lowered for term in ("connected", "connection", "oauth", "status"))
        ):
            return self._answer_events(clean, account)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=(
                f"Vellum is connected to Google Calendar. Time zone: {account.get('time_zone') or 'not reported'}."
            ),
            analysis="Used calendar.account through the official OAuth connector.",
            confidence=1.0,
        )

    def execute_action_request(self, action_request: dict) -> SpecialistResponse:
        action = str(action_request.get("action") or "")
        if action not in self.WRITE_ACTIONS:
            return self._blocked("CalendarAgent cannot execute that pending Calendar action.")
        payload = action_request.get("payload") if isinstance(action_request.get("payload"), dict) else {}
        try:
            result = self.tool_registry.invoke(action, {**payload, "confirm": True}, agent_name=self.name)
        except Exception as exc:
            return self._error("CalendarAgent could not complete that Calendar action.", exc)
        event = result.get("event") if isinstance(result.get("event"), dict) else {}
        labels = {
            "calendar.create_event": "Created",
            "calendar.update_event": "Updated",
            "calendar.delete_event": "Deleted",
        }
        target = str(event.get("summary") or payload.get("summary") or payload.get("event_id") or "the event")
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=f"{labels[action]} {target} in Google Calendar.",
            analysis=f"Used {action} after explicit confirmation.",
            confidence=1.0,
            structured_payload={**dict(result), "authorization": "confirmed"},
        )

    def _answer_events(self, query: str, account: dict) -> SpecialistResponse:
        start, end = self._window(query, account)
        search = self._quoted_text(query)
        try:
            result = self.tool_registry.invoke(
                "calendar.events",
                {
                    "calendar_id": "primary",
                    "time_min": start.isoformat(),
                    "time_max": end.isoformat(),
                    "query": search,
                    "max_results": 50,
                },
                agent_name=self.name,
            )
        except Exception as exc:
            return self._error("CalendarAgent could not read Google Calendar events.", exc)
        events = list(result.get("items") or [])
        if not events:
            return SpecialistResponse(
                agent=self.name,
                status="answered",
                summary="No Google Calendar events matched that time range.",
                analysis="Used calendar.events through the official OAuth connector.",
                confidence=1.0,
            )
        lines = []
        sources = []
        for index, event in enumerate(events[:50], start=1):
            title = str(event.get("summary") or "Untitled event")
            starts = str(event.get("start") or "")
            location = str(event.get("location") or "")
            event_id = str(event.get("id") or "")
            identifier = f" - event ID: {event_id}" if event_id else ""
            lines.append(f"[{index}] {title} - {starts}" + (f" - {location}" if location else "") + identifier)
            sources.append(SpecialistSource(
                kind="api",
                title=title,
                path_or_url=f"google-calendar://events/{event_id or index}",
                snippet=f"Starts {starts}",
                captured_at=starts,
                freshness="live",
            ))
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary="Google Calendar events:\n" + "\n".join(lines),
            analysis="Used calendar.events through the official OAuth connector.",
            sources=sources,
            confidence=1.0,
        )

    def _answer_free_busy(self, query: str, account: dict) -> SpecialistResponse:
        start, end = self._window(query, account)
        try:
            result = self.tool_registry.invoke(
                "calendar.free_busy",
                {"time_min": start.isoformat(), "time_max": end.isoformat(), "calendar_ids": ["primary"]},
                agent_name=self.name,
            )
        except Exception as exc:
            return self._error("CalendarAgent could not check availability.", exc)
        calendars = result.get("calendars") if isinstance(result.get("calendars"), dict) else {}
        primary = calendars.get("primary") if isinstance(calendars.get("primary"), dict) else {}
        busy = primary.get("busy") if isinstance(primary.get("busy"), list) else []
        if not busy:
            summary = f"Your primary calendar is free from {start.isoformat()} to {end.isoformat()}."
        else:
            slots = [f"{item.get('start')} to {item.get('end')}" for item in busy if isinstance(item, dict)]
            summary = "Busy periods on your primary calendar:\n" + "\n".join(slots)
        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used calendar.free_busy through the official OAuth connector.",
            confidence=1.0,
        )

    def _prepare_mutation(self, query: str, action: str, account: dict) -> SpecialistResponse:
        payload, error = self._mutation_payload(query, action, account)
        if error:
            return self._blocked(error)
        preview = self._preview(action, payload)
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f"Confirm this Google Calendar change:\n\n{preview}",
            analysis=f"Prepared {action} and is waiting for explicit confirmation.",
            confidence=0.95,
            action_request={"action": action, "payload": payload, "preview": preview},
        )

    def _mutation_payload(self, query: str, action: str, account: dict) -> tuple[dict, str]:
        payload: dict[str, object] = {"calendar_id": "primary"}
        event_id = self._labeled_value(query, r"event(?:\s+id)?", r"[A-Za-z0-9_-]{3,1024}")
        if action in {"calendar.update_event", "calendar.delete_event"}:
            if not event_id:
                return {}, "CalendarAgent needs the exact event ID shown by Vellum before changing an existing event."
            payload["event_id"] = event_id
        if action == "calendar.delete_event":
            return payload, ""

        title = self._quoted_text(query)
        if action == "calendar.create_event" and not title:
            return {}, 'CalendarAgent needs the event title in quotes, for example: schedule "Project review" tomorrow at 3 PM.'
        if title:
            payload["summary"] = title
        if action == "calendar.update_event" and not title and not re.search(r"\b(?:at|on|from)\b", query, re.I):
            return {}, "CalendarAgent needs a new quoted title or an exact new date and time."

        start = self._requested_start(query, account)
        if start is not None:
            duration = self._duration(query)
            payload["start"] = start.isoformat()
            payload["end"] = (start + duration).isoformat()
            payload["time_zone"] = self._timezone_name(account)
        elif action == "calendar.create_event":
            return {}, "CalendarAgent needs an unambiguous date and start time."
        return payload, ""

    @staticmethod
    def _mutation_action(lowered: str) -> str:
        if re.search(r"\b(?:delete|remove|cancel)\b", lowered):
            return "calendar.delete_event"
        if re.search(r"\b(?:reschedule|move|update|rename|change)\b", lowered):
            return "calendar.update_event"
        if re.search(r"\b(?:add|create|schedule|book)\b", lowered):
            return "calendar.create_event"
        return ""

    def _window(self, query: str, account: dict) -> tuple[datetime, datetime]:
        tz = self._timezone(account)
        now = self._now(tz)
        lowered = query.casefold()
        if "tomorrow" in lowered:
            day = now.date() + timedelta(days=1)
            start = datetime.combine(day, time.min, tz)
            return start, start + timedelta(days=1)
        if "today" in lowered:
            start = datetime.combine(now.date(), time.min, tz)
            return start, start + timedelta(days=1)
        if "week" in lowered:
            start = datetime.combine(now.date(), time.min, tz)
            return start, start + timedelta(days=7)
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", query)
        if date_match:
            day = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
            start = datetime.combine(day, time.min, tz)
            return start, start + timedelta(days=1)
        return now, now + timedelta(days=7)

    def _requested_start(self, query: str, account: dict) -> datetime | None:
        direct = re.search(r"\b(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))\b", query)
        if direct:
            return datetime.fromisoformat(direct.group(1).replace("Z", "+00:00"))
        lowered = query.casefold()
        tz = self._timezone(account)
        now = self._now(tz)
        if "tomorrow" in lowered:
            day = now.date() + timedelta(days=1)
        elif "today" in lowered:
            day = now.date()
        else:
            match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", query)
            if not match:
                return None
            day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        clock = re.search(r"\b(?:at|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
        if not clock:
            return None
        hour = int(clock.group(1))
        minute = int(clock.group(2) or 0)
        meridiem = clock.group(3)
        if meridiem:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        elif hour > 23:
            return None
        if minute > 59:
            return None
        return datetime.combine(day, time(hour, minute), tz)

    @staticmethod
    def _duration(query: str) -> timedelta:
        match = re.search(r"\bfor\s+(\d{1,3})\s*(minutes?|mins?|hours?|hrs?)\b", query, re.I)
        if not match:
            return timedelta(hours=1)
        amount = max(1, int(match.group(1)))
        return timedelta(hours=min(amount, 24)) if match.group(2).casefold().startswith(("hour", "hr")) else timedelta(minutes=min(amount, 1440))

    @staticmethod
    def _quoted_text(query: str) -> str:
        match = re.search(r'["“](.+?)["”]', query)
        return match.group(1).strip()[:1024] if match else ""

    @staticmethod
    def _labeled_value(query: str, label: str, value_pattern: str) -> str:
        match = re.search(rf"\b{label}\s*[:#]?\s*({value_pattern})\b", query, re.I)
        return match.group(1) if match else ""

    @staticmethod
    def _timezone_name(account: dict) -> str:
        return str(account.get("time_zone") or "UTC")

    def _timezone(self, account: dict):
        try:
            return ZoneInfo(self._timezone_name(account))
        except ZoneInfoNotFoundError:
            return UTC

    @staticmethod
    def _preview(action: str, payload: dict) -> str:
        if action == "calendar.delete_event":
            return f"Delete event {payload.get('event_id')} from the primary calendar."
        verb = "Create" if action == "calendar.create_event" else "Update"
        title = payload.get("summary") or payload.get("event_id")
        when = f" from {payload.get('start')} to {payload.get('end')}" if payload.get("start") else ""
        return f"{verb} {title}{when}."

    def _account(self) -> dict:
        return dict(self.tool_registry.invoke("calendar.account", {}, agent_name=self.name))

    def _needs_connection(self, summary: str) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="needs_fetch",
            summary=summary,
            analysis="Used calendar.account through the official OAuth connector.",
            confidence=1.0,
        )

    def _blocked(self, summary: str) -> SpecialistResponse:
        return SpecialistResponse(agent=self.name, status="blocked", summary=summary, confidence=1.0)

    def _error(self, summary: str, exc: Exception) -> SpecialistResponse:
        return SpecialistResponse(
            agent=self.name,
            status="error",
            summary=summary,
            analysis=f"Calendar connector failed: {type(exc).__name__}.",
            confidence=0.2,
        )
