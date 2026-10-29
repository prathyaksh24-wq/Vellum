"""Date constraints must survive request planning and account history retrieval."""
from datetime import UTC, datetime

from agent.contracts.youtube_requests import clear_read_request
from agent.plugins.youtube_browser_history import history_day
from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
import asyncio
import time
import pytest


def test_monday_constraint_is_not_dropped_by_request_parser():
    request = clear_read_request('what did I watch on Monday?')
    assert request.day_label == 'Monday'


def test_weekday_history_heading_resolves_to_recent_day():
    assert history_day('Monday', now=datetime(2026,10,8,tzinfo=UTC), timezone='Asia/Kolkata') == '2026-10-05'


@pytest.mark.parametrize('label,expected', [('2 Oct','2026-10-02'), ('1 October','2026-10-01'), ('31 Dec','2025-12-31')])
def test_actual_browser_day_first_month_headings_are_durable_dates(label, expected):
    assert history_day(label, now=datetime(2026,10,9,tzinfo=UTC), timezone='Asia/Kolkata') == expected


@pytest.mark.parametrize('text,expected', [('what did I watch on 2026-10-05?', '2026-10-05'),
    ('show my watch history last Monday', 'Last Monday')])
def test_date_text_preserves_day_without_confusing_year_with_list_quantity(text, expected):
    request = clear_read_request(text)
    assert request.day_label == expected and request.limit == 20


def test_day_followup_keeps_history_context_and_filters(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=lambda:{
        'available':True, 'provider':'browser', 'refreshed_at':'2026-10-08T10:00:00Z',
        'items':[{'video_id':'abcdefghijk', 'title':'Monday video', 'day_label':'Monday', 'channel_title':'Creator'},
                 {'video_id':'abcdefghij0', 'title':'Today video', 'day_label':'Today', 'channel_title':'Creator'}]})
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=service)
    response = agent.answer_with_context('what about Monday?', {'at':time.time(),
        'account_request':{'source':'history', 'creator':'Creator', 'limit':2}})
    assert 'Monday video' in response.summary and 'Today video' not in response.summary
    assert response.structured_payload['youtube_account']['request']['day_label'] == 'Monday'


def test_date_query_combines_only_verified_account_saved_matches(tmp_path, monkeypatch):
    from agent.knowledge.store import KnowledgeStore
    from agent.plugins import youtube_browser_history
    store = KnowledgeStore(tmp_path/'core.db', tmp_path/'blobs')
    packets = iter([
        {'status':'ready', 'account_id':'a'*64, 'items':[{'video_id':'abcdefghijk', 'title':'Saved Monday', 'day_label':'Monday'}]},
        {'status':'ready', 'account_id':'a'*64, 'items':[{'video_id':'abcdefghij0', 'title':'Today', 'day_label':'Today'}]},
        {'status':'empty', 'account_id':'b'*64, 'items':[]}])
    reader = youtube_browser_history.YouTubeBrowserHistoryService(store=store, browser_reader=lambda:next(packets),
        clock=lambda:datetime(2026,10,8,tzinfo=UTC))
    reader.refresh()
    monkeypatch.setattr(youtube_browser_history, 'YouTubeBrowserHistoryService', lambda:reader)
    service = YoutubeCapabilityService(vault_root=tmp_path)
    result = service.watch_history({'day_label':'Monday'})
    assert [row['title'] for row in result['items']] == ['Saved Monday']
    assert result['saved_matches'] == 1
    assert service.watch_history({'day_label':'Monday'})['items'] == []


def test_uncaptured_day_is_honest_instead_of_claiming_an_empty_day(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=lambda:{
        'available':True, 'provider':'browser', 'refreshed_at':'2026-10-08T10:00:00Z',
        'items':[{'video_id':'abcdefghijk','title':'Today video','day_label':'Today'}]})
    result = YoutubeAgent(vault_root=tmp_path, youtube_service=service).answer('what did I watch Monday?')
    assert result.status == 'needs_fetch' and "haven't captured" in result.summary
    assert '2026-10-05' in result.summary and 'Today video' not in result.summary


def test_history_date_matches_resolved_days_and_empty_day_is_bounded(tmp_path):
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=lambda:{
        'available':True, 'provider':'browser', 'timezone':'Asia/Kolkata', 'refreshed_at':'2026-10-08T10:00:00Z',
        'truncated':False, 'items':[
            {'video_id':'abcdefghijk', 'title':'Monday video', 'day_label':'Oct 5, 2026', 'history_day':'2026-10-05'},
            {'video_id':'abcdefghij0', 'title':'Today video', 'day_label':'Today', 'history_day':'2026-10-08'}]})
    monday = service.watch_history({'day_label':'Monday'})
    assert [row['title'] for row in monday['items']] == ['Monday video']
    yesterday = service.watch_history({'day_label':'Yesterday'})
    assert yesterday['items'] == [] and yesterday['requested_day'] == '2026-10-07'


def test_targeted_reader_scrolls_past_newer_entries_without_filling_the_100_row_limit():
    from agent.mcp.youtube_history import read_history_page
    class Page:
        url = 'https://www.youtube.com/feed/history'
        step = 0
        async def evaluate(self, _script):
            day = ['Today', 'Yesterday', 'Monday', 'Sunday'][self.step]
            return {'signed_in':True, 'identity':'fixture-account', 'timezone':'Asia/Kolkata',
                'items':[{'video_id':f'video{i:06d}', 'title':f'Video {i}', 'day_label':day} for i in range(100)], 'empty':False}
        async def wait_for_timeout(self, _time): pass
        async def wheel(self, *_): self.step = min(self.step + 1, 3)
        @property
        def mouse(self): return self
    result = asyncio.run(read_history_page(Page(), day_label='Monday', now=datetime(2026,10,8,tzinfo=UTC)))
    assert result['requested_day'] == '2026-10-05'
    assert len(result['items']) == 100 and all(item['day_label'] == 'Monday' for item in result['items'])
