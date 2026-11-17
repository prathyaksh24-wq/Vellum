import asyncio
import threading
import time

from agent.desktop_runtime import start_loop_watchdog


def test_watchdog_records_stacks_when_the_event_loop_stops_answering(tmp_path):
    loop = asyncio.new_event_loop()  # Never run: every ping goes unanswered.
    log = tmp_path / "backend-stall.log"
    stop = start_loop_watchdog(loop, interval=0.05, stall_after=0.1, log_path=log)
    try:
        # Wait for the report itself, not just the file: the watchdog creates
        # the log before it finishes writing, and reading in between saw "".
        deadline = time.monotonic() + 5
        text = ""
        while time.monotonic() < deadline and "Event loop unresponsive" not in text:
            time.sleep(0.05)
            text = log.read_text(encoding="utf-8") if log.exists() else ""
        assert "Event loop unresponsive" in text
        assert "vellum-loop-watchdog" in text or "Thread" in text
        # One stall is reported once, not on every check.
        time.sleep(0.4)
        assert log.read_text(encoding="utf-8").count("Event loop unresponsive") == 1
    finally:
        stop.set()
        loop.close()


def test_watchdog_stays_quiet_for_a_responsive_loop(tmp_path):
    loop = asyncio.new_event_loop()
    runner = threading.Thread(target=loop.run_forever, daemon=True)
    runner.start()
    log = tmp_path / "backend-stall.log"
    stop = start_loop_watchdog(loop, interval=0.05, stall_after=0.5, log_path=log)
    try:
        time.sleep(0.4)
        assert not log.exists()
    finally:
        stop.set()
        loop.call_soon_threadsafe(loop.stop)
        runner.join(2)
        loop.close()


def test_worker_threads_exist_before_requests_need_them():
    from agent.desktop_runtime import prestart_worker_threads

    async def scenario():
        loop = asyncio.get_running_loop()
        await prestart_worker_threads(loop, executor_workers=4, threadpool_workers=3)
        names = [thread.name for thread in threading.enumerate()]
        assert sum(name.startswith("vellum-worker") for name in names) == 4
        # Later work reuses those threads rather than starting new ones.
        before = threading.active_count()
        await asyncio.gather(*(asyncio.to_thread(time.sleep, 0.01) for _ in range(4)))
        assert threading.active_count() == before
        loop._default_executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_embedding_health_never_imports_the_ml_stack(monkeypatch):
    import sys
    from agent import api

    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    assert api._embedding_health()["ok"] is True
    assert "sentence_transformers" not in sys.modules
