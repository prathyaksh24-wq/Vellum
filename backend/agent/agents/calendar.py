from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.tools.registry import ToolRegistry
from agent.tools.capabilities.calendar_service import CalendarConflictError


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
            re.search(r"\b(?:am\s+i|are\s+we|will\s+i\s+be)\s+(?:free|available|busy)\b", lowered)
            or re.search(r"\b(?:my|our)\s+availability\b", lowered)
            or re.search(r"\b(?:my\s+)?upcoming\s+(?:events?|meetings?|appointments?)\b", lowered)
            or re.search(r"\b(?:my|our)\s+(?:schedule|appointments?|meetings?)\b", lowered)
            or re.search(
                r"\b(?:book|create|add|schedule|reschedule|cancel|delete|move|update|find|rename)\s+(?:a|an|my|the)?\s*(?:meeting|appointment|event)\b",
                lowered,
            )
        )

    def answer(self, query: str) -> SpecialistResponse:
        return self.answer_with_context(query, {})

    def answer_with_context(self, query: str, context: dict) -> SpecialistResponse:
        clean = str(query or "").strip()
        lowered = clean.casefold()
        try:
            account = self._account()
        except Exception as exc:
            return self._error("CalendarAgent could not check Google Calendar.", exc)
        if account.get("enabled") is False:
            return self._blocked("Google Calendar is disabled. Enable it in Plugins to use your calendar.")
        if not account.get("configured"):
            return self._needs_connection("Google Calendar OAuth is not configured in Vellum.")
        if not account.get("connected"):
            return self._needs_connection("Vellum is not connected to Google Calendar.")
        action = self._mutation_action(re.sub(r'["“].+?["”]', "", lowered))
        if action:
            return self._prepare_mutation(clean, action, account, context)
        if any(term in lowered for term in ("free", "available", "availability", "open time", "busy")):
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
        except CalendarConflictError as exc:
            return self._time_proposal(action, payload, exc.availability)
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
            structured_payload={**dict(result), **({"event":{**event,"calendar_id":payload.get("calendar_id") or "primary","calendar_label":payload.get("calendar_label") or ""}} if event else {}), "authorization": "confirmed"},
        )

    def _answer_events(self, query: str, account: dict) -> SpecialistResponse:
        start, end = self._window(query, account)
        search = self._quoted_text(query)
        try:
            result = self.tool_registry.invoke(
                "calendar.events",
                {
                    "calendar_id": self._calendar_scope(query),
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
        errors = result.get("errors") or []
        partial = " Some calendars could not be read; this list is incomplete." if errors else ""
        if not events:
            return SpecialistResponse(
                agent=self.name,
                status="answered",
                summary="No Google Calendar events matched that time range." + partial,
                analysis="Used calendar.events through the official OAuth connector.",
                confidence=0.5 if errors else 1.0,
                structured_payload={"events": [], "calendars":result.get("calendars", []), "errors":errors},
            )
        lines = []
        sources = []
        for index, event in enumerate(events[:50], start=1):
            title = str(event.get("summary") or "Untitled event")
            starts = str(event.get("start") or "")
            location = str(event.get("location") or "")
            event_id = str(event.get("id") or "")
            identifier = f" - event ID: {event_id}" if event_id and "id" in query.casefold() else ""
            label = str(event.get("calendar_label") or "")
            lines.append(f"- {title} — {self._display_time(starts, self._timezone_name(account))}" + (f" · {label}" if label else "") + (f" · {location}" if location else "") + identifier)
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
            summary="Google Calendar events:\n" + "\n".join(lines) + partial,
            analysis="Used calendar.events through the official OAuth connector.",
            sources=sources,
            confidence=1.0,
            structured_payload={"events": events, "calendars":result.get("calendars", []), "errors":errors},
        )

    def _calendar_scope(self, query: str) -> str:
        lowered = query.casefold()
        calendars = self.tool_registry.invoke("calendar.calendars", {}, agent_name=self.name).get("items", [])
        aliases = bool(re.search(r"\b(?:f1|formula\s*(?:1|one))\b", lowered))
        matches = []
        for calendar in calendars:
            label = str(calendar.get("summary") or "").casefold().strip()
            named = label and re.search(rf"(?:{re.escape(label)}\s+calendar|calendar\s+(?:called\s+|named\s+)?{re.escape(label)})(?:\b|$)",lowered)
            f1 = aliases and re.search(r"\b(?:f1|formula\s*(?:1|one))\b",label)
            if named or f1: matches.append(calendar)
        return str(matches[0]["id"]) if len(matches)==1 else "all"

    @staticmethod
    def thread_context(response: SpecialistResponse, previous: dict) -> dict:
        result = dict(previous)
        structured = response.structured_payload
        allowed = ("id","summary","start","end","calendar_id","calendar_label","access_role")
        if "events" in structured:
            result.pop("last_deleted", None)
            events = [{k:e.get(k, "") for k in allowed} for e in structured["events"][:50]]
            result["events"] = events
            old = result.get("focus_event") or {}
            result["focus_event"] = events[0] if len(events)==1 else next((e for e in events if e["id"]==old.get("id") and e["calendar_id"]==old.get("calendar_id")), None)
        event = structured.get("event")
        if isinstance(event, dict) and event.get("id"):
            result.pop("last_deleted", None)
            result["focus_event"] = {k:event.get(k, "") for k in allowed}
            result["events"] = [result["focus_event"]]
        if structured.get("deleted"):
            result["last_deleted"] = True
            result["events"] = [e for e in result.get("events",[]) if not (e.get("id")==structured.get("event_id") and e.get("calendar_id")==structured.get("calendar_id"))]
            result["focus_event"] = None
        return result

    def _answer_free_busy(self, query: str, account: dict) -> SpecialistResponse:
        start, end = self._window(query, account)
        try:
            selected = self._calendar_scope(query)
            calendars = self.tool_registry.invoke("calendar.calendars", {}, agent_name=self.name).get("items", [])
            ids = [c["id"] for c in calendars if not c.get("hidden") and (selected=="all" or c["id"]==selected)]
            result = self.tool_registry.invoke("calendar.free_busy", {"time_min":start.isoformat(), "time_max":end.isoformat(), "calendar_ids":ids},agent_name=self.name)
        except Exception as exc:
            return self._error("CalendarAgent could not check availability.", exc)
        blocks = result.get("calendars") if isinstance(result.get("calendars"), dict) else {}
        busy = [b for c in blocks.values() for b in c.get("busy",[]) if isinstance(b,dict)]
        if any(c.get("errors") for c in blocks.values()) or not ids:
            return self._blocked("I could not check every calendar, so I cannot verify that this time is free.")
        if not busy:
            summary = f"Your calendars are free from {self._display_time(start.isoformat(),self._timezone_name(account))} to {self._display_time(end.isoformat(),self._timezone_name(account))}."
        else:
            slots = sorted(set(f"{self._display_time(item.get('start',''),self._timezone_name(account))} to {self._display_time(item.get('end',''),self._timezone_name(account))}" for item in busy))
            summary = "Busy periods across your calendars:\n" + "\n".join(slots)

        return SpecialistResponse(
            agent=self.name,
            status="answered",
            summary=summary,
            analysis="Used calendar.free_busy through the official OAuth connector.",
            confidence=1.0,
        )

    def _prepare_mutation(self, query: str, action: str, account: dict, context: dict | None = None) -> SpecialistResponse:
        payload, error = self._mutation_payload(query, action, account, context or {})
        if error:
            return self._blocked(error)
        if payload.get("start"):
            try:
                availability = self.tool_registry.invoke("calendar.availability", payload, agent_name=self.name)
            except Exception as exc:
                return self._error("I could not check availability before preparing that change.", exc)
            if not availability.get("available"):
                return self._time_proposal(action, payload, availability)
        preview = self._preview(action, payload)
        return SpecialistResponse(
            agent=self.name,
            status="blocked",
            summary=f"Confirm this Google Calendar change:\n\n{preview}",
            analysis=f"Prepared {action} and is waiting for explicit confirmation.",
            confidence=0.95,
            action_request={"action": action, "payload": payload, "preview": preview},
        )

    def _mutation_payload(self, query: str, action: str, account: dict, context: dict | None = None) -> tuple[dict, str]:
        payload: dict[str, object] = {"calendar_id": "primary"}
        event_id = self._labeled_value(query, r"(?:event\s+id|id)", r"[A-Za-z0-9_-]{3,1024}")
        quoted = re.findall(r'["“](.+?)["”]', query)
        title = quoted[0].strip() if quoted else self._natural_title(query, action)
        existing = None
        if action in {"calendar.update_event", "calendar.delete_event"}:
            context = context or {}
            referenced = bool(re.search(r"\b(?:delete|remove|cancel|move|reschedule|update|change)\s+(?:it|that|this|the\s+(?:event|meeting|appointment))\b", query, re.I)) and not quoted
            if referenced and not event_id:
                existing = context.get("focus_event")
                if not existing and len(context.get("events") or []) == 1:
                    existing = context["events"][0]
                if not existing and action=="calendar.delete_event" and context.get("last_deleted"):
                    return {}, "That event has already been deleted."
                if not existing:
                    return {}, "Which event should I change? Give me its title, or find the event first."
                event_id = str(existing.get("id") or "")
                payload["calendar_id"] = existing.get("calendar_id") or "primary"
                title = str(existing.get("summary") or "")
            if not event_id:
                if not title:
                    return {}, "Which calendar event should I change? Give me its title or event ID."
                try:
                    now = self._now(self._timezone(account))
                    dated = bool(re.search(r"\b(?:today|tomorrow|20\d{2}-\d{2}-\d{2})\b", query, re.I))
                    first, last = self._window(query, account) if dated else (now-timedelta(days=30),now+timedelta(days=365))
                    result = self.tool_registry.invoke("calendar.events", {
                        "calendar_id": self._calendar_scope(query), "time_min": first.isoformat(),
                        "time_max": last.isoformat(), "query": title, "max_results": 250,
                    }, agent_name=self.name)
                    if result.get("errors") or result.get("truncated"):
                        return {}, "I could not search every calendar safely. Select the calendar and event before changing it."
                    candidates = [item for item in result.get("items", []) if str(item.get("summary") or "").casefold() == title.casefold()]
                    if not candidates:
                        candidates = [item for item in result.get("items", []) if title.casefold() in str(item.get("summary") or "").casefold()]
                    if len(candidates) != 1:
                        return {}, ("I found more than one event with that title. Specify its date, calendar, or event ID."
                                    if len(candidates) > 1 else "I could not find that event. Give me its exact title or find it first.")
                    existing = candidates[0]
                    event_id = str(existing["id"])
                    payload["calendar_id"] = existing.get("calendar_id") or "primary"
                except Exception:
                    return {}, "I could not look up that calendar event. Please try again."
            elif existing is None:
                matching = [e for e in context.get("events", []) if e.get("id")==event_id]
                if len(matching)==1:
                    payload["calendar_id"] = matching[0].get("calendar_id") or "primary"
                try:
                    existing = self.tool_registry.invoke("calendar.event", {"calendar_id":payload["calendar_id"],"event_id":event_id},agent_name=self.name).get("event",{})
                except Exception:
                    return {}, "That event could not be found. Find it on your calendar first so I can use its real event ID."
            if existing and existing.get("access_role") in {"reader", "freeBusyReader"}:
                return {}, "This calendar is read-only. I can show its events, but cannot change or delete them."
            payload["event_id"] = event_id
            if existing:
                payload["calendar_label"] = existing.get("calendar_label") or ""
        if action == "calendar.delete_event":
            if existing: payload["summary"] = existing.get("summary") or title
            return payload, ""
        if action == "calendar.create_event" and not title:
            return {}, 'What should the event be called? Include a title in quotes or after "schedule".'
        if title:
            payload["summary"] = quoted[1].strip() if action == "calendar.update_event" and len(quoted) > 1 else title
        if action == "calendar.update_event" and not title and not re.search(r"\b(?:at|on|from)\b", query, re.I):
            return {}, "What should I change: the title or the date and time?"

        start = self._requested_start(query, account)
        if start is not None:
            duration = self._duration(query)
            if action == "calendar.update_event" and not re.search(r"\bfor\s+\d+", query, re.I):
                if existing is None:
                    try:
                        existing = self.tool_registry.invoke("calendar.event", {"calendar_id": "primary", "event_id": event_id}, agent_name=self.name).get("event", {})
                    except Exception:
                        return {}, "I could not read the event's duration before rescheduling it."
                try:
                    duration = datetime.fromisoformat(str(existing["end"]).replace("Z", "+00:00")) - datetime.fromisoformat(str(existing["start"]).replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    return {}, "Please specify the duration for this event."
            payload["start"] = start.isoformat()
            payload["end"] = (start + duration).isoformat()
            payload["time_zone"] = self._timezone_name(account)
        elif action == "calendar.create_event":
            return {}, "CalendarAgent needs an unambiguous date and start time."
        return payload, ""

    def _time_proposal(self, action: str, payload: dict, availability: dict) -> SpecialistResponse:
        proposal = availability.get("proposed")
        if not proposal:
            return self._blocked("That time overlaps another event. I could not find a daytime slot in the next seven days. Which day should I check?")
        changed = {**payload, **proposal}
        preview = self._preview(action, changed)
        return SpecialistResponse(agent=self.name, status="blocked", confidence=1.0,
            summary=f"That time overlaps another calendar event. You're free {self._display_time(proposal['start'], str(proposal.get('time_zone') or ''))} to {self._display_time(proposal['end'], str(proposal.get('time_zone') or ''))}. Does that time work? Confirm to book it.",
            action_request={"action": action, "payload": changed, "preview": preview},
            structured_payload={"availability": availability},
            analysis="Checked live calendar availability; the suggested time is awaiting confirmation.")

    @staticmethod
    def _natural_title(query: str, action: str) -> str:
        verb = r"(?:schedule|create|add|book)" if action == "calendar.create_event" else r"(?:delete|remove|cancel|reschedule|move|update|rename|change)"
        match = re.search(rf"\b{verb}\s+(?:(?:a|an|the|my)\s+)?(?:(?:calendar\s+)?(?:event|meeting|appointment)\s+(?:called|named|titled)\s+)?(.+)", query, re.I)
        if not match: return ""
        title = re.split(r"\s+(?:today|tomorrow|on|at|from|for|to)\b", match.group(1), maxsplit=1, flags=re.I)[0].strip()
        title = re.sub(r"\s+(?:in|on)\s+(?:my\s+)?(?:google\s+)?calendar.*$", "", title, flags=re.I).strip()
        return "" if re.fullmatch(r"(?:a\s+)?(?:meeting|event|appointment)(?:\s+sometime)?", title, re.I) else title[:1024]

    @staticmethod
    def _display_time(value: str, time_zone: str = "") -> str:
        try:
            if len(value)==10:
                return datetime.fromisoformat(value).strftime("%a %d %b") + " (all day)"
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if time_zone: stamp = stamp.astimezone(ZoneInfo(time_zone))
            return stamp.strftime("%a %d %b, %I:%M %p").replace(", 0", ", ") + " " + str(stamp.tzname() or "")
        except ValueError:
            return value

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
            if "afternoon" in lowered:
                return start.replace(hour=12), start.replace(hour=18)
            if "morning" in lowered:
                return start.replace(hour=6), start.replace(hour=12)
            if "evening" in lowered:
                return start.replace(hour=18), start.replace(hour=22)
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
            return f"Delete {payload.get('summary') or payload.get('event_id')} from {payload.get('calendar_label') or 'Google Calendar'}."
        verb = "Create" if action == "calendar.create_event" else "Update"
        title = payload.get("summary") or payload.get("event_id")
        when = f" from {CalendarAgent._display_time(str(payload.get('start')), str(payload.get('time_zone') or ''))} to {CalendarAgent._display_time(str(payload.get('end')), str(payload.get('time_zone') or ''))}" if payload.get("start") else ""
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
        if type(exc).__name__ == "GoogleCalendarAPIError":
            message = str(exc).casefold()
            if "not found" in message:
                summary = "That event was not found on this calendar. Find it again so I can use the current event ID."
            elif "insufficient" in message or "authorization" in message:
                summary = "Google Calendar rejected the change. Check that this calendar is writable and the Calendar connection has event access."
            elif "unreachable" in message:
                summary = "Google Calendar could not be reached. No change was completed. You can retry the same action."
        return SpecialistResponse(
            agent=self.name,
            status="error",
            summary=summary,
            analysis=f"Calendar connector failed: {type(exc).__name__}.",
            confidence=0.2,
        )
