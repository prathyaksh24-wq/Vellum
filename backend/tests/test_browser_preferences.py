import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent.contracts.browser import BrowserControl, BrowserPreferences
from agent.mcp import dedicated_browser
from agent.mcp.dedicated_browser import BrowserSessionError, DedicatedBrowser


@pytest.fixture
def preferences_path(monkeypatch, tmp_path):
    path = tmp_path / 'browser-session' / 'preferences.json'
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda _: path)
    return path


def test_preferences_persist_without_changing_browser_ownership(preferences_path, monkeypatch):
    browser = DedicatedBrowser()
    page = SimpleNamespace(url='https://example.org/')
    browser.active_page, browser.control = page, 'agent'
    async def status(): return browser._browser_preferences()
    monkeypatch.setattr(browser, 'status', status)
    result = asyncio.run(browser.ui_control(BrowserControl(operation='preferences', search_engine='searxng',
        searxng_url='https://search.example.org/searx/', shortcuts=[{'id':'docs','name':' Docs ', 'url':'https://example.org/docs'}])))
    assert result.search_engine == 'searxng'
    assert result.searxng_url == 'https://search.example.org/searx'
    assert result.shortcuts[0].name == 'Docs'
    assert browser.active_page is page and browser.control == 'agent'
    assert DedicatedBrowser()._browser_preferences() == result
    browser._update_preferences(BrowserControl(operation='preferences',search_engine='brave'))
    assert DedicatedBrowser()._browser_preferences().shortcuts == result.shortcuts


@pytest.mark.parametrize('value', ['file:///tmp', 'https://user:password@example.org', 'https://example.org/?q=test',
    'https://example.org/#fragment', 'about:blank'])
def test_invalid_instance_never_changes_saved_preferences(preferences_path, value):
    browser = DedicatedBrowser()
    with pytest.raises(BrowserSessionError):
        browser._update_preferences(BrowserControl(operation='preferences',search_engine='searxng',searxng_url=value))
    assert browser._browser_preferences().search_engine == 'google'
    assert not preferences_path.exists()


@pytest.mark.parametrize('shortcuts', [
    [{'id':'a','name':'A','url':'about:blank'}],
    [{'id':'a','name':'A','url':'https://user:password@example.org'}],
    [{'id':'a','name':' ','url':'https://example.org'}],
    [{'id':'a','name':'A','url':'https://example.org'}, {'id':'a','name':'B','url':'https://example.net'}],
])
def test_shortcut_contract_rejects_unsafe_or_ambiguous_entries(preferences_path, shortcuts):
    with pytest.raises(BrowserSessionError):
        DedicatedBrowser()._update_preferences(BrowserControl(operation='preferences',shortcuts=shortcuts))
    assert not preferences_path.exists()


def test_corrupt_preferences_fall_back_to_default(preferences_path):
    preferences_path.parent.mkdir()
    preferences_path.write_text('{broken',encoding='utf-8')
    assert DedicatedBrowser()._browser_preferences() == BrowserPreferences()


def test_failed_save_retains_last_applied_preferences(preferences_path, monkeypatch):
    browser = DedicatedBrowser()
    browser._update_preferences(BrowserControl(operation='preferences',search_engine='brave'))
    def denied(*_args, **_kwargs): raise OSError('private filesystem details')
    monkeypatch.setattr(type(preferences_path),'replace',denied)
    with pytest.raises(BrowserSessionError, match='could not be saved'):
        browser._update_preferences(BrowserControl(operation='preferences',search_engine='startpage'))
    assert browser._browser_preferences().search_engine == 'brave'
    assert DedicatedBrowser()._browser_preferences().search_engine == 'brave'


def test_search_preferences_are_typed_and_bounded():
    for data in [{'search_engine':'bing'}, {'unknown':True}, {'shortcuts':[{'id':str(i),'name':'A','url':'https://example.org'} for i in range(13)]}]:
        with pytest.raises(ValidationError): BrowserPreferences.model_validate(data)
