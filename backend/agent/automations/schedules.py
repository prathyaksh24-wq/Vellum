"""Schedule parsing for automations.

Accepts four natural formats (matching Hermes and the design spec):

- relative delay: ``30m`` / ``2h`` / ``1d`` / ``2w``  (one-shot)
- interval: ``every 2h``, ``every 30m``, ``every 1d at 09:00``  (recurring)
- 5-field cron: ``0 9 * * *``  (recurring, validated via croniter)
- ISO timestamp: ``2026-08-03T09:00:00Z``  (one-shot)

Every accepted expression parses to a canonical record the scheduler can
turn into an APScheduler trigger; garbage input raises ``ScheduleParseError``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter


class ScheduleParseError(ValueError):
    """Raised when a schedule expression cannot be understood."""


_RELATIVE_RE = re.compile(r"^\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\s*$", re.I)

_UNIT_SECONDS = {
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}
_UNIT_LABEL = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


@dataclass(frozen=True)
class ScheduleRecord:
    kind: str
    expression: str
    value: int | None = None
    unit: str | None = None
    seconds: int | None = None
    at_time: str | None = None
    run_at: str | None = None
    time_zone: str | None = None
    end_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        record: dict[str, object] = {"kind": self.kind, "expression": self.expression}
        if self.value is not None:
            record["value"] = self.value
        if self.unit is not None:
            record["unit"] = self.unit
        if self.seconds is not None:
            record["seconds"] = self.seconds
        if self.at_time is not None:
            record["at_time"] = self.at_time
        if self.run_at is not None:
            record["run_at"] = self.run_at
        if self.time_zone is not None:
            record["time_zone"] = self.time_zone
        if self.end_at is not None:
            record["end_at"] = self.end_at
        return record


def _unit_seconds(label: str) -> int:
    return _UNIT_SECONDS[label.lower()[0]]


def _canonical_unit(label: str) -> str:
    return _UNIT_LABEL[label.lower()[0]]


def _parse_iso(expression: str, zone=None) -> ScheduleRecord:
    text = expression.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleParseError(
            f"invalid ISO timestamp {expression!r}; expected e.g. '2026-08-03T09:00:00Z'"
        ) from exc
    if parsed.tzinfo is None:
        wall_time = parsed
        parsed = wall_time.replace(tzinfo=zone or timezone.utc)
        if zone is not None:
            if parsed.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall_time:
                raise ScheduleParseError("This clock time does not exist in the selected time zone.")
            if parsed.utcoffset() != parsed.replace(fold=1).utcoffset():
                raise ScheduleParseError("This clock time occurs twice. Use a timestamp with an explicit UTC offset.")
    elif zone is not None:
        raise ScheduleParseError("Specify either a time zone or a UTC offset for this timestamp.")
    return ScheduleRecord(
        kind="iso",
        expression=text,
        run_at=parsed.isoformat(),
    )


def _parse_relative(expression: str) -> ScheduleRecord:
    match = _RELATIVE_RE.match(expression)
    if match is None:
        raise ScheduleParseError(
            f"invalid relative delay {expression!r}; expected e.g. '30m', '2h', '1d', '2w'"
        )
    value = int(match.group(1))
    if not 1 <= value <= 999_999:
        raise ScheduleParseError("Delay must be between 1 and 999999 units.")
    unit = _canonical_unit(match.group(2))
    return ScheduleRecord(
        kind="relative",
        expression=expression.strip(),
        value=value,
        unit=unit,
        seconds=value * _unit_seconds(match.group(2)),
    )


def _parse_interval(expression: str) -> ScheduleRecord:
    tokens = expression.strip()[5:].strip().split()
    if not tokens:
        raise ScheduleParseError(
            f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
        )

    quantity = tokens.pop(0)
    if quantity.isdecimal():
        value_text = quantity
        if not tokens:
            raise ScheduleParseError(
                f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
            )
        unit_text = tokens.pop(0)
    else:
        split_at = next((index for index, char in enumerate(quantity) if not char.isdecimal()), 0)
        value_text = quantity[:split_at]
        unit_text = quantity[split_at:]
        if not value_text or not unit_text:
            raise ScheduleParseError(
                f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
            )
    if not value_text.isdecimal() or len(value_text) > 9:
        raise ScheduleParseError(
            f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
        )
    value = int(value_text)
    if not 1 <= value <= 999_999:
        raise ScheduleParseError("Interval must be between 1 and 999999 units.")
    try:
        unit = _canonical_unit(unit_text)
        seconds = value * _unit_seconds(unit_text)
    except (IndexError, KeyError):
        raise ScheduleParseError(
            f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
        ) from None

    at_time: str | None = None
    if tokens:
        if len(tokens) != 2 or tokens[0].casefold() != "at":
            raise ScheduleParseError(
                f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
            )
        clock = tokens[1]
        clock_parts = clock.split(":")
        if (
            len(clock_parts) != 2
            or len(clock_parts[0]) > 2
            or len(clock_parts[1]) != 2
            or not all(part.isdecimal() for part in clock_parts)
        ):
            raise ScheduleParseError(f"invalid time-of-day {clock!r} in {expression!r}")
        hour = int(clock_parts[0])
        minute = int(clock_parts[1])
        if hour > 23 or minute > 59:
            raise ScheduleParseError(f"invalid time-of-day {hour:02d}:{minute:02d} in {expression!r}")
        at_time = f"{hour:02d}:{minute:02d}"
        if unit not in ("days", "weeks"):
            raise ScheduleParseError("time-of-day 'at HH:MM' is only valid for day/week intervals")
    return ScheduleRecord(
        kind="interval",
        expression=expression.strip(),
        value=value,
        unit=unit,
        seconds=seconds,
        at_time=at_time,
    )


def _looks_like_cron(expression: str) -> bool:
    text = expression.strip()
    return len(text.split()) == 5 and not text.lower().startswith("every")


def _parse_cron(expression: str) -> ScheduleRecord:
    return ScheduleRecord(kind="cron", expression=expression.strip())


def cron_trigger(expression: str, *, zone=timezone.utc, end_at=None):
    """Use standard cron weekdays (0/7 Sunday) and day-of-month/day-of-week OR."""
    try:
        minute, hour, day, month, _ = expression.split()
        expanded, nth_weekdays = croniter.expand(expression)
        if nth_weekdays:
            raise ValueError("nth weekday syntax is unsupported")
        weekdays = expanded[4]
        names = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
        weekday = "*" if weekdays == ["*"] else ",".join(names[value % 7] for value in weekdays)
        day = "last" if day.lower() == "l" else day
        options = {"minute": minute, "hour": hour, "month": month, "timezone": zone, "end_date": end_at}
        if day != "*" and weekday != "*":
            return OrTrigger([CronTrigger(day=day, **options), CronTrigger(day_of_week=weekday, **options)])
        return CronTrigger(day=day, day_of_week=weekday, **options)
    except (ValueError, KeyError) as exc:
        raise ScheduleParseError(f"invalid or unsupported cron expression {expression!r}") from exc


def parse_schedule(expression: str) -> ScheduleRecord:
    """Parse a user schedule expression into a canonical record."""
    text = expression.strip()
    if not text:
        raise ScheduleParseError("schedule expression cannot be empty")
    body, _, end_date = text.partition(" until ")
    body, _, zone_name = body.partition(" @ ")
    body, zone_name = body.strip(), zone_name.strip()
    try:
        zone = ZoneInfo(zone_name) if zone_name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleParseError(f"Unknown time zone {zone_name!r}. Use a name like Asia/Kolkata.") from exc
    if body.casefold().startswith("every "):
        record = _parse_interval(body)
    elif _looks_like_cron(body):
        record = _parse_cron(body)
    elif _RELATIVE_RE.match(body) is not None:
        record = _parse_relative(body)
    else:
        record = _parse_iso(body, zone if zone_name else None)
    if zone_name and record.kind not in {"cron", "iso"}:
        raise ScheduleParseError("Use a time zone with a calendar schedule or a one-time date.")
    end_at = None
    if end_date:
        if record.kind != "cron" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_date.strip()):
            raise ScheduleParseError("End dates require a calendar schedule and a YYYY-MM-DD date.")
        try:
            end_at = datetime.fromisoformat(end_date.strip() + "T23:59:59").replace(tzinfo=zone)
        except ValueError as exc:
            raise ScheduleParseError("Choose a valid end date.") from exc
    if record.kind == "cron":
        cron_trigger(body, zone=zone, end_at=end_at)
    return replace(record, time_zone=zone_name or None, end_at=end_at.isoformat() if end_at else None)
