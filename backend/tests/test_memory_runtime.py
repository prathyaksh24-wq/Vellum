from agent.memory import runtime


def test_memory_runtime_returns_one_process_wide_orchestrator(monkeypatch):
    sentinel = object()
    runtime.set_memory_orchestrator(None)
    monkeypatch.setattr(runtime, "build_memory_orchestrator", lambda: sentinel)

    first = runtime.get_memory_orchestrator()
    second = runtime.get_memory_orchestrator()

    assert first is sentinel
    assert second is sentinel
    runtime.set_memory_orchestrator(None)
