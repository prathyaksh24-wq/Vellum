from datetime import datetime
from agent.agents.calendar import CalendarAgent
from agent.agents.live_dispatcher import LiveAgentDispatcher
from agent.master.state import MasterThreadStateStore
from agent.profiles.catalog import AgentCatalog
from agent.tools.capabilities.calendar_service import CalendarCapabilityService


def harness(tmp_path):
    calls=[]
    def events(**kw):
        if kw.get('query') and 'New Appointment' in kw['query'] and kw['calendar_id']=='f1': return []
        if kw['calendar_id']=='f1':
            return [{'id':'f1-session','summary':'Singapore Grand Prix Practice','start':{'dateTime':'2026-10-02T13:30:00+05:30'},'end':{'dateTime':'2026-10-02T14:30:00+05:30'}}]
        return [{'id':'real-event','summary':"30-minute appointment titled 'New Appointment' (or ask",'start':{'dateTime':'2026-10-02T14:00:00+05:30'},'end':{'dateTime':'2026-10-02T14:30:00+05:30'}}]
    svc=CalendarCapabilityService(account_backend=lambda:{'enabled':True,'configured':True,'connected':True,'time_zone':'Asia/Kolkata'},
        calendars_backend=lambda:[{'id':'primary','summary':'Personal','primary':True,'accessRole':'owner'},{'id':'f1','summary':'Formula 1','accessRole':'reader'}],
        events_backend=events,delete_backend=lambda **kw:calls.append(kw) or {'deleted':True,**kw})
    agent=CalendarAgent(tool_registry=svc.build_registry(),now=lambda tz:datetime(2026,10,1,12,tzinfo=tz))
    catalog=AgentCatalog(profile_dir=tmp_path/'profiles',executors={'CalendarAgent':agent})
    state=MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    dispatcher=LiveAgentDispatcher(vault_root=tmp_path/'vault',agent_catalog=catalog,state_store=state)
    return agent,dispatcher,state,calls


def test_synced_f1_is_in_tomorrow_calendar(tmp_path):
    agent,_,_,_=harness(tmp_path)
    response=agent.answer('What is on my calendar tomorrow?')
    assert 'Singapore Grand Prix Practice' in response.summary
    assert any(e.get('calendar_id')=='f1' for e in response.structured_payload['events'])


def test_delete_that_uses_real_event_from_previous_read_and_confirms_once(tmp_path):
    _,dispatcher,state,calls=harness(tmp_path)
    read=dispatcher.maybe_handle('Find "New Appointment" on my calendar tomorrow','chat')
    assert read is not None
    prepared=dispatcher.maybe_handle('delete that','chat')
    assert prepared is not None and state.get_pending_action('chat') is not None
    assert state.get_pending_action('chat')['payload']['event_id']=='real-event'
    result=dispatcher.maybe_handle('yes delete it','chat')
    assert result is not None and 'Deleted' in result.answer
    assert len(calls)==1
    assert state.get_pending_action('chat') is None


def test_pending_delete_repetition_is_confirmation_not_new_preview(tmp_path):
    _,dispatcher,state,calls=harness(tmp_path)
    state.set_pending_action('chat',{'agent':'CalendarAgent','action':'calendar.delete_event','payload':{'calendar_id':'primary','event_id':'real-event','summary':'New Appointment'}})
    result=dispatcher.maybe_handle('yes delete it','chat')
    assert result is not None and 'Deleted' in result.answer
    assert len(calls)==1


def test_context_is_persistent_and_thread_scoped(tmp_path):
    _,dispatcher,state,calls=harness(tmp_path)
    dispatcher.maybe_handle('Find "New Appointment" on my calendar tomorrow','chat')
    restored=MasterThreadStateStore(sessions_db=state.sessions_db)
    assert restored.get_specialist_context('chat','CalendarAgent')['events'][0]['id']=='real-event'
    assert restored.get_specialist_context('other-chat','CalendarAgent')=={}
    assert restored.get_specialist_context('chat','XAgent')=={}


def test_failed_delete_can_retry_same_authorized_target_without_another_preview(tmp_path):
    agent,dispatcher,state,calls=harness(tmp_path)
    original=agent.execute_action_request
    tries=[]
    from agent.agents.base import SpecialistResponse
    def execute(action):
        tries.append(action)
        if len(tries)==1:return SpecialistResponse(agent='CalendarAgent',status='error',summary='Google Calendar is temporarily unavailable.')
        return original(action)
    agent.execute_action_request=execute
    state.set_pending_action('chat',{'agent':'CalendarAgent','action':'calendar.delete_event','payload':{'calendar_id':'primary','event_id':'real-event','summary':'New Appointment'}})
    assert dispatcher.maybe_handle('yes','chat').status=='error'
    assert state.get_pending_action('chat')['confirmed_until']
    assert 'Deleted' in dispatcher.maybe_handle('try again','chat').answer
    assert len(calls)==1 and calls[0]['event_id']=='real-event'
    assert state.get_pending_action('chat') is None


def test_cancel_pending_delete_does_not_delete_it(tmp_path):
    _,dispatcher,state,calls=harness(tmp_path)
    state.set_pending_action('chat',{'agent':'CalendarAgent','action':'calendar.delete_event','payload':{'calendar_id':'primary','event_id':'real-event'}})
    assert 'Canceled' in dispatcher.maybe_handle('cancel it','chat').answer
    assert calls==[]


def test_same_event_id_in_another_calendar_still_blocks_slot(tmp_path):
    agent,_,_,_=harness(tmp_path)
    service=CalendarCapabilityService(calendars_backend=lambda:[{'id':'primary','primary':True},{'id':'f1'}],
        events_backend=lambda **kw:[{'id':'same','start':{'dateTime':'2026-10-02T15:00:00+05:30'},'end':{'dateTime':'2026-10-02T16:00:00+05:30'}}])
    result=service.availability({'calendar_id':'primary','event_id':'same','start':'2026-10-02T15:00:00+05:30','end':'2026-10-02T15:30:00+05:30'})
    assert not result['available'] and result['checked_calendar_ids']==['primary','f1']


def test_api_keeps_retry_text_bound_to_existing_calendar_action(monkeypatch):
    from agent import api
    from types import SimpleNamespace
    state=SimpleNamespace(get_pending_action=lambda thread:{'agent':'CalendarAgent','action':'calendar.delete_event','confirmed_until':'2026-10-01T12:00:00+00:00'})
    monkeypatch.setattr(api,'_live_dispatcher',SimpleNamespace(state_store=state))
    monkeypatch.setattr(api,'_thread_user_messages',lambda *a,**kw:['Delete "Review"','yes','try again'])
    assert api._continuity_request('try again','chat')=='try again'


def test_expired_retry_requires_confirmation_of_same_target(tmp_path):
    _,dispatcher,state,calls=harness(tmp_path)
    state.set_pending_action('chat',{'agent':'CalendarAgent','action':'calendar.delete_event','payload':{'calendar_id':'primary','event_id':'real-event','summary':'New Appointment'},'confirmed_until':'2000-01-01T00:00:00+00:00'})
    assert 'Confirm' in dispatcher.maybe_handle('try again','chat').answer
    assert calls==[]
    assert 'Deleted' in dispatcher.maybe_handle('yes delete it','chat').answer


def test_failed_retry_does_not_authorize_a_different_event(tmp_path):
    _,dispatcher,state,calls=harness(tmp_path)
    state.set_pending_action('chat',{'agent':'CalendarAgent','action':'calendar.delete_event','payload':{'calendar_id':'primary','event_id':'real-event','summary':'New Appointment'},'confirmed_until':'2099-01-01T00:00:00+00:00'})
    dispatcher.maybe_handle('delete another event','chat')
    assert calls==[]


def test_deleting_chat_clears_local_calendar_context_and_pending_authority(tmp_path):
    from agent.memory.sessions import SessionsReader
    _,dispatcher,state,calls=harness(tmp_path)
    dispatcher.maybe_handle('Find "New Appointment" on my calendar tomorrow','chat')
    dispatcher.maybe_handle('delete that','chat')
    reader=SessionsReader(checkpoints_db=tmp_path/'missing.db',sessions_db=state.sessions_db)
    reader.delete('chat')
    assert state.get_specialist_context('chat','CalendarAgent')=={}
    assert state.get_pending_action('chat') is None
