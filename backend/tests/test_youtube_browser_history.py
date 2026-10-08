from __future__ import annotations

import json
from datetime import UTC, datetime
import asyncio
import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.contracts.youtube_history import YouTubeHistoryConfig
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_browser_history import (ACTION, ORIGIN, YouTubeBrowserHistory,
    YouTubeBrowserHistoryService, HistoryReadError, history_day)
from agent.mcp.youtube_history_page import read_history



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


def test_worker_routes_fresh_history_to_background_reader(monkeypatch):
    from agent.mcp.playwright_tools import _PlaywrightMcpClient
    from agent.mcp import youtube_history_page

    async def fresh_snapshot():
        return snapshot()

    async def unexpected_configured_read(*_args, **_kwargs):
        pytest.fail('Fresh account history must use the temporary-tab reader')

    worker = _PlaywrightMcpClient()
    worker._dedicated = SimpleNamespace(youtube_history=fresh_snapshot)
    monkeypatch.setattr(youtube_history_page, 'read_history', unexpected_configured_read)
    assert asyncio.run(worker.session('youtube_history'))['status'] == 'ready'


def test_worker_configured_refresh_preserves_closed_and_busy_boundaries(monkeypatch):
    from agent.mcp.playwright_tools import _PlaywrightMcpClient
    from agent.mcp import youtube_history_page

    async def unexpected_read(*_args, **_kwargs):
        pytest.fail('A skipped refresh must not read or launch a browser')

    worker = _PlaywrightMcpClient()
    monkeypatch.setattr(youtube_history_page, 'read_history', unexpected_read)
    arguments = {'url': 'https://www.youtube.com/feed/history', 'automatic': True}
    assert asyncio.run(worker.session('youtube_history', arguments))['status'] == 'browser_closed'
    worker._dedicated = object()
    worker._busy = True
    assert asyncio.run(worker.session('youtube_history', arguments))['status'] == 'browser_busy'

NOW = datetime(2026, 10, 5, 0, 15, tzinfo=UTC)
ENTRY = {"url":"https://www.youtube.com/watch?v=abc123XYZ09", "title":"A video",
    "channel_title":"Creator", "day_label":"Today"}


def service(tmp_path, responses):
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    reader = YouTubeBrowserHistory(store=store,
        browser=lambda *_args: responses.pop(0), clock=lambda: NOW)
    return reader, store


def ready(entries=None, account="account-one"):
    return {"status":"ready", "account_fingerprint":account, "entries":entries or [ENTRY]}


def test_repeat_refresh_is_idempotent_and_preserves_private_day_evidence(tmp_path):
    reader, store = service(tmp_path, [ready(), ready()])
    assert reader.refresh()["status"] == "ready"
    assert reader.refresh()["records"] == 1
    observations = store.list_observation_details(origin=ORIGIN, action=ACTION)
    assert len(observations) == 1
    assert observations[0]["payload"]["history_day"] == "2026-10-05"
    assert observations[0]["payload"]["occurred_at"] == ""
    assert observations[0]["sensitivity"] == "private_local_only"
    assert observations[0]["payload"]["provider"] == ORIGIN
    source = store.get_source(observations[0]["source_id"])
    assert source["external_policy"] == "deny_raw"


def test_failure_and_account_switch_preserve_last_success(tmp_path):
    reader, store = service(tmp_path, [ready(), {"status":"page_changed"}, ready(account="other")])
    succeeded = reader.refresh()["last_success_at"]
    assert reader.refresh()["last_success_at"] == succeeded
    assert reader.status()["status"] == "page_changed"
    assert reader.refresh()["status"] == "account_changed"
    assert store.count_observations(origin=ORIGIN, action=ACTION) == 1


def test_localized_date_is_not_invented_and_remains_in_current_snapshot(tmp_path):
    reader, store = service(tmp_path, [ready([{**ENTRY, "day_label":"Hier"}]), ready([{**ENTRY, "day_label":"Hier"}])])
    assert reader.refresh()["status"] == "ready"
    assert reader.refresh()["records"] == 0
    item = reader.history()["items"][0]
    assert item["time_precision"] == "unknown"
    assert item["history_day"] == ""
    assert item["occurred_at"] == ""


def test_invalid_video_links_do_not_report_success(tmp_path):
    reader, _ = service(tmp_path, [ready([{**ENTRY, "url":"https://evil.example/watch?v=abc123XYZ09"}])])
    assert reader.refresh()["status"] == "page_changed"
    assert not reader.status()["last_success_at"]


def test_timezone_and_day_heading_normalization():
    reference = datetime(2026, 10, 4, 20, tzinfo=UTC)
    assert history_day("Today", now=reference, timezone="Asia/Kolkata") == "2026-10-05"
    assert history_day("Yesterday", now=reference, timezone="Asia/Kolkata") == "2026-10-04"
    assert history_day("October 2, 2026", now=NOW, timezone="UTC") == "2026-10-02"
    assert history_day("Friday", now=NOW, timezone="UTC") == ""


@pytest.mark.parametrize("url", ["https://youtube.com.evil/feed/history", "http://youtube.com/feed/history",
    "https://user:pass@youtube.com/feed/history", "https://www.youtube.com/watch?v=abc123XYZ09",
    "https://www.youtube.com/feed/history?redirect=evil", "https://www.youtube.com:8443/feed/history"])
def test_config_rejects_untrusted_urls(url):
    with pytest.raises(ValidationError):
        YouTubeHistoryConfig(url=url)


def test_config_change_preserves_provenance_and_success(tmp_path):
    reader, _ = service(tmp_path, [ready()])
    reader.refresh()
    before = reader.status()
    reader.configure({"url":"https://www.youtube.com/feed/history", "timezone":"Asia/Kolkata"})
    assert reader.status()["last_success_at"] == before["last_success_at"]
    assert reader.status()["account_bound"]


def test_background_refresh_never_navigates_or_reads_user_tab():
    class Page:
        url = "https://www.youtube.com/feed/history"
        async def reload(self, **_kwargs):
            pytest.fail("User-controlled browser was touched")
    browser = type("Browser", (), {"context":object(), "active_page":Page(), "control":"user"})()
    assert asyncio.run(read_history(browser, url=Page.url, automatic=True))["status"] == "browser_busy"
    browser.control = "agent"
    browser.active_page.url = "https://example.com"
    assert asyncio.run(read_history(browser, url=Page.url, automatic=True))["status"] == "history_page_required"


def test_history_status_http_contract(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent.plugins import youtube_browser_history, youtube_api
    reader, _ = service(tmp_path, [])
    monkeypatch.setattr(youtube_browser_history, "YouTubeBrowserHistory", lambda: reader)
    app = FastAPI()
    app.include_router(youtube_api.router, prefix="/api")
    response = TestClient(app).get("/api/plugins/youtube/history/status")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["coverage"] == "recent_loaded_history"
    assert response.json()["local_only"]
    assert "account_fingerprint" not in response.json()


def test_agent_reads_browser_only_history_and_discloses_stale_refresh(monkeypatch, tmp_path):
    from agent.agents.youtube import YoutubeAgent
    from agent.knowledge import runtime
    from agent.plugins import youtube_runtime
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService

    reader, store = service(tmp_path, [ready(), {"status": "page_changed"}])
    reader.refresh()
    reader.refresh()
    monkeypatch.setattr(runtime, "get_knowledge_core", lambda: SimpleNamespace(store=store))
    monkeypatch.setattr(youtube_runtime, "youtube_status", lambda: {})
    capability = YoutubeCapabilityService(vault_root=tmp_path)
    agent = YoutubeAgent(vault_root=tmp_path, youtube_service=capability)

    answer = agent._answer_takeout_history("my watch history")
    assert answer.status == "answered"
    assert "A video" in answer.summary
    assert "2026-10-05" in answer.summary
    assert "Last successful browser refresh" in answer.summary
    assert "layout was not recognized" in answer.summary
    assert "exact time unavailable" in answer.summary

    context = agent._answer_personal_context("my youtube activity")
    assert context.status == "answered"
    assert "A video" in context.summary
    assert "repeat plays" in context.summary
    assert "layout was not recognized" in context.summary
    # Browser presence never becomes a fabricated precise Takeout watch event.
    assert store.count_observations(origin="youtube_takeout", action="youtube.watch") == 0


def test_reload_redirect_never_reads_an_untrusted_page():
    class Page:
        url = "https://www.youtube.com/feed/history"

        async def reload(self, **_kwargs):
            self.url = "https://example.com"

        async def evaluate(self, _script):
            pytest.fail("Reader evaluated an unexpected page")

    browser = SimpleNamespace(context=object(), active_page=Page(), control="agent")
    assert asyncio.run(read_history(browser, url=browser.active_page.url))["status"] == "history_page_required"


def test_history_app_actions_work_without_oauth_and_use_canonical_store(monkeypatch, tmp_path):
    from agent.plugins import youtube_browser_history
    from agent.plugins.youtube_controls import YouTubeControlService
    reader, store = service(tmp_path, [ready(), {"status": "browser_closed"}])

    def create_reader(*, store):
        assert store is reader.store
        return reader

    monkeypatch.setattr(youtube_browser_history, "YouTubeBrowserHistory", create_reader)
    controls = YouTubeControlService(knowledge_core_provider=lambda: SimpleNamespace(store=store))
    configured = controls.execute("youtube.history.configure", {"timezone": "Asia/Kolkata"})
    assert configured["history"]["config"]["timezone"] == "Asia/Kolkata"
    refreshed = controls.execute("youtube.history.refresh", {})
    assert refreshed["history"]["records"] == 1
    assert refreshed["_target_kind"] == "knowledge_projection"
    assert "account_fingerprint" not in refreshed["history"]
    from agent.plugins.contributions import PluginContributionActionError
    with pytest.raises(PluginContributionActionError, match="Open History"):
        controls.execute("youtube.history.refresh", {})


@pytest.mark.skipif(os.environ.get('VELLUM_BROWSER_SMOKE') != '1', reason='Opt-in installed Chromium DOM test')
def test_actual_browser_extracts_history_without_account_cookies(monkeypatch, tmp_path):
    from agent.mcp import dedicated_browser
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path: tmp_path / path.name)
    markup = '''<script>window.ytcfg={get:key=>({LOGGED_IN:true,DATASYNC_ID:'synthetic-account'})[key]};</script>
      <ytd-browse page-subtype="history"><ytd-item-section-renderer>
      <ytd-item-section-header-renderer><span id="title">Today</span></ytd-item-section-header-renderer>
      <ytd-video-renderer><a id="video-title" href="/watch?v=abc123XYZ09">Fixture video</a>
      <ytd-channel-name><a href="/channel/UC-fixture">Fixture creator</a></ytd-channel-name>
      </ytd-video-renderer></ytd-item-section-renderer></ytd-browse>'''

    async def exercise():
        browser = dedicated_browser.DedicatedBrowser()
        try:
            await browser.open()
            await browser.context.route('https://www.youtube.com/**',
                lambda route: route.fulfill(status=200, content_type='text/html', body=markup))
            await browser.active_page.goto('https://www.youtube.com/feed/history')
            result = await read_history(browser, url='https://www.youtube.com/feed/history')
            assert result['status'] == 'ready'
            assert result['entries'][0]['title'] == 'Fixture video'
            assert result['entries'][0]['day_label'] == 'Today'
            assert result['entries'][0]['channel_title'] == 'Fixture creator'
            assert result['account_fingerprint'] != 'synthetic-account'
            assert 'account' not in result
            browser.control = 'user'
            assert (await read_history(browser, url='https://www.youtube.com/feed/history', automatic=True))['status'] == 'browser_busy'
        finally:
            await browser.close()
    asyncio.run(exercise())
