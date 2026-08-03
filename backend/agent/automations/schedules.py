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

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from croniter import croniter


class ScheduleParseError(ValueError):
    """Raised when a schedule expression cannot be understood."""


_RELATIVE_RE = re.compile(r"^\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\s*$", re.I)
_INTERVAL_RE = re.compile(
    r"^\s*every\s+(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\s*"
    r"(?:\s+at\s+(\d{1,2}):(\d{2})\s*)?$",
    re.I,
)

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
        return record


def _unit_seconds(label: str) -> int:
    return _UNIT_SECONDS[label.lower()[0]]


def _canonical_unit(label: str) -> str:
    return _UNIT_LABEL[label.lower()[0]]


def _parse_iso(expression: str) -> ScheduleRecord:
    text = expression.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleParseError(
            f"invalid ISO timestamp {expression!r}; expected e.g. '2026-08-03T09:00:00Z'"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
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
    unit = _canonical_unit(match.group(2))
    return ScheduleRecord(
        kind="relative",
        expression=expression.strip(),
        value=value,
        unit=unit,
        seconds=value * _unit_seconds(match.group(2)),
    )


def _parse_interval(expression: str) -> ScheduleRecord:
    match = _INTERVAL_RE.match(expression)
    if match is None:
        raise ScheduleParseError(
            f"invalid interval {expression!r}; expected e.g. 'every 2h', 'every 1d at 09:00'"
        )
    value = int(match.group(1))
    unit = _canonical_unit(match.group(2))
    at_time: str | None = None
    if match.group(3) is not None:
        hour = int(match.group(3))
        minute = int(match.group(4))
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
        seconds=value * _unit_seconds(match.group(2)),
        at_time=at_time,
    )


def _looks_like_cron(expression: str) -> bool:
    text = expression.strip()
    return len(text.split()) == 5 and not text.lower().startswith("every")


def _parse_cron(expression: str) -> ScheduleRecord:
    text = expression.strip()
    try:
        croniter(text, datetime.now(timezone.utc))
    except (ValueError, KeyError) as exc:
        raise ScheduleParseError(f"invalid cron expression {text!r}") from exc
    return ScheduleRecord(kind="cron", expression=text)


def parse_schedule(expression: str) -> ScheduleRecord:
    """Parse a user schedule expression into a canonical record."""
    text = expression.strip()
    if not text:
        raise ScheduleParseError("schedule expression cannot be empty")
    if text.lower().startswith("every"):
        return _parse_interval(text)
    if _looks_like_cron(text):
        return _parse_cron(text)
    if _RELATIVE_RE.match(text) is not None:
        return _parse_relative(text)
    return _parse_iso(text)
