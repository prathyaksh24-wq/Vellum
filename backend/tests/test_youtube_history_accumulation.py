from datetime import UTC, datetime, timedelta
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event

import pytest

from agent.knowledge.store import KnowledgeStore
from agent.plugins.youtube_browser_history import ACTION, ORIGIN, HistoryReadError, YouTubeBrowserHistory, YouTubeBrowserHistoryService

NOW = datetime(2026, 10, 8, 20, tzinfo=UTC)


def item(number=0, *, day="Today", channel="Creator"):
    return {"video_id": f"{number:011d}", "title": f"Video {number}", "channel_title": channel, "day_label": day}


def packet(items=None, account="a", **extra):
    return {"status": "ready", "account_id": account * 64,
        "items": [item()] if items is None else items, **extra}


def reader(tmp_path, packets, *, clock=lambda: NOW):
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    reads = iter(packets)
    return YouTubeBrowserHistoryService(store=store, browser_reader=lambda: next(reads), clock=clock), store


def test_refreshes_accumulate_surviving_records_without_duplicate_counts(tmp_path):
    service, store = reader(tmp_path, [packet([item(0), item(1)]), packet([item(1), item(2)]), packet([item(1), item(2)])])
    first = service.refresh()
    second = service.refresh(automatic=True)
    service.refresh()
    assert first["source_id"] == second["source_id"]
    assert second["total"] == 2  # Fresh page count stays distinct from saved coverage.
    saved = YouTubeBrowserHistory(store=store).history(limit=10)
    assert saved["total"] == 3
    assert {video["video_id"] for video in saved["items"]} == {f"{i:011d}" for i in range(3)}
    assert saved["coverage"] == "accumulated_recent_pages"
    assert all(video["occurred_at"] == "" for video in saved["items"])
    source = store.get_source(first["source_id"])
    assert len(source["metadata"]["items"]) == 2
    assert source["sensitivity"] == "private_local_only" and source["external_policy"] == "deny_raw"
    assert store.count_observations(origin=ORIGIN, action=ACTION) == 3
    assert store.count_observations(origin="youtube_takeout", action="youtube.watch") == 0


def test_day_rollover_and_timezone_do_not_inflate_yesterday_entries(tmp_path):
    moment = [NOW]
    service, store = reader(tmp_path, [packet(timezone="Asia/Kolkata"), packet([item(day="Yesterday")], timezone="Asia/Kolkata"),
        packet(timezone="Asia/Kolkata")], clock=lambda: moment[0])
    service.refresh()
    # October 9 in the browser's zone, then October 10 after rollover.
    moment[0] += timedelta(days=1)
    service.refresh()
    assert store.count_observations(origin=ORIGIN, action=ACTION) == 1
    service.refresh()
    rows = store.list_observation_details(origin=ORIGIN, action=ACTION)
    assert {row["payload"]["history_day"] for row in rows} == {"2026-10-09", "2026-10-10"}
    assert YouTubeBrowserHistory(store=store).status()["config"]["timezone"] == "Asia/Kolkata"


def test_account_switch_isolated_and_return_to_account_recovers_its_history(tmp_path):
    service, store = reader(tmp_path, [packet([item(1)]), packet([item(2)], account="b"), packet([item(3)])])
    first = service.refresh()
    service.refresh()
    owner = YouTubeBrowserHistory(store=store)
    assert owner.status()["records"] == 1
    assert [video["video_id"] for video in owner.history()["items"]] == [item(2)["video_id"]]
    service.refresh()
    assert owner.status()["records"] == 2
    assert {video["video_id"] for video in owner.history()["items"]} == {item(1)["video_id"], item(3)["video_id"]}
    assert store.get_source(first["source_id"])["account_id"] == "a" * 64


@pytest.mark.parametrize("failure", ["signed_out", "account_changed", "account_unknown", "page_unreadable"])
def test_failed_auto_read_keeps_records_cursor_and_last_success(tmp_path, failure):
    service, store = reader(tmp_path, [packet(), {"status": failure}])
    service.refresh()
    before = store.get_sync_cursor(ORIGIN, "a" * 64)
    owner = YouTubeBrowserHistory(store=store)
    last_success = owner.status()["last_success_at"]
    with pytest.raises(HistoryReadError):
        service.refresh(automatic=True)
    assert store.get_sync_cursor(ORIGIN, "a" * 64) == before
    assert owner.status()["last_success_at"] == last_success
    assert owner.history()["total"] == 1
    assert owner.status()["status"] != "ready"


def test_empty_latest_page_retains_accumulated_day_evidence(tmp_path):
    service, store = reader(tmp_path, [packet(), packet([], status="empty")])
    service.refresh()
    empty = service.refresh(automatic=True)
    assert empty["total"] == 0
    assert YouTubeBrowserHistory(store=store).status()["status"] == "empty"
    assert YouTubeBrowserHistory(store=store).history()["total"] == 1


def test_unknown_dates_stay_snapshot_only(tmp_path):
    service, store = reader(tmp_path, [packet([item(day="Hier")]), packet([item(day="Hier")]), packet([item(2)])])
    service.refresh()
    service.refresh()
    owner = YouTubeBrowserHistory(store=store)
    assert owner.status()["records"] == 0 and owner.history()["total"] == 1
    service.refresh()
    assert owner.history()["total"] == 1 and owner.history()["items"][0]["video_id"] == item(2)["video_id"]


def test_saved_creator_filter_reads_beyond_500_observations(tmp_path):
    packets = [packet([item(i, channel="Other") for i in range(start, start + 100)]) for start in range(0, 600, 100)]
    packets.append(packet([item(601, channel="Wanted Creator")]))
    service, store = reader(tmp_path, packets)
    for _ in packets:
        service.refresh(automatic=True)
    result = YouTubeBrowserHistory(store=store).history(limit=1, channel="Wanted Creator")
    assert result["total"] == 1 and result["items"][0]["video_id"] == item(601)["video_id"]
    assert YouTubeBrowserHistory(store=store).status()["records"] == 601


def test_manual_and_automatic_refresh_cannot_overlap(tmp_path):
    entered, release = Event(), Event()
    calls = []
    def read():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return packet()
    store = KnowledgeStore(tmp_path / "core.db", tmp_path / "blobs")
    service = YouTubeBrowserHistoryService(store=store, browser_reader=read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.refresh, automatic=True)
        assert entered.wait(5)
        try:
            with pytest.raises(HistoryReadError, match="another refresh"):
                service.refresh()
        finally:
            release.set()
        assert future.result()["total"] == 1
    assert len(calls) == 1


def test_failed_ingestion_does_not_advance_success_or_account_cursor(tmp_path, monkeypatch):
    service, store = reader(tmp_path, [packet(), packet([item(1)])])
    service.refresh()
    before = store.get_sync_cursor(ORIGIN, "a" * 64)
    success = YouTubeBrowserHistory(store=store).status()["last_success_at"]
    def fail(_items):
        raise OSError("private filesystem details")
    monkeypatch.setattr(store, "record_observations", fail)
    with pytest.raises(HistoryReadError, match="History refresh failed"):
        service.refresh(automatic=True)
    after = store.get_sync_cursor(ORIGIN, "a" * 64)
    assert after["cursor"] == before["cursor"] and after["state"] == before["state"]
    assert after["last_success_at"] == before["last_success_at"]
    assert after["last_error_code"] == "OSERROR"
    assert YouTubeBrowserHistory(store=store).status()["last_success_at"] == success
    assert "filesystem" not in YouTubeBrowserHistory(store=store).status()["message"]


def test_scheduled_handler_reports_failure_and_treats_pause_as_skip(monkeypatch):
    from agent.automations import builtins
    from agent.plugins import youtube_browser_history
    calls = []
    result = {"status": "browser_busy"}
    class Owner:
        def refresh(self, *, automatic):
            calls.append(automatic)
            return result
    monkeypatch.setattr(youtube_browser_history, "YouTubeBrowserHistory", Owner)
    asyncio.run(builtins._youtube_history_handler())
    result.update(status="sign_in_required", message="Sign into YouTube manually.")
    with pytest.raises(RuntimeError, match="Sign into YouTube"):
        asyncio.run(builtins._youtube_history_handler())
    assert calls == [True, True]


def test_browser_identity_matches_legacy_account_hash():
    from agent.mcp.youtube_history import read_history_page
    class Page:
        url = "https://www.youtube.com/feed/history"
        async def evaluate(self, _script):
            return {"signed_in": True, "identity": "fixture-account", "items": [item()], "empty": False}
        async def wait_for_timeout(self, _time):
            pass
    result = asyncio.run(read_history_page(Page(), scroll_limit=0))
    assert result["account_id"] == sha256(b"fixture-account").hexdigest()


def test_cloud_profile_cannot_read_private_history(tmp_path):
    from agent.profiles.execution import ProfileExecution, profile_execution
    from agent.tools.capabilities.youtube_service import YoutubeCapabilityService
    service = YoutubeCapabilityService(vault_root=tmp_path,
        browser_history_backend=lambda: pytest.fail("Private history must not reach an external profile model"))
    execution = ProfileExecution("YoutubeAgent", "openai/gpt-4o", "light", "", "", {}, "", "test")
    with profile_execution(execution), pytest.raises(ValueError, match="local only"):
        service.watch_history({})


def test_browser_worker_uses_quiet_reader_for_automatic_and_manual_calls(monkeypatch):
    from agent.mcp import dedicated_browser, playwright_tools
    calls = []
    class Browser:
        async def youtube_history(self, *, url):
            calls.append(url)
            return packet()
    monkeypatch.setattr(dedicated_browser, "DedicatedBrowser", Browser)
    async def check():
        client = playwright_tools._PlaywrightMcpClient()
        result = await client.session("youtube_history", {"url": "https://www.youtube.com/feed/history", "automatic": True})
        assert result["account_id"] == "a" * 64
        result = await client.session("youtube_history")
        assert result["status"] == "ready"
        client._busy = True
        assert (await client.session("youtube_history", {"automatic": True}))["status"] == "browser_busy"
    asyncio.run(check())
    assert calls == ["https://www.youtube.com/feed/history", None]


@pytest.mark.skipif(os.environ.get("VELLUM_BROWSER_SMOKE") != "1", reason="Opt-in installed browser fixture")
def test_real_quiet_history_tab(monkeypatch, tmp_path):
    from agent.mcp import dedicated_browser
    monkeypatch.setattr(dedicated_browser, "_resolve_against_repo", lambda path: tmp_path / path.name)
    markup = """<script>window.ytcfg={get:key=>({LOGGED_IN:true,DATASYNC_ID:'fixture-account'})[key]};</script>
      <ytd-browse page-subtype="history"><ytd-item-section-renderer><div id="header">Today</div>
      <yt-lockup-view-model><h3><a href="/watch?v=abcdefghijk">Fixture watched video</a></h3>
      <div class="ytContentMetadataViewModelMetadataRow"><span class="ytContentMetadataViewModelMetadataText">Fixture Creator</span></div>
      </yt-lockup-view-model></ytd-item-section-renderer></ytd-browse>"""
    async def check():
        browser = dedicated_browser.DedicatedBrowser()
        original_open = browser.open
        state = {}
        async def open_fixture():
            await original_open()
            await browser.context.route("https://www.youtube.com/**",
                lambda route: route.fulfill(status=200, content_type="text/html", body=markup))
            state["visible"] = browser.active_page
            state["pages"] = len(browser.context.pages)
        monkeypatch.setattr(browser, "open", open_fixture)
        try:
            result = await browser.youtube_history()
            assert result["status"] == "ready"
            assert result["items"][0]["channel_title"] == "Fixture Creator"
            assert browser.active_page is state["visible"]
            assert browser.active_page.url == "about:blank"
            assert len(browser.context.pages) == state["pages"]
            assert browser.presentation_requested is False
            browser.control = "paused"
            with pytest.raises(dedicated_browser.BrowserSessionError, match="paused"):
                await browser.youtube_history()
            assert len(browser.context.pages) == state["pages"]
        finally:
            await browser.close()
            assert browser.context is None
            assert browser._process is None
    asyncio.run(check())


def test_redirected_history_page_is_not_evaluated():
    from agent.mcp.youtube_history import read_history_page
    class Page:
        url = "https://www.youtube.com/feed/history"
        calls = 0
        async def evaluate(self, _script):
            self.calls += 1
            assert self.url.startswith("https://www.youtube.com/")
            self.url = "https://example.com"
            return {"signed_in": True, "identity": "account", "items": [item()], "empty": False}
    page = Page()
    result = asyncio.run(read_history_page(page, scroll_limit=0))
    assert result["status"] == "page_unreadable" and page.calls == 1
