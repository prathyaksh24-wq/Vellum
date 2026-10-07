from datetime import UTC, datetime
import asyncio
import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.contracts.youtube_history import YouTubeHistoryConfig
from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_browser_history import ACTION, ORIGIN, YouTubeBrowserHistory, history_day
from agent.mcp.youtube_history_page import read_history

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
