import pytest
from agent.contracts.voice import DictationTranscript
from agent.voice.history import DictationStore


def transcript(text='A completed draft.',language='kn',requested='auto'):
    return DictationTranscript(text=text,language=language,requested_language=requested,duration_seconds=2.5,device='cuda')


def test_completed_text_and_language_survive_restart_without_audio(tmp_path):
    path=tmp_path/'voice/dictation.db'
    store=DictationStore(path)
    identity=store.save(transcript())
    restarted=DictationStore(path)
    page=restarted.history()
    assert page.total==1 and page.items[0].id==identity
    assert page.items[0].language=='kn' and page.items[0].requested_language=='auto'
    assert page.language_counts=={'kn':1}
    assert {p.name for p in path.parent.iterdir()}=={'dictation.db'}
    assert 'audio' not in page.items[0].model_dump()


def test_preference_patch_persists_and_off_stops_new_entries_without_erasing_old(tmp_path):
    store=DictationStore(tmp_path/'dictation.db')
    store.save(transcript())
    store.update_preferences({'language':'kn'})
    store.update_preferences({'save_history':False})
    assert DictationStore(store.path).preferences().language=='kn'
    assert DictationStore(store.path).preferences().save_history is False
    assert store.save(transcript('Not retained.')) is None
    assert store.history().total==1
    store.update_preferences({'save_history':True})
    assert store.save(transcript('Retained.'))
    assert store.history().total==2


def test_pagination_search_language_filter_and_delete_are_exact(tmp_path):
    store=DictationStore(tmp_path/'dictation.db')
    first=store.save(transcript('Kannada 22 piece 100%'))
    second=store.save(transcript('English sample','en','en'))
    assert store.history(limit=1).items[0].id==second
    assert store.history(offset=1,limit=1).items[0].id==first
    assert store.history(query='100%').total==1
    assert store.history(language='kn').total==1
    assert store.delete(entry_id=first)==1
    assert store.delete(entry_id=first)==0
    assert store.history().language_counts=={'en':1}
    assert store.delete(all=True)==1
    assert store.history().total==0


@pytest.mark.parametrize('patch',[{'language':'xx'},{'save_history':'false'},{'unknown':True},{}])
def test_invalid_preferences_do_not_mutate_saved_values(tmp_path,patch):
    store=DictationStore(tmp_path/'dictation.db')
    with pytest.raises(ValueError):store.update_preferences(patch)
    assert store.preferences().save_history is True


def test_blank_text_is_not_history_and_delete_requires_explicit_target(tmp_path):
    store=DictationStore(tmp_path/'dictation.db')
    assert store.save(transcript('  ')) is None
    for command in ({},{'entry_id':'../escape'},{'entry_id':'a'*32,'all':True},{'all':'true'}):
        with pytest.raises(ValueError):store.delete(**command)


def test_history_delete_requires_existing_confirmation_and_cannot_be_replayed(tmp_path):
    from agent import api
    from agent.app_actions.models import AppActionContext,AppActionRequest
    from agent.app_actions.runtime import AppActionRuntime
    store=DictationStore(tmp_path/'dictation.db')
    identity=store.save(transcript())
    original=api._settings_runtime_actions._dictation_store_provider
    api._settings_runtime_actions._dictation_store_provider=lambda:store
    try:
        runtime=AppActionRuntime(settings_runtime_handler=api._settings_runtime_actions.execute)
        request=AppActionRequest(action_id='dictation.history.delete',arguments={'all':True})
        context=AppActionContext(source='ui')
        pending=runtime.dispatch(request,context)
        assert pending.status=='confirmation_required'
        assert store.history().total==1
        receipt=runtime.confirm(pending.confirmation.token,request,context)
        assert receipt.status=='applied' and store.history().total==0
        store.save(transcript('A newer transcript.'))
        runtime.confirm(pending.confirmation.token,request,context)
        assert store.history().total==1
    finally:
        api._settings_runtime_actions._dictation_store_provider=original


def test_every_recording_survives_restart_and_confirmed_deletion_removes_audio(tmp_path):
    store=DictationStore(tmp_path/'dictation.db')
    identities=[store.save(transcript(f'Recording {i}'),b'RIFF'+bytes([i])) for i in range(25)]
    restarted=DictationStore(store.path)
    page=restarted.history(limit=100)
    assert page.total==25 and all(item.has_recording for item in page.items)
    assert restarted.recording(identities[0])==b'RIFF'+bytes([0])
    assert restarted.delete(entry_id=identities[0])==1
    assert restarted.recording(identities[0]) is None
    assert restarted.recording(identities[-1]) is not None
    assert restarted.delete(all=True)==24
    with restarted.connection() as db:
        assert db.execute('SELECT count(*) FROM recordings').fetchone()[0]==0


def test_dictionary_and_shortcuts_persist_normalize_and_preserve_omitted_fields(tmp_path):
    store=DictationStore(tmp_path/'dictation.db')
    store.update_preferences({'dictionary':[' Vellum  AI ','vellum ai','ಕನ್ನಡ'], 'toggle_shortcut':'Alt+Ctrl+Q'})
    result=store.update_preferences({'hold_shortcut':'Shift+Ctrl+D'})
    assert result.toggle_shortcut=='Ctrl+Alt+Q' and result.hold_shortcut=='Ctrl+Shift+D'
    assert result.dictionary==['vellum ai','ಕನ್ನಡ']
    assert DictationStore(store.path).preferences()==result


@pytest.mark.parametrize('patch',[
    {'dictionary':['']},{'dictionary':['x'*101]},{'dictionary':['word']*101},
    {'toggle_shortcut':'D'},{'toggle_shortcut':'Shift+D'},{'toggle_shortcut':'Ctrl+Ctrl+D'},
    {'toggle_shortcut':'Shift+Ctrl+V'},{'toggle_shortcut':'Meta+Shift+G'},
    {'hold_shortcut':'Ctrl+Shift+D'},{'toggle_shortcut':'Alt+F4'},
])
def test_invalid_dictionary_or_conflicting_shortcuts_leave_saved_settings_unchanged(tmp_path,patch):
    store=DictationStore(tmp_path/'dictation.db')
    before=store.preferences()
    with pytest.raises(ValueError):store.update_preferences(patch)
    assert store.preferences()==before
