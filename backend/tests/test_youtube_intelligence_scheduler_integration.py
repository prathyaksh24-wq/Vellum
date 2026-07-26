from __future__ import annotations

from types import SimpleNamespace

from agent.scheduler import digest


def test_youtube_projection_runs_when_other_scheduler_jobs_are_disabled(
    monkeypatch,
) -> None:
    class FakeScheduler:
        def __init__(self) -> None:
            self.jobs = []
            self.started = False

        def add_job(self, func, trigger, **kwargs) -> None:
            self.jobs.append((func, trigger, kwargs))

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(
        digest,
        "get_settings",
        lambda: SimpleNamespace(
            enable_nightly_digest=False,
            enable_vault_retention=False,
        ),
    )
    scheduler = FakeScheduler()

    result = digest.start_scheduler(scheduler=scheduler)

    assert result is scheduler
    assert scheduler.started is True
    assert "youtube_intelligence_projection" in {
        options["id"] for _func, _trigger, options in scheduler.jobs
    }
