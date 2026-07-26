from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from agent.scheduler import youtube_intelligence


def test_projection_job_rebuilds_local_youtube_intelligence() -> None:
    calls = []

    class FakeIntelligence:
        def rebuild(self, *, now):
            calls.append(now)
            return {"observations_scanned": 12, "signals_created": 4}

    now = datetime(2026, 7, 23, 2, 30, tzinfo=UTC)
    result = youtube_intelligence.run_projection(intelligence=FakeIntelligence(), now=now)

    assert result == {
        "status": "completed",
        "observations_scanned": 12,
        "signals_created": 4,
    }
    assert calls == [now]


def test_projection_job_registration_is_single_instance_and_coalesced() -> None:
    scheduler = SimpleNamespace(jobs=[])
    scheduler.add_job = lambda func, trigger, **kwargs: scheduler.jobs.append((func, trigger, kwargs))

    youtube_intelligence.install_projection_job(scheduler)

    assert len(scheduler.jobs) == 1
    _func, trigger, options = scheduler.jobs[0]
    assert trigger == "cron"
    assert options["id"] == "youtube_intelligence_projection"
    assert options["hour"] == 2
    assert options["minute"] == 30
    assert options["max_instances"] == 1
    assert options["coalesce"] is True
