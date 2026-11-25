"""Regressions from the Quote of the day report (2026-11-25).

A Run now executed the agent in a throwaway event loop; the shared async runtime
stayed bound to it, so the next scheduled run and every later chat turn failed with
"... is bound to a different event loop".
"""

from __future__ import annotations

import asyncio
import threading

from agent.automations import server_loop
from agent.automations.builtins import describe_builtin_result
from agent.automations.suggestions import covered_by_task


def test_run_and_wait_uses_the_server_loop_from_a_worker_thread() -> None:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    server_loop.set_server_loop(loop)
    try:
        async def which_loop():
            return asyncio.get_running_loop()

        assert server_loop.run_and_wait(which_loop, timeout=5) is loop
        future = server_loop.submit(which_loop)
        assert future.result(timeout=5) is loop
    finally:
        server_loop.set_server_loop(None)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


def test_run_and_wait_without_a_server_loop_still_runs() -> None:
    server_loop.set_server_loop(None)

    async def answer():
        return 42

    assert server_loop.submit(answer) is None
    assert server_loop.run_and_wait(answer) == 42


def test_lazy_agent_rebuilds_a_runtime_built_on_another_loop(monkeypatch) -> None:
    from agent.graph import agent as agent_module

    built: list[asyncio.AbstractEventLoop] = []

    async def fake_build(model=None, reasoning_mode=None):
        built.append(asyncio.get_running_loop())
        return object()

    monkeypatch.setattr(agent_module, "build_async_agent", fake_build)
    lazy = agent_module.LazyAgent()
    first = asyncio.run(lazy._aget("m"))
    second = asyncio.run(lazy._aget("m"))  # a new loop: the old runtime must not be reused
    assert first is not second
    assert len(built) == 2 and built[0] is not built[1]


def test_builtin_report_says_what_the_job_did() -> None:
    report = describe_builtin_result("Skill curator tick", {
        "summary": "Reviewed skills.", "archived": ["old-skill"], "checked": 12, "ok": True})
    assert "Reviewed skills." in report
    assert "- Checked: 12" in report
    assert "- Archived: 1 — old-skill" in report
    assert describe_builtin_result("Digest", None) == "Digest finished. It reported no details."


def test_suggestions_hide_ideas_an_existing_task_already_covers() -> None:
    tasks = [{"name": "Music Discovery", "instructions": "Every Friday suggest new tracks based on Drake and J. Cole."}]
    assert covered_by_task({"name": "Music discovery", "request": "Weekly tracks"}, tasks)
    assert covered_by_task({"name": "New tracks", "request": "Every Friday at 5pm suggest new tracks based on Drake"}, tasks)
    assert not covered_by_task({"name": "GitHub Health Check", "request": "Every day check failed CI builds"}, tasks)
