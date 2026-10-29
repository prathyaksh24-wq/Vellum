import asyncio

from agent import api as api_mod


def test_music_learning_never_ingests_provider_results(monkeypatch):
    calls = []
    class Store:
        def get_settings(self):
            return {'memory_enabled':True, 'save_new_memories':True, 'dreaming_enabled':False}
    class Memory:
        store = Store()
        def extract_memory_candidates(self, **kwargs):
            calls.append(kwargs)
            return []
        def record_turn(self, **kwargs):
            raise AssertionError('Spotify results must not enter memory models or indexes')
    monkeypatch.setattr(api_mod, '_memory_orchestrator', Memory())
    asyncio.run(api_mod._background_learn('I like instrumental music when working',
        'Spotify returned PRIVATE LISTENING HISTORY', thread_id='music', agent_name='MusicAgent'))
    assert calls == [{'thread_id':'music', 'user_message':'I like instrumental music when working',
                      'assistant_message':'', 'agent_name':'MusicAgent'}]
    asyncio.run(api_mod._background_learn('I like instrumental music when working',
        'Spotify returned PRIVATE LISTENING HISTORY', thread_id='music', agent_name='VellumAgent', tools=[{'name':'spotify_playback'}]))
    assert len(calls) == 2 and calls[-1] == calls[0]


def test_explicit_music_memory_is_not_duplicated_by_background_learning(monkeypatch):
    class Memory:
        store = None
        def extract_memory_candidates(self, **kwargs):
            raise AssertionError('Explicit preference already saved')
    monkeypatch.setattr(api_mod, '_memory_orchestrator', Memory())
    asyncio.run(api_mod._background_learn('remember I prefer quiet music', 'Remembered', agent_name='MusicAgent'))


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
