from __future__ import annotations

from types import SimpleNamespace

from agent.scheduler import digest


def test_youtube_projection_runs_when_other_scheduler_jobs_are_disabled(
    monkeypatch,
    tmp_path,
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
    from agent.automations import api as automations_api
    from agent.automations.store import AutomationStore

    store = AutomationStore(tmp_path / "automations")
    automations_api.set_store(store)
    scheduler = FakeScheduler()

    result = digest.start_scheduler(scheduler=scheduler)

    assert result is scheduler
    assert scheduler.started is True
    records = {r["builtin_key"]: r for r in store.list()}
    assert records["youtube_intelligence_projection"]["state"] == "active"
    registered = {options["id"] for _func, _trigger, options in scheduler.jobs}
    assert f"automation-{records['youtube_intelligence_projection']['id']}" in registered
    assert f"automation-{records['nightly_digest']['id']}" not in registered
    assert f"automation-{records['vault_retention']['id']}" not in registered
