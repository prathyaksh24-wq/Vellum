import sqlite3
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.contracts.browser import BrowserAddressSuggestions, BrowserPreferences
from agent.mcp import browser_api, dedicated_browser
from agent.mcp.dedicated_browser import DedicatedBrowser


def test_close_before_start_acknowledges_closed_without_opening_a_session(monkeypatch):
    from agent.mcp.playwright_tools import _PlaywrightMcpClient
    monkeypatch.setattr(dedicated_browser,'browser_readiness',lambda:(True,''))
    monkeypatch.setattr(DedicatedBrowser,'read_preferences',staticmethod(lambda:BrowserPreferences()))
    client = _PlaywrightMcpClient()
    result = asyncio.run(client.session('control',{'operation':'close'}))
    assert result.control == 'closed' and not result.running
    assert client._dedicated is None


def test_owned_chromium_history_is_read_only_filtered_and_bounded(tmp_path, monkeypatch):
    history = tmp_path / 'History'
    connection = sqlite3.connect(history)
    connection.execute('CREATE TABLE urls (url TEXT, title TEXT, last_visit_time INTEGER)')
    rows = [('https://www.youtube.com/feed/history', 'Watch history - YouTube', 100),
            ('https://www.youtube.com/feed/history', 'Duplicate', 99),
            ('https://user:secret@example.com/', 'Unsafe', 98),
            ('javascript:alert(1)', 'Unsafe', 97), ('https://[', 'Malformed', 96)]
    rows += [(f'https://example.com/{n}', 'Example', n) for n in range(12)]
    connection.executemany('INSERT INTO urls VALUES (?, ?, ?)', rows)
    connection.commit(); connection.close()
    before = history.read_bytes()
    def owned_path(path):
        assert str(path).replace('\\', '/') == 'data/browser-session/profile/Default/History'
        return history
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', owned_path)
    result = DedicatedBrowser.address_suggestions('yo')
    assert [item.url for item in result.items] == ['https://www.youtube.com/feed/history']
    assert len(DedicatedBrowser.address_suggestions().items) == 8
    assert DedicatedBrowser.address_suggestions("' OR 1=1 --").items == []
    assert history.read_bytes() == before


def test_missing_or_locked_history_does_not_create_or_copy_a_profile(tmp_path, monkeypatch):
    history = tmp_path / 'History'
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda _: history)
    assert DedicatedBrowser.address_suggestions('youtube').items == []
    assert not history.exists()
    history.write_bytes(b'not sqlite')
    assert DedicatedBrowser.address_suggestions().items == []
    assert list(tmp_path.iterdir()) == [history]


def test_suggestions_route_is_typed_non_cached_and_bounds_query(monkeypatch):
    calls = []
    monkeypatch.setattr(browser_api, 'browser_session', lambda operation, args: calls.append((operation,args)) or (BrowserAddressSuggestions(),BrowserPreferences(search_engine='duckduckgo')))
    monkeypatch.setattr(browser_api, 'search_completions', lambda query,prefs: (['yoga'], 'ready'))
    app = FastAPI(); app.include_router(browser_api.router, prefix='/api')
    with TestClient(app) as client:
        response = client.get('/api/browser/suggestions?q=yo')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {'contract_version':1, 'items':[], 'queries':['yoga'], 'search_engine':'duckduckgo', 'suggestion_status':'ready'}
        assert calls == [('suggestions', {'query':'yo','with_preferences':True})]
        assert client.get('/api/browser/suggestions', params={'q':'x' * 257}).status_code == 422


def test_running_session_retains_history_and_closed_tab_navigation_when_chromium_locks_sqlite(monkeypatch):
    from agent.contracts.browser import BrowserAddressSuggestion
    cached = [BrowserAddressSuggestion(url='https://example.org/old',title='Old document')]
    monkeypatch.setattr(DedicatedBrowser, '_read_address_history', staticmethod(lambda: cached))
    browser = DedicatedBrowser()
    browser.context = object()
    monkeypatch.setattr(DedicatedBrowser, '_read_address_history', staticmethod(lambda: None))
    assert browser.session_address_suggestions('document').items == cached
    page = SimpleNamespace(url='https://example.org/new',main_frame=object())
    browser._pages = {'owned':page}; browser.active_page = page
    browser._frame_navigated(page,page.main_frame)
    browser._remember_address(page.url,'New document')
    browser._pages.clear()
    assert browser.session_address_suggestions('new').items[0].title == 'New document'
    for n in range(510): browser._remember_address(f'https://example.org/{n}',visited=True)
    assert len(browser._address_history) == 500
    browser.context = None
    monkeypatch.setattr(DedicatedBrowser, '_read_address_history', staticmethod(lambda: []))
    assert browser.session_address_suggestions().items == []
