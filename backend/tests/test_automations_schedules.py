import pytest

from agent.automations.schedules import ScheduleParseError, parse_schedule


def test_relative_delay_parses_minutes() -> None:
    record = parse_schedule("30m")
    assert record.kind == "relative"
    assert record.value == 30
    assert record.unit == "minutes"
    assert record.seconds == 1800


def test_relative_delay_parses_long_units() -> None:
    assert parse_schedule("2h").seconds == 7200
    assert parse_schedule("1d").seconds == 86400
    assert parse_schedule("2w").seconds == 1209600
    assert parse_schedule("45 min").unit == "minutes"
    assert parse_schedule("1 day").seconds == 86400


def test_interval_parses_without_time_of_day() -> None:
    record = parse_schedule("every 2h")
    assert record.kind == "interval"
    assert record.value == 2
    assert record.unit == "hours"
    assert record.at_time is None


def test_interval_parses_with_time_of_day() -> None:
    record = parse_schedule("every 1d at 09:00")
    assert record.kind == "interval"
    assert record.at_time == "09:00"

    early = parse_schedule("every 1 day at 6:05")
    assert early.at_time == "06:05"


def test_interval_rejects_time_of_day_on_hourly() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule("every 2h at 09:00")


def test_interval_rejects_bad_time_of_day() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule("every 1d at 24:00")


def test_cron_parses_five_field() -> None:
    record = parse_schedule("0 9 * * *")
    assert record.kind == "cron"
    assert record.expression == "0 9 * * *"


def test_cron_rejects_garbage() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule("61 9 * * *")
    with pytest.raises(ScheduleParseError):
        parse_schedule("0 9 * *")


def test_iso_parses_zulu() -> None:
    record = parse_schedule("2026-08-03T09:00:00Z")
    assert record.kind == "iso"
    assert record.run_at is not None
    assert record.run_at.startswith("2026-08-03T09:00:00")


def test_iso_parses_naive_as_utc() -> None:
    record = parse_schedule("2026-08-03T09:00:00")
    assert record.run_at.endswith("+00:00")


def test_iso_rejects_garbage() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule("not-a-date")


def test_empty_expression_rejected() -> None:
    with pytest.raises(ScheduleParseError):
        parse_schedule("   ")


def test_canonical_dict_round_trip_fields() -> None:
    record = parse_schedule("every 2h")
    as_dict = record.to_dict()
    assert as_dict == {"kind": "interval", "expression": "every 2h", "value": 2, "unit": "hours", "seconds": 7200}
