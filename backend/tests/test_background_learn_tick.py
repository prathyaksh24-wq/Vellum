import asyncio

from agent import api as api_mod


def test_background_learn_calls_tick(tmp_path, monkeypatch):
    async def run_case():
        await api_mod._background_learn("user typed this", "agent said that", thread_id="t1")

    _setup_background_learn_case(tmp_path, monkeypatch)
    asyncio.run(run_case())
    log = (tmp_path / "Projects" / "fitness" / "log.md").read_text()
    assert "user typed this" in log


def _setup_background_learn_case(tmp_path, monkeypatch):
    """Verify _background_learn appends to the active project's log.md."""
    # Set up an active project so tick has somewhere to write
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    (proj / "hot.md").write_text("<!-- vellum-managed: empty -->\n")
    (proj / "log.md").write_text("")

    from agent.memory.project_context import ProjectContext

    ctx = ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")
    ctx._state.set_active_project("t1", "fitness")

    monkeypatch.setattr(api_mod, "_project_context_singleton", ctx, raising=False)
    monkeypatch.setattr(api_mod, "_project_context", lambda: ctx, raising=False)

    # Stub external dependencies so the call won't hit network/disk side effects
    class FakeHoncho:
        def __init__(self, **kw): pass
        def get_or_create_session(self, t): return "s1"
        def add_message(self, sid, content, role): pass

    monkeypatch.setattr(api_mod, "HonchoMemory", FakeHoncho)

    class FakeFTS:
        def add_qa_pair(self, **kw): pass

    monkeypatch.setattr(api_mod, "_fts5_memory", FakeFTS())

    class FakeDataClass:
        GREEN = "GREEN"
        YELLOW = "YELLOW"
        RED = "RED"

    monkeypatch.setattr(api_mod, "DataClass", FakeDataClass)
    monkeypatch.setattr(api_mod, "classify", lambda q: ("GREEN", ""))
