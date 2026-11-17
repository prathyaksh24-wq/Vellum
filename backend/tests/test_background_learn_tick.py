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

