import asyncio
import json

import pytest

from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_browser_history import YouTubeBrowserHistoryService, HistoryReadError


def snapshot(account='a', title='Actual video'):
    return {'status':'ready', 'account_id':account * 64,
        'items':[{'video_id':'abcdefghijk', 'title':title, 'channel_title':'Real creator',
                  'channel_id':'UC-test', 'day_label':'Today'}], 'coverage':'recent_page', 'truncated':False}


def test_refresh_keeps_accounts_separate_and_marks_private_local_only(tmp_path):
    store = KnowledgeStore(tmp_path/'core.db', tmp_path/'blobs')
    reads = iter([snapshot(), snapshot('b', 'Other account video')])
    service = YouTubeBrowserHistoryService(store=store, browser_reader=lambda:next(reads))
    first, second = service.refresh(), service.refresh()
    assert first['source_id'] != second['source_id']
    assert second['items'][0]['title'] == 'Other account video'
    assert first['freshness'] == 'browser_refresh' and first['local_only']
    source = store.get_source(first['source_id'], include_content=True)
    assert source['account_id'] == 'a'*64
    assert source['sensitivity'] == 'private_local_only' and source['external_policy'] == 'deny_raw'


@pytest.mark.parametrize('status', ['signed_out', 'account_unknown', 'page_unreadable', 'account_changed'])
def test_failed_refresh_never_returns_previous_account_snapshot(tmp_path, status):
    reads = iter([snapshot(), {'status':status, 'items':[]}])
    service = YouTubeBrowserHistoryService(store=KnowledgeStore(tmp_path/'core.db', tmp_path/'blobs'),
        browser_reader=lambda:next(reads))
    service.refresh()
    with pytest.raises(HistoryReadError):
        service.refresh()


def test_empty_history_is_a_valid_fresh_account_snapshot(tmp_path):
    value = {**snapshot(), 'status':'empty', 'items':[]}
    result = YouTubeBrowserHistoryService(store=KnowledgeStore(tmp_path/'core.db', tmp_path/'blobs'),
        browser_reader=lambda:value).refresh()
    assert result['available'] and result['total'] == 0


def test_browser_parser_preserves_verified_links_and_never_returns_raw_identity():
    from agent.mcp.youtube_history import read_history_page
    class Page:
        url = 'https://www.youtube.com/feed/history'
        async def evaluate(self, _script):
            return {'signed_in':True, 'identity':'private-account-identity', 'empty':False,
                'items':[{'video_id':'abcdefghijk', 'title':'Observed title', 'channel_title':'Creator',
                    'channel_id':'UC-real', 'day_label':'Today'}]}
        async def wait_for_timeout(self, _time): pass
    result = asyncio.run(read_history_page(Page(), scroll_limit=0))
    assert result['status'] == 'ready'
    assert len(result['account_id']) == 64
    assert 'private-account-identity' not in json.dumps(result)
    assert result['items'][0]['url'] == 'https://www.youtube.com/watch?v=abcdefghijk'


def test_browser_parser_rejects_mid_read_account_changes():
    from agent.mcp.youtube_history import read_history_page
    class Page:
        url = 'https://www.youtube.com/feed/history'
        calls = 0
        async def evaluate(self, _script):
            self.calls += 1
            return {'signed_in':True, 'identity':str(self.calls), 'empty':True, 'items':[]}
        async def wait_for_timeout(self, _time): pass
    assert asyncio.run(read_history_page(Page(), scroll_limit=0))['status'] == 'account_changed'


def test_youtube_agent_uses_browser_history_and_retains_displayed_link_order(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    reads = []
    def history():
        reads.append(True)
        return {'available':True, 'provider':'browser', 'local_only':True, 'total':3,
            'refreshed_at':'2026-10-07T10:00:00Z', 'coverage':'recent_page', 'source_id':'src-history',
            'items':[{'video_id':f'abcdefghij{i}', 'title':f'Current account video {i}', 'day_label':'Today'} for i in range(3)]}
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=history,
        takeout_history_backend=lambda *_args:pytest.fail('Fresh history must not read Takeout'),
        search_backend=lambda *_args:pytest.fail('Personal history must not search public videos'))
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=service)
    first = agent.answer_with_context('what are the last 3 videos I watched?', {})
    assert first.status == 'answered' and first.summary.count('https://www.youtube.com/watch?v=') == 3
    assert 'browser just now' in first.summary and 'full watch history' in first.summary
    second = agent.answer_with_context('give me the link to the second video', agent.thread_context(first, {}))
    assert 'watch?v=abcdefghij1' in second.summary and len(reads) == 1


def test_history_failure_is_honest_and_never_uses_takeout_or_public_search(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    def fail(): raise HistoryReadError('Sign into YouTube in Browser.')
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=fail,
        takeout_history_backend=lambda *_args:pytest.fail('No archive fallback'),
        search_backend=lambda *_args:pytest.fail('No public fallback'))
    result = YoutubeAgent(vault_root=tmp_path, youtube_service=service).answer('what did I recently watch?')
    assert result.status == 'needs_fetch' and 'Sign into YouTube' in result.summary


def test_refresh_action_uses_same_history_service_and_returns_content_free_receipt(tmp_path):
    from agent.plugins.youtube_controls import YouTubeControlService
    store = KnowledgeStore(tmp_path/'core.db', tmp_path/'blobs')
    factory = lambda:YouTubeBrowserHistoryService(store=store, browser_reader=snapshot)
    result = YouTubeControlService(history_factory=factory).execute('youtube.history.refresh', {})
    assert result['changed'] and result['history']['total'] == 1
    assert 'Actual video' not in json.dumps(result)


def test_history_capability_is_not_a_raw_browser_tool_for_the_main_agent(tmp_path):
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    from agent.tools.registry import ToolPermissionError
    registry = YoutubeCapabilityService(vault_root=tmp_path).build_registry()
    with pytest.raises(ToolPermissionError):
        registry.invoke('youtube.watch_history', {}, agent_name='VellumAgent')


@pytest.mark.parametrize('payload', [{'url':'https://example.com'}, {'limit':0}, {'day_label':'Last week'}])
def test_invalid_history_arguments_are_rejected_before_browser_read(tmp_path, payload):
    from pydantic import ValidationError
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    service = YoutubeCapabilityService(vault_root=tmp_path,
        browser_history_backend=lambda:pytest.fail('Invalid arguments must not read the browser'))
    with pytest.raises(ValidationError):
        service.watch_history(payload)


def test_yesterday_filter_and_channel_projection_apply_before_display_limit(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    items = [{'video_id':f'abcdefghij{i}', 'title':f'Video {i}', 'channel_title':f'Creator {i%2}',
        'day_label':'Yesterday' if i>0 else 'Today'} for i in range(4)]
    service = YoutubeCapabilityService(vault_root=tmp_path,
        browser_history_backend=lambda:{'available':True,'provider':'browser','total':4,'items':items})
    result = YoutubeAgent(vault_root=tmp_path, youtube_service=service).answer('name 2 channels from videos I watched yesterday')
    assert result.summary.count('Creator') == 2 and 'Video 0' not in result.summary
    assert 'Video 1' not in result.summary and 'recent channels' in result.summary


@pytest.mark.parametrize('fail', [False, True])
def test_background_read_preserves_visible_tab_and_closes_temporary_tab(monkeypatch, fail):
    from agent.mcp.dedicated_browser import DedicatedBrowser
    from agent.mcp import youtube_history
    browser = DedicatedBrowser()
    visible = object()
    closed = []
    class Page:
        async def close(self):
            closed.append(True)
            browser._page_closed(self)
    class Context:
        async def new_page(self):
            page = Page()
            browser._pages['temporary'] = page
            browser.active_page = page
            return page
    async def open_browser():
        browser.context = Context()
        browser.control = 'agent'
        browser.active_page = visible
        browser._pages['visible'] = visible
    async def navigate(page, url):
        assert browser.active_page is visible
    async def read(page, **kwargs):
        assert browser.active_page is visible
        if fail:
            raise ValueError('Read failed')
        return snapshot()
    monkeypatch.setattr(browser, 'open', open_browser)
    monkeypatch.setattr(browser, '_goto', navigate)
    monkeypatch.setattr(youtube_history, 'read_history_page', read)
    if fail:
        with pytest.raises(ValueError, match='Read failed'):
            asyncio.run(browser.youtube_history())
    else:
        assert asyncio.run(browser.youtube_history())['status'] == 'ready'
    assert browser.active_page is visible and closed == [True]
    assert list(browser._pages) == ['visible']
    assert browser.presentation_requested is False


def test_verified_ordinal_link_does_not_depend_on_model_availability(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    agent = YoutubeAgent(vault_root=tmp_path, planner=lambda *_args:pytest.fail('Exact saved link needs no model'))
    result = agent.answer('give me the link to the second video', context={
        'account_request':{'source':'history','view':'videos'},
        'account_items':[{'video_id':'abcdefghij0','title':'First'},{'video_id':'abcdefghij1','title':'Second'}]})
    assert result.status == 'answered' and 'watch?v=abcdefghij1' in result.summary


def test_history_creator_filter_uses_creator_not_video_title(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    service = YoutubeCapabilityService(vault_root=tmp_path, browser_history_backend=lambda:{
        'available':True,'provider':'browser','items':[{'video_id':'abcdefghijk', 'title':'A different title',
            'channel_title':'Actual Creator'}]})
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=service,
        planner=lambda *_args:{'source':'history','creator':'Actual Creator','limit':3})
    result = agent.answer('show videos by Actual Creator from my watch history')
    assert result.status == 'answered' and 'A different title' in result.summary
