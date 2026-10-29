"""Regressions from the signed-in user's activity conversation."""
import time

import pytest

from agent.agents.youtube import YoutubeAgent
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService


def activity_agent(tmp_path, *, planner=None, count=6):
    reads = []
    def history():
        reads.append(True)
        return {'available':True, 'provider':'browser', 'local_only':True,
            'refreshed_at':'2026-10-09T05:30:00Z', 'timezone':'Asia/Kolkata',
            'items':[{'video_id':f'video{i:06d}', 'title':f'Chess game review {i}',
                'channel_title':'Chess Creator' if i < 4 else 'Other Creator',
                'day_label':'Today' if i < 3 else 'Monday'} for i in range(count)]}
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=history,
        search_backend=lambda *_:pytest.fail('Personal activity reached public search'),
        personal_context_backend=lambda *_:pytest.fail('Browser account activity reached an unrelated imported account'))
    return YoutubeAgent(vault_root=tmp_path, youtube_service=service, planner=planner), reads


def test_repeated_link_keeps_the_selected_item_without_planning_or_refresh(tmp_path):
    agent, reads = activity_agent(tmp_path, count=70)
    first = agent.answer_with_context('show 100 videos from my watch history', {})
    context = agent.thread_context(first, {})
    selected = agent.answer_with_context('give the video link to the 64th one', context)
    context = agent.thread_context(selected, context)
    agent.planner = lambda *_:pytest.fail('A selected link needs no model')
    repeat = agent.answer_with_context('the video link please', context)
    assert 'watch?v=video000063' in repeat.summary
    assert 'video000000' not in repeat.summary
    assert len(reads) == 1


def test_ambiguous_link_does_not_guess_first_item(tmp_path):
    agent, reads = activity_agent(tmp_path, planner=lambda *_: {'source':'previous','view':'link','index':1})
    context = {'at':time.time(), 'account_items':[{'video_id':'video000000'}, {'video_id':'video000001'}],
        'account_request':{'source':'history','view':'videos'}}
    response = agent.answer_with_context('the video link please', context)
    assert response.status == 'needs_fetch' and 'which' in response.summary.lower()
    assert not reads


@pytest.mark.parametrize('query', ['what is the latest video i watched?', 'what did i watch on Monday?'])
def test_clear_history_read_does_not_wait_for_model_interpreter(tmp_path, query):
    agent, reads = activity_agent(tmp_path, planner=lambda *_:pytest.fail('Clear history needs no model'))
    response = agent.answer_with_context(query, {})
    assert response.status == 'answered'
    assert reads
    if 'latest' in query:
        assert response.summary.count('watch?v=') == 1
    else:
        assert 'video000003' in response.summary and 'video000000' not in response.summary


def test_trends_and_analysis_followup_use_counted_browser_evidence(tmp_path):
    agent, reads = activity_agent(tmp_path, planner=lambda *_:pytest.fail('Activity analysis needs no intent model'))
    response = agent.answer_with_context('what is the trend u are seeing from my yt watch history', {})
    assert response.status == 'answered'
    assert 'Chess Creator' in response.summary and '4' in response.summary
    assert '2026-10-05' in response.summary and '2026-10-09' in response.summary
    assert 'chess' in response.summary.lower()
    context = agent.thread_context(response, {})
    followup = agent.answer_with_context('what is ur analysis based on that', context)
    assert followup.status == 'answered' and 'Chess Creator' in followup.summary
    assert 'duration' in followup.summary.lower()
    assert len(reads) == 2


def test_capabilities_question_is_answered_without_fetch_or_model(tmp_path):
    agent, reads = activity_agent(tmp_path, planner=lambda *_:pytest.fail('Capabilities need no model'))
    response = agent.answer_with_context('what else can YT agent do for me?', {})
    assert response.status == 'answered'
    assert 'history' in response.summary.lower() and 'liked' in response.summary.lower()
    assert not reads


def test_my_youtube_data_defaults_to_current_browser_account(tmp_path):
    agent, reads = activity_agent(tmp_path)
    response = agent.answer_with_context('what can u tell me about my youtube data', {})
    assert response.status == 'answered' and 'Chess Creator' in response.summary
    assert len(reads) == 1


def test_summary_retains_selected_link_and_supports_bare_summary_followup(tmp_path):
    agent, reads = activity_agent(tmp_path)
    first = agent.answer_with_context('show my watch history', {})
    context = agent.thread_context(first, {})
    selected = agent.answer_with_context('link to the fourth video', context)
    context = agent.thread_context(selected, context)
    summary = agent.answer_with_context('give me a summary', context)
    assert 'most represented channels' in summary.summary
    context = agent.thread_context(summary, context)
    repeat = agent.answer_with_context('the video link please', context)
    assert 'watch?v=video000003' in repeat.summary
    assert len(reads) == 2


def test_retry_now_preserves_latest_history_request(tmp_path):
    agent, reads = activity_agent(tmp_path)
    first = agent.answer_with_context('what is the latest video i watched?', {})
    response = agent.answer_with_context('check again now?', agent.thread_context(first, {}))
    assert response.status == 'answered' and response.summary.count('watch?v=') == 1
    assert len(reads) == 2


def test_day_followup_accepts_on_monday(tmp_path):
    agent, _ = activity_agent(tmp_path)
    first = agent.answer_with_context('what did I watch today?', {})
    response = agent.answer_with_context('what about on Monday?', agent.thread_context(first, {}))
    assert response.status == 'answered' and 'video000003' in response.summary
    assert 'video000000' not in response.summary


def test_analysis_accumulates_only_the_freshly_verified_account(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from agent.knowledge.store import KnowledgeStore
    from agent.plugins import youtube_browser_history as history
    store = KnowledgeStore(tmp_path/'core.db', tmp_path/'blobs')
    def packet(account, i):
        return {'status':'ready', 'account_id':account*64, 'items':[
            {'video_id':f'video{i:06d}', 'title':f'Account video {i}', 'channel_title':f'Account {account}', 'day_label':'Today'}]}
    packets = iter([packet('a', 0), packet('b', 1), packet('a', 2), {'status':'signed_out'}])
    reader = history.YouTubeBrowserHistoryService(store=store, browser_reader=lambda:next(packets),
        clock=lambda:datetime(2026,10,9,tzinfo=UTC))
    reader.refresh()
    reader.refresh()
    monkeypatch.setattr(history, 'YouTubeBrowserHistoryService', lambda:reader)
    service = YoutubeCapabilityService(vault_root=tmp_path)
    result = service.watch_history({'limit':100, 'include_accumulated':True})
    assert {item['video_id'] for item in result['items']} == {'video000000','video000002'}
    assert result['total'] == 2 and result['coverage'] == 'fresh_and_accumulated'
    saved = next(item for item in result['items'] if item['video_id'] == 'video000000')
    assert saved['day_label'] == '2026-10-09'
    with pytest.raises(history.HistoryReadError):
        service.watch_history({'include_accumulated':True})


def test_activity_followups_route_through_the_existing_dispatcher(tmp_path):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    from agent.master.state import MasterThreadStateStore
    from agent.profiles import AgentCatalog
    agent, reads = activity_agent(tmp_path)
    catalog = AgentCatalog(profile_dir=tmp_path/'profiles', executors={'YoutubeAgent':agent})
    state = MasterThreadStateStore(sessions_db=tmp_path/'sessions.db')
    dispatcher = LiveAgentDispatcher(vault_root=tmp_path, agent_catalog=catalog, state_store=state)
    first = dispatcher.maybe_handle('what is the trend u are seeing from my yt watch history', 'activity')
    assert first.agent_name == 'YoutubeAgent' and first.status == 'answered'
    followup = dispatcher.maybe_handle('what is ur analysis based on that', 'activity')
    assert followup.agent_name == 'YoutubeAgent' and followup.status == 'answered'
    assert 'Chess Creator' in followup.answer and len(reads) == 2


def test_invalid_ordinal_keeps_previous_selection_and_list(tmp_path):
    agent, reads = activity_agent(tmp_path, count=70)
    first = agent.answer_with_context('show 100 videos from my watch history', {})
    context = agent.thread_context(first, {})
    selected = agent.answer_with_context('link to the 64th video', context)
    context = agent.thread_context(selected, context)
    invalid = agent.answer_with_context('link to the 100th video', context)
    assert invalid.status == 'needs_fetch' and '70 items' in invalid.summary
    repeat = agent.answer_with_context('the video link please', agent.thread_context(invalid, context))
    assert 'watch?v=video000063' in repeat.summary and len(reads) == 1
