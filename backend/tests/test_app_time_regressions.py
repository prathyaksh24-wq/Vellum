from datetime import datetime, timezone

import pytest

from agent import api
from test_app_action_settings_runtime import make_runtime, context
from test_calendar_scheduling import agent


@pytest.mark.parametrize('question', [
    'what is the time in South Korea?', 'what time is it in Seoul?',
    'current date and time in Asia/Seoul',
])
def test_requested_clock_zone_overrides_user_zone(monkeypatch, question):
    monkeypatch.setenv('VELLUM_USER_TIMEZONE', 'Asia/Kolkata')
    answer = api._current_datetime_answer(question, now=datetime(2026, 10, 15, 16, tzinfo=timezone.utc))
    assert '1:00 AM KST' in answer
    assert 'October 16, 2026' in answer
    assert 'IST' not in answer


def test_unknown_clock_location_does_not_return_india_time():
    answer = api._current_datetime_answer('what is the time in Atlantis?')
    assert answer and 'IST' not in answer
    assert 'city' in answer.lower() or 'timezone' in answer.lower()


def test_clock_answer_leads_with_the_requested_time_and_keeps_date_natural():
    answer = api._current_datetime_answer('what time is it in Belgium?', now=datetime(2026,10,15,12,tzinfo=timezone.utc))
    assert answer == "It's 2:00 PM CEST in Belgium on Thursday, October 15, 2026."
    assert 'Today is' not in answer


@pytest.mark.parametrize('suffix', [' right now?!', ' currently!!!', '\u2003today?', ' now', ' ?', ' right now ?!'])
def test_clock_location_and_display_label_share_the_same_suffix_boundary(suffix):
    answer = api._current_datetime_answer('what time is it in Belgium' + suffix, now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
    assert answer == "It's 2:00 PM CEST in Belgium on Thursday, October 15, 2026."


def test_clock_zone_label_does_not_include_space_before_punctuation():
    answer = api._current_datetime_answer('what time is it in utc ?', now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
    assert answer == "It's 12:00 PM UTC in UTC on Thursday, October 15, 2026."


def test_long_unknown_clock_location_returns_clarification():
    assert 'timezone' in api._current_datetime_answer('time in ' + 'a' * 100_000)


@pytest.mark.parametrize('prefix', ['and ', 'what about ', 'how about '])
def test_repeated_followup_prefixes_and_punctuation_keep_the_requested_zone(monkeypatch, prefix):
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: ['what time is it in South Korea?'])
    answer = api._clock_followup_answer(prefix * 5_000 + 'Belgium' + '!' * 10_000, 'clock-thread')
    assert 'CEST in Brussels ' in answer


def test_location_followup_keeps_the_first_explicit_preposition(monkeypatch):
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: ['what time is it in South Korea?'])
    assert 'CEST in Brussels ' in api._clock_followup_answer('in Belgium?!', 'clock-thread')
    assert 'timezone' in api._clock_followup_answer('in in Belgium?!', 'clock-thread')


def test_repeated_articles_in_short_time_followup_do_not_become_a_location(monkeypatch):
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: ['what time is it in South Korea?'])
    assert api._clock_followup_answer('and ' + 'the ' * 10_000 + 'time', 'clock-thread') is None


def test_unrelated_message_does_not_scan_the_saved_archive(monkeypatch):
    def forbidden():
        pytest.fail('Unrelated messages must not load all saved chats')
    monkeypatch.setattr(api, '_read_ui_conversations', forbidden)
    assert api._conversation_recall_answer('hello', 'quick-chat') is None


@pytest.mark.parametrize('followup', ['and the time?', 'no, I meant South Korea', 'it is 1 AM there, you gave me India time'])
def test_clock_followup_keeps_requested_location_and_correction_is_not_a_note(monkeypatch, followup):
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: ['what is the time in South Korea?', followup])
    answer = api._direct_contextual_answer(followup, 'clock-thread')
    assert answer and 'KST' in answer
    assert 'IST' not in answer
    assert 'note' not in answer.lower()
    if not followup.startswith('and'):
        assert 'wrong' in answer.lower() or 'sorry' in answer.lower()


@pytest.mark.parametrize('query', ['change the background', 'can you change my background?', 'switch to a different background'])
def test_unspecified_background_changes_to_another_registered_scene(query):
    runtime, *_ = make_runtime()
    request = runtime.match_submission(query)
    assert request is not None
    receipt = runtime.dispatch(request, context('ui').model_copy(update={
        'device_settings': {'version': 1, 'revision': 2, 'values': {'background': 'galaxy'}},
    }))
    assert receipt.status == 'applied'
    assert receipt.result['device_settings_patch']['values']['background'] != 'galaxy'


@pytest.mark.parametrize('short_day', ['tom', 'tmrw', 'tmr'])
def test_calendar_shorthand_uses_daytime_appointment_hour(short_day):
    calls = []
    cal = agent(calls=calls)
    result = cal.answer(f'book an appointment {short_day} at 3')
    assert result.action_request['payload']['start'] == '2026-10-02T15:00:00+05:30'
    assert result.action_request['payload']['summary'] == 'Appointment'
    assert '3:00 PM' in result.summary
    assert calls == []


def test_explicit_calendar_shorthand_never_books_at_three_am():
    result = agent().answer('book an appointment tom at 3pm')
    assert result.action_request['payload']['start'] == '2026-10-02T15:00:00+05:30'


@pytest.mark.parametrize('clock,expected_hour', [
    ('3 AM', 3), ('03:00', 3), ('3 in the morning', 3),
    ('3 in the afternoon', 15), ('8 in the evening', 20),
    ('8 at night', 20), ('15:00', 15), ('12', 12), ('9', 9),
])
def test_calendar_daytime_default_preserves_explicit_hours(clock, expected_hour):
    result = agent().answer(f'book an appointment tom at {clock}')
    assert datetime.fromisoformat(result.action_request['payload']['start']).hour == expected_hour


def test_calendar_tom_name_is_not_a_relative_date():
    result = agent().answer('book a meeting with Tom tomorrow at 3')
    assert result.action_request['payload']['summary'] == 'meeting with Tom'
    assert 'T15:00:00' in result.action_request['payload']['start']


def test_multiple_clock_followups_keep_the_original_timezone(monkeypatch):
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: [
        'what is the time in South Korea?', 'and the time?', 'no that is wrong',
    ])
    assert 'KST' in api._direct_contextual_answer('no that is wrong', 'clock-thread')


def test_clock_correction_survives_the_shared_continuity_router(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(api, '_live_dispatcher', SimpleNamespace(state_store=SimpleNamespace(get_pending_action=lambda *a: None)))
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: ['what is the time in South Korea?'])
    correction = 'that is wrong, I asked for South Korea'
    resolved = api._continuity_request(correction, 'clock-thread')
    assert resolved == correction
    answer = api._direct_contextual_answer(resolved, 'clock-thread')
    assert 'KST' in answer and 'wrong' in answer


@pytest.mark.parametrize('current', ['galaxy', 'liquid-metal', 'serenox-home'])
def test_background_selection_advances_from_the_current_device_snapshot(current):
    runtime, *_ = make_runtime()
    action_context = context('ui').model_copy(update={
        'device_settings': {'version':1, 'revision':3, 'values':{'background':current}},
    })
    receipt = runtime.dispatch(runtime.match_submission('change the background'), action_context)
    assert receipt.status == 'applied'
    patch = receipt.result['device_settings_patch']
    assert patch['base_revision'] == 3 and patch['revision'] == 4
    assert patch['values']['background'] != current
    assert patch['values']['background'] != 'next'


@pytest.mark.parametrize('zone', ['America/New_York', 'Europe/London'])
@pytest.mark.parametrize('instant', [datetime(2026, 1, 15, 16, tzinfo=timezone.utc), datetime(2026, 7, 15, 16, tzinfo=timezone.utc)])
def test_clock_conversion_uses_timezone_database_daylight_saving(zone, instant):
    from zoneinfo import ZoneInfo
    local = instant.astimezone(ZoneInfo(zone))
    answer = api._current_datetime_answer(f'what time is it in {zone}?', now=instant)
    assert api._format_clock_time(local) in answer
    assert local.tzname() in answer


@pytest.mark.asyncio
async def test_background_chat_stream_uses_the_device_receipt(monkeypatch):
    from agent.app_actions.models import AppActionContext
    import agent.skills.curator_runtime as curator_runtime
    from test_app_action_stream import parse_sse, passthrough
    from types import SimpleNamespace
    runtime, *_ = make_runtime()
    monkeypatch.setattr(api, '_app_action_runtime', runtime)
    monkeypatch.setattr(api, '_audited_turn_stream', passthrough)
    monkeypatch.setattr(curator_runtime, 'get_curator_runtime', lambda: SimpleNamespace(mark_activity=lambda: None))
    async def forbidden(**kwargs):
        pytest.fail('A background command must not fall through to model planning')
        yield ''
    monkeypatch.setattr(api, '_stream_agent_turn', forbidden)
    response = await api.chat_stream(api.ChatRequest(
        message='change the background', thread_id='background-test', store=False,
        action_context=AppActionContext(source='ui', device_settings={'version':1, 'revision':0, 'values':{'background':'galaxy'}}),
    ))
    events = parse_sse(''.join([chunk async for chunk in response.body_iterator]))
    receipt = next(data['receipt'] for name, data in events if name == 'app.action.receipt')
    assert receipt['status'] == 'applied'
    assert receipt['result']['device_settings_patch']['values']['background'] == 'liquid-metal'


@pytest.mark.asyncio
@pytest.mark.parametrize('correction', ['no, I meant South Korea', 'that is wrong, I asked for South Korea'])
async def test_clock_correction_returns_directly_without_model_or_memory_tools(monkeypatch, correction):
    from types import SimpleNamespace
    monkeypatch.setattr(api, '_live_dispatcher', SimpleNamespace(state_store=SimpleNamespace(get_pending_action=lambda *a: None)))
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **kw: ['what is the time in South Korea?'])
    result = await api._run_agent_scoped(correction, 'clock-test', store=False)
    assert 'KST' in result.answer
    assert 'wrong' in result.answer
    assert result.tools == []


@pytest.mark.parametrize('question', ['time in South Korea?', 'what time in Seoul?', 'tell me the time in South Korea'])
def test_short_clock_location_requests_are_understood(question):
    answer = api._current_datetime_answer(question, now=datetime(2026, 10, 15, 16, tzinfo=timezone.utc))
    assert '1:00 AM KST' in answer


@pytest.mark.parametrize('question', ['what is the time of my meeting?', 'what is the time complexity?', 'convert that time to IST'])
def test_clock_shortcut_does_not_preempt_scheduling_or_conversion(question):
    assert api._current_datetime_answer(question) is None
