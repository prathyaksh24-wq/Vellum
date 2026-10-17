import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from agent.app_actions.models import AppActionContext
from agent.graph import agent as graph
from agent.personalization import personalization_scope, request_personalization, recording_reference_allowed
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry
from agent.tools.app_actions import app_action, app_action_session, drain_app_action_events
from test_app_action_settings_runtime import make_runtime


@pytest.fixture
def prompt(monkeypatch):
    model = SimpleNamespace(id='test/model',label='Test model',tool_calling_compatibility='compatible')
    monkeypatch.setattr(graph, 'get_provider_registry', lambda:SimpleNamespace(current_model=lambda:model))
    monkeypatch.setattr(graph, '_get_project_ctx', lambda:SimpleNamespace(build=lambda *a:'Private profile evidence'))
    monkeypatch.setattr(graph, '_get_skill_registry', lambda:None)
    monkeypatch.setattr(graph, 'build_skill_activation_block', lambda *a,**k:'')
    monkeypatch.setattr(graph, 'get_agent_catalog', lambda:SimpleNamespace(specialist_skill_ids=lambda:set()))
    monkeypatch.setattr(graph, '_specialist_directory_block', lambda:'')
    monkeypatch.setattr('agent.memory.memory_context.build_memory_block', lambda *a,**k:'Private memory evidence')
    return lambda query:graph.vellum_prompt({'messages':[HumanMessage(content=query)]},{'configurable':{'thread_id':'prefs'}})[0].content


def test_personalization_controls_reach_the_actual_model_prompt(prompt):
    with personalization_scope({'baseStyle':'efficient','warm':'less','enthusiastic':'less','headers':'less','emoji':'less','nickname':'Reader','occupation':'Designer','about':'Learning Python','custom':'Use short examples.','fastAnswers':False}, 'Help me learn Python'):
        system = prompt('Help me learn Python')
    for phrase in ('concise and practical', 'neutral tone', 'avoid hype', 'Prefer connected prose', 'Avoid emojis', 'Reader', 'Designer', 'Learning Python', 'Use short examples.'):
        assert phrase in system


def test_fast_answers_skip_private_context_for_general_facts_but_not_personal_requests(prompt):
    with personalization_scope({'fastAnswers':True}, 'Why is the sky blue?'):
        assert 'Private memory evidence' not in prompt('Why is the sky blue?')
        assert 'Private profile evidence' not in prompt('Why is the sky blue?')
    with personalization_scope({'fastAnswers':True}, 'What do my notes say?'):
        assert 'Private memory evidence' in prompt('What do my notes say?')
    with personalization_scope({'fastAnswers':True}, 'Why is the sky blue?'):
        assert 'Private memory evidence' not in prompt('Why is the sky blue?\n\n[Recent Vellum conversation context]\nUser: I am a designer.')


def test_preferences_do_not_leak_between_requests(prompt):
    with personalization_scope({'custom':'UNIQUE-PREF-ALPHA'}, 'Hello'):
        assert 'UNIQUE-PREF-ALPHA' in prompt('Hello')
    assert 'UNIQUE-PREF-ALPHA' not in prompt('Hello')


def test_automatic_web_search_is_enforced_by_the_actual_tool_registry():
    calls=[]
    registry=ToolRegistry()
    registry.register(CapabilityRecord(name='web_search',namespace='web',access=CapabilityAccess.READ,allowed_agents=frozenset({'VellumAgent'}),stream_label='Search',adapter=lambda payload:calls.append(payload) or 'results'))
    with personalization_scope({'webSearch':False}, 'Explain this idea'):
        with pytest.raises(ToolPermissionError,match='Automatic web search is off'):
            registry.invoke('web_search',{'query':'private idea'},agent_name='VellumAgent')
    assert calls == []
    with personalization_scope({'webSearch':False}, 'Search the web for this idea'):
        assert registry.invoke('web_search',{'query':'requested search'},agent_name='VellumAgent') == 'results'


def test_direct_search_and_specialist_search_respect_automatic_search_preference(monkeypatch):
    from agent.tools import web
    from agent.personalization import tool_preference_error
    calls=[]
    monkeypatch.setattr(web,'provider_chain',lambda _:calls.append('network') or [])
    with personalization_scope({'webSearch':False},'Explain the latest result'):
        assert tool_preference_error('sports.web_search','sports')
        result=json.loads(web.web_search.invoke({'query':'latest result'}))
    assert result['success'] is False and 'Automatic web search is off' in result['error']
    assert calls==[]


def test_record_history_filter_keeps_regular_notes():
    with personalization_scope({'recordHist':False}):
        assert not recording_reference_allowed({'source_type':'transcript'})
        assert not recording_reference_allowed({'path':'Recordings/meeting.md'})
        assert recording_reference_allowed({'path':'Projects/design.md'})


def test_explicit_search_button_can_override_the_automatic_search_preference():
    from agent.personalization import tool_preference_error
    with personalization_scope({'webSearch':False}, 'Find recent information', explicit_web_search=True):
        assert tool_preference_error('web_search','web') is None


def test_connector_search_preference_blocks_automatic_reads_but_respects_explicit_calendar_requests():
    from agent.personalization import tool_preference_error
    with personalization_scope({'connector':False}, 'What should I work on?'):
        assert tool_preference_error('calendar.events','calendar')
    with personalization_scope({'connector':False}, 'Check my calendar'):
        assert tool_preference_error('calendar.events','calendar') is None


def test_mixed_action_patch_changes_preferences_for_the_same_turn():
    context=AppActionContext(source='nlp',device_settings={'values':{'personalization':{'warm':'less'}}})
    receipt=SimpleNamespace(status='applied',result={'device_settings_patch':{'values':{'personalization':{'warm':'more'}}}})
    assert request_personalization(context,[receipt])['warm'] == 'more'


def test_model_action_tool_uses_canonical_receipts_and_advances_the_device_snapshot():
    runtime,*_=make_runtime()
    context=AppActionContext(source='nlp',device_settings={'values':{'background':'galaxy'}})
    with app_action_session(context,'settings-chat',runtime):
        catalog=json.loads(app_action.invoke({'operation':'list','query':'appearance'}))
        assert any(action['id']=='settings.device.update' for action in catalog['actions'])
        changed=json.loads(app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'patch':{'background':'next'}}}))
        previous=json.loads(app_action.invoke({'operation':'execute','action_id':'settings.device.inspect'}))
        restored=json.loads(app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'patch':{'background':'previous'}}}))
        events=drain_app_action_events()
    assert changed['status']=='applied' and restored['status']=='applied'
    assert previous['result']['previous_background']=='galaxy'
    assert restored['result']['device_settings_patch']['values']['background']=='galaxy'
    assert len(events)==3


def test_model_action_tool_never_accepts_secrets_or_bypasses_confirmation():
    runtime,*_=make_runtime()
    with app_action_session(AppActionContext(source='nlp'),'settings-chat',runtime):
        blocked=json.loads(app_action.invoke({'operation':'execute','action_id':'provider.credential.configure','arguments':{'provider':'openai','secret':'not-a-real-secret'}}))
        pending=json.loads(app_action.invoke({'operation':'execute','action_id':'memory.settings.update','arguments':{'patch':{'memory_enabled':False}}}))
    assert blocked['status']=='blocked'
    assert 'not-a-real-secret' not in json.dumps(blocked)
    assert pending['status']=='confirmation_required'


@pytest.mark.asyncio
async def test_nonstream_response_returns_the_actual_model_action_receipt(monkeypatch):
    from agent import api
    runtime,*_=make_runtime()
    monkeypatch.setattr(api,'_app_action_runtime',runtime)
    async def run(*args,**kwargs):
        app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'patch':{'personalization':{'warm':'less'}}}})
        return api.ChatResponse(answer='Updated.',thread_id='prefs')
    monkeypatch.setattr(api,'_run_agent_scoped',run)
    response=await api._run_agent('Be less warm','prefs',app_action_context=AppActionContext(source='nlp'))
    assert len(response.action_receipts)==1
    assert response.action_receipts[0].status=='applied'
    assert response.action_receipts[0].result['device_settings_patch']['values']['personalization']['warm']=='less'


def test_streamed_model_action_reaches_the_frontend_receipt_contract(monkeypatch):
    from agent import api
    from test_chat_stream_sources import _run_stream, _parse_sse
    runtime,*_=make_runtime()
    monkeypatch.setattr(api,'_app_action_runtime',runtime)
    class ActionAgent:
        async def astream_events(self,*args,**kwargs):
            yield {'event':'on_tool_start','name':'app_action','data':{'input':{'operation':'execute'}}}
            result=app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'patch':{'background':'next'}}})
            yield {'event':'on_tool_end','name':'app_action','data':{'output':result}}
            yield {'event':'on_chat_model_stream','name':'RoutedChatModel','data':{'chunk':SimpleNamespace(content='Background updated.')}}
        async def aclose(self):
            pass
    events=_parse_sse(_run_stream(monkeypatch,ActionAgent()))
    receipt=json.loads(next(data for name,data in events if name=='app.action.receipt'))
    assert receipt['turn_kind']=='mixed'
    assert receipt['receipt']['status']=='applied'
    assert receipt['receipt']['result']['device_settings_patch']['revision']==1


def test_failed_model_setting_change_cannot_turn_into_a_success_claim_and_can_retry():
    from agent.tools.app_actions import app_action_result_guard
    runtime,*_=make_runtime()
    with app_action_session(AppActionContext(source='nlp'),'settings-chat',runtime):
        found=json.loads(app_action.invoke({'operation':'list','query':'personality emojis'}))
        assert any(item['id']=='settings.device.update' for item in found['actions'])
        failed=json.loads(app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'description':'stop emojis'}}))
        assert failed['status']=='failed' and 'argument_schema' in failed
        assert 'Unknown device setting' in app_action_result_guard()
        applied=json.loads(app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'patch':{'personalization':{'emoji':'less'}}}}))
        assert applied['status']=='applied'
        assert app_action_result_guard() is None


def test_model_can_discover_with_inspect_text_and_use_an_exact_catalog_id_in_query():
    from agent.tools.app_actions import app_action_result_guard
    runtime,*_=make_runtime()
    with app_action_session(AppActionContext(source='nlp'),'settings-chat',runtime):
        discovered=json.loads(app_action.invoke({'operation':'inspect','query':'personality settings'}))
        assert any(item['id']=='settings.device.update' for item in discovered['actions'])
        schema=json.loads(app_action.invoke({'operation':'inspect','query':'settings.device.update'}))
        assert schema['id']=='settings.device.update'
        receipt=json.loads(app_action.invoke({'operation':'execute','query':'settings.device.update','arguments':{'patch':{'personalization':{'emoji':'none'}}}}))
        assert receipt['status']=='applied'
        assert receipt['result']['device_settings_patch']['values']['personalization']['emoji']=='less'
        assert app_action_result_guard() is None


def test_stream_does_not_publish_a_false_completion_after_a_failed_settings_tool(monkeypatch):
    from agent import api
    from test_chat_stream_sources import _run_stream, _parse_sse
    runtime,*_=make_runtime()
    monkeypatch.setattr(api,'_app_action_runtime',runtime)
    class FailedActionAgent:
        async def astream_events(self,*args,**kwargs):
            result=app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'description':'stop emojis'}})
            yield {'event':'on_tool_end','name':'app_action','data':{'output':result}}
            yield {'event':'on_chat_model_stream','name':'RoutedChatModel','data':{'chunk':SimpleNamespace(content='I have updated your preferences.')}}
        async def aclose(self):
            pass
    events=_parse_sse(_run_stream(monkeypatch,FailedActionAgent()))
    answer=json.loads(next(data for name,data in events if name=='final'))['answer']
    assert 'Unknown device setting' in answer
    assert 'I have updated' not in '\n'.join(data for name,data in events if name in {'token','response.output_text.delta','final'})


@pytest.mark.parametrize('feature',['canvas','advVoice'])
def test_unimplemented_features_do_not_return_a_false_applied_receipt(feature):
    runtime,*_=make_runtime()
    with app_action_session(AppActionContext(source='nlp'),'settings-chat',runtime):
        result=json.loads(app_action.invoke({'operation':'execute','action_id':'settings.device.update','arguments':{'patch':{'personalization':{feature:True}}}}))
    assert result['status']=='unavailable'
    assert not result['result'].get('device_settings_patch')
