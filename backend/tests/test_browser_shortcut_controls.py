"""Shortcut transport checks with fake pages only; no browser or saved data."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agent.contracts.browser import BrowserControl
from agent.mcp.dedicated_browser import DedicatedBrowser, BrowserSessionError
from agent.app_actions.settings_runtime import SettingsRuntimeActionService, SettingsRuntimeActionError


def owner():
    browser = DedicatedBrowser.__new__(DedicatedBrowser)
    browser._profile = lambda: SimpleNamespace(id="profile-a")
    page = SimpleNamespace(url="about:blank")
    browser._pages = {"tab": page}
    browser.active_page = page
    browser.context = SimpleNamespace(new_page=AsyncMock(), target_for_page=lambda value: "owned-target")
    browser._closed_tabs = []
    browser._native = None
    browser.open = AsyncMock()
    browser.status = AsyncMock(return_value="status")
    browser._invalidate = Mock()
    browser._start_tab_load = Mock()
    browser._cancel_tab_load = AsyncMock()
    return browser


def test_reopen_uses_latest_matching_profile_without_an_extra_blank_tab():
    browser = owner()
    browser._closed_tabs = [("profile-a", "https://example.test/a"), ("profile-b", "https://example.test/b")]
    assert asyncio.run(browser.ui_control(BrowserControl(operation="reopen_tab"))) == "status"
    browser.context.new_page.assert_not_called()
    browser._start_tab_load.assert_called_once_with(browser.active_page, "https://example.test/a")
    assert browser._closed_tabs == [("profile-b", "https://example.test/b")]


def test_empty_reopen_does_not_start_a_browser():
    browser = owner()
    with pytest.raises(BrowserSessionError, match="no recently closed"):
        asyncio.run(browser.ui_control(BrowserControl(operation="reopen_tab")))
    browser.open.assert_not_called()


def test_closed_tab_memory_is_bounded_and_excludes_embedded_credentials():
    browser = owner()
    for index in range(25):
        browser._remember_closed_tab(SimpleNamespace(url=f"https://example.test/{index}"))
    browser._remember_closed_tab(SimpleNamespace(url="https://user:password@example.test/"))
    browser._remember_closed_tab(SimpleNamespace(url="about:blank"))
    assert len(browser._closed_tabs) == 20
    assert browser._closed_tabs[0][1] == "https://example.test/5"


def test_find_uses_only_the_owned_native_target_and_keeps_tab_identity():
    browser = owner()
    browser._native = SimpleNamespace(call=AsyncMock())
    asyncio.run(browser.ui_control(BrowserControl(operation="find", text="Saturn", find_next=True, forward=False)))
    browser._native.call.assert_awaited_once_with("find", target_id="owned-target", text="Saturn", find_next=True, forward=False)
    assert list(browser._pages) == ["tab"]


def test_force_reload_uses_cdp_and_releases_its_session():
    browser = owner()
    session = SimpleNamespace(send=AsyncMock(), detach=AsyncMock())
    browser.active_page.context = SimpleNamespace(new_cdp_session=AsyncMock(return_value=session))
    asyncio.run(browser.ui_control(BrowserControl(operation="reload", ignore_cache=True)))
    session.send.assert_awaited_once_with("Page.reload", {"ignoreCache": True})
    session.detach.assert_awaited_once()


def test_number_shortcut_preference_uses_existing_device_setting_validation():
    assert SettingsRuntimeActionService._validate_device_patch({"number_shortcuts": "chats"}) == {"number_shortcuts": "chats"}
    for value in ("other", [], 1):
        with pytest.raises(SettingsRuntimeActionError):
            SettingsRuntimeActionService._validate_device_patch({"number_shortcuts": value})
