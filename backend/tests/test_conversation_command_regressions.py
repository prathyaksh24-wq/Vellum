from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent import api
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.session_controls import MODEL_SELECT_ACTION_ID
from test_app_action_settings_runtime import make_runtime, context
from test_app_action_session_controls import make_runtime as session_runtime


@pytest.mark.parametrize('query,action', [
    ('chnage the background', 'settings.device.update'),
    ('change the bg', 'settings.device.update'),
    ('can u chnage the bg of vellum', 'settings.device.update'),
    ('turn on drak mode', 'ui.surface.configure'),
    ('switch from dark to light mode', 'ui.surface.configure'),
    ('chnage the model provider to openai', MODEL_SELECT_ACTION_ID),
    ('enable a pet', 'petdex.visibility.set'),
    ('chnage warmth to more', 'settings.device.update'),
    ('disable web search', 'settings.device.update'),
    ('change my nickname to Test Person', 'settings.device.update'),
    ('chnage my profile name to Test Person', 'settings.device.update'),
])
def test_reported_natural_commands_reach_existing_actions(query, action):
    runtime, *_ = make_runtime()
    request = runtime.match_submission(query)
    assert request is not None
    assert request.action_id == action


def test_background_previous_survives_the_device_snapshot():
    runtime, *_ = make_runtime()
    original = context().model_copy(update={'device_settings': {'version':1,'revision':0,'values':{'background':'galaxy'}}})
    changed = runtime.dispatch(runtime.match_submission('change the background'), original)
    values = {**original.device_settings['values'], **changed.result['device_settings_patch']['values']}
    assert values['previous_background'] == 'galaxy'
    next_context = original.model_copy(update={'device_settings': {'version':1,'revision':1,'values':values}})
    restored = runtime.dispatch(runtime.match_submission('restore the previous background'), next_context)
    assert restored.status == 'applied'
    assert restored.result['device_settings_patch']['values']['background'] == 'galaxy'


@pytest.mark.parametrize('query,zone', [
    ('time in netherlands', 'CEST'), ('what is it tiime in belgium', 'CEST'),
])
def test_actual_clock_messages_use_the_country_timezone(query, zone):
    answer = api._current_datetime_answer(query, now=datetime(2026,10,15,8,tzinfo=timezone.utc))
    assert answer and '10:00 AM' in answer and zone in answer


def test_configured_provider_switch_changes_the_thread_model(tmp_path):
    runtime, state = session_runtime(tmp_path)
    service = runtime._session_control_handler.__self__
    service.provider_registry.models.append(SimpleNamespace(id='openai/test-model',label='OpenAI test model',provider='openai'))
    receipt = runtime.dispatch(AppActionRequest(action_id=MODEL_SELECT_ACTION_ID, arguments={'provider':'openai'}), AppActionContext(source='nlp',invocation_conversation_id='provider-chat'))
    assert receipt.status == 'applied'
    assert state.get('provider-chat').selected_model == 'openai/test-model'


def test_missing_provider_key_requests_secure_entry_and_resumes_the_same_thread(tmp_path):
    runtime, state = session_runtime(tmp_path)
    service = runtime._session_control_handler.__self__
    receipt = runtime.dispatch(AppActionRequest(action_id=MODEL_SELECT_ACTION_ID, arguments={'provider':'openai'}), AppActionContext(source='nlp',invocation_conversation_id='provider-chat'))
    assert receipt.status == 'applied'
    assert receipt.result['client_effect']['focus'] == 'provider-key-openai'
    assert state.get('provider-chat').selected_model == ''
    service.provider_registry.models.append(SimpleNamespace(id='openai/test-model',label='OpenAI test model',provider='openai'))
    resumed = service.resume_provider_selection('openai', AppActionContext(source='ui',invocation_conversation_id='provider-chat'))
    assert resumed['model']['id'] == 'openai/test-model'
    assert state.get('provider-chat').selected_model == 'openai/test-model'
    assert state.get('other-chat').selected_model == ''


def test_saving_the_requested_key_resumes_selection_only_after_confirmation(tmp_path):
    runtime, state = session_runtime(tmp_path)
    service = runtime._session_control_handler.__self__
    setting_runtime,*_ = make_runtime()
    settings_service = setting_runtime._settings_runtime_handler.__self__
    saved=[]
    def write(provider, secret):
        saved.append(provider)
        service.provider_registry.models.append(SimpleNamespace(id='openai/test-model',label='OpenAI test model',provider='openai'))
    settings_service._credential_writer = write
    settings_service._provider_selection_resumer = service.resume_provider_selection
    ctx=AppActionContext(source='ui',invocation_conversation_id='provider-chat')
    runtime.dispatch(AppActionRequest(action_id=MODEL_SELECT_ACTION_ID,arguments={'provider':'openai'}),ctx)
    request=AppActionRequest(action_id='provider.credential.configure',arguments={'provider':'openai','secret':'fixture-only-key'})
    receipt=setting_runtime.dispatch(request,ctx)
    assert receipt.status == 'confirmation_required'
    assert saved == [] and state.get('provider-chat').selected_model == ''
    confirmed=setting_runtime.confirm(receipt.confirmation.token,request,ctx)
    assert confirmed.status == 'applied'
    assert confirmed.result['session_control_patch']['model_id'] == 'openai/test-model'
    assert confirmed.result['session_control_conversation_id'] == 'provider-chat'
    assert confirmed.result['provider_selection_resumed'] is True
    assert state.get('provider-chat').selected_model == 'openai/test-model'
    assert 'fixture-only-key' not in confirmed.model_dump_json()


def test_generic_previous_background_followup_uses_the_actual_previous_command(monkeypatch):
    runtime,*_=make_runtime()
    monkeypatch.setattr(api,'_app_action_runtime',runtime)
    monkeypatch.setattr(api,'_thread_user_messages',lambda *a,**k:['chnage the bg','change back to the previous one'])
    assert api._contextual_presentation_message('change back to the previous one','bg-chat') == 'restore the previous background'
    monkeypatch.setattr(api,'_thread_user_messages',lambda *a,**k:['play some music','change back to the previous one'])
    assert api._contextual_presentation_message('change back to the previous one','bg-chat') == 'change back to the previous one'


def test_spelling_repair_never_changes_saved_text_or_setting_values():
    from agent.text_normalization import normalize_command_words
    assert normalize_command_words('remember I like drak chocolate') == 'remember I like drak chocolate'
    assert normalize_command_words('chnage my custom instructions to use drak chocolate as an example') == 'change my custom instructions to use drak chocolate as an example'


@pytest.mark.parametrize('value', ['"drak theme"', '“drak theme”', '"" drak theme', 'TO drak theme', 'to\u2003drak theme'])
def test_spelling_repair_preserves_the_first_protected_value(value):
    from agent.text_normalization import normalize_command_words
    assert normalize_command_words('chnage ' + value) == 'change ' + ' '.join(value.split())


def test_unmatched_quotes_do_not_hide_the_remaining_command():
    from agent.text_normalization import normalize_command_words
    assert normalize_command_words('chnage “drak theme') == 'change “dark theme'


def test_many_unmatched_quotes_preserve_the_entire_normalized_message():
    from agent.text_normalization import normalize_command_words
    quotes = '“' * 100_000
    assert normalize_command_words('chnage ' + quotes) == 'change ' + quotes


def test_profile_name_change_uses_the_saved_device_owner_and_response_context():
    from agent.personalization import request_personalization
    runtime,*_=make_runtime()
    ctx=context().model_copy(update={'device_settings':{'version':1,'revision':0,'values':{'profile':{'displayName':'Old Name','username':'unchanged'}}}})
    receipt=runtime.dispatch(runtime.match_submission('chnage my profile name to Test Person'),ctx)
    assert receipt.status=='applied'
    assert receipt.result['device_settings_patch']['values']['profile']=={'displayName':'Test Person','username':'unchanged'}
    assert request_personalization(ctx,[receipt])['nickname']=='Test Person'
