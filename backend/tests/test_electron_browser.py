import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.mcp.electron_browser import ElectronBridge, ElectronContext


@pytest.mark.parametrize('endpoint', ['https://127.0.0.1:1234','http://example.org:1234',
    'http://127.0.0.1:1234/private','http://user:password@127.0.0.1:1234','http://127.0.0.1:1234?token=secret'])
def test_bridge_rejects_non_owned_endpoint_shapes(tmp_path, endpoint):
    descriptor=tmp_path/'bridge.json'
    descriptor.write_text(json.dumps({'version':1,'endpoint':endpoint,'token':'a'*64}))
    assert ElectronBridge.discover(descriptor) is None


def test_bridge_requires_valid_private_descriptor_without_discovering_other_browsers(tmp_path):
    descriptor=tmp_path/'bridge.json'
    assert ElectronBridge.discover(descriptor) is None
    descriptor.write_text(json.dumps({'version':1,'endpoint':'http://127.0.0.1:1234','token':'a'*64}))
    bridge=ElectronBridge.discover(descriptor)
    assert bridge.endpoint=='http://127.0.0.1:1234'
    descriptor.write_text(json.dumps({'version':1,'endpoint':'http://127.0.0.1:1234','token':'invalid'}))
    assert ElectronBridge.discover(descriptor) is None


def test_context_cannot_create_cdp_sessions_for_chat_or_unregistered_pages():
    owner=SimpleNamespace(_browser_preferences=lambda:SimpleNamespace(active_profile_id='default'))
    context=ElectronContext(owner,None,None)
    app_page=SimpleNamespace(is_closed=lambda:False)
    with pytest.raises(ValueError,match='does not belong'):
        asyncio.run(context.new_cdp_session(app_page))


def test_native_cookie_clear_does_not_remove_the_existing_brave_profile(monkeypatch,tmp_path):
    from agent.mcp import dedicated_browser
    from agent.contracts.browser import BrowserSettingsCommand
    monkeypatch.setattr(dedicated_browser,'_resolve_against_repo',lambda value:tmp_path/Path(value))
    owner=dedicated_browser.DedicatedBrowser()
    old_cookie=tmp_path/'data/browser-session/profile/Default/Network/Cookies'
    old_cookie.parent.mkdir(parents=True);old_cookie.write_text('retained Brave fixture')
    calls=[]
    async def call(operation,**kwargs):calls.append((operation,kwargs));return {}
    owner._native=SimpleNamespace(call=call)
    asyncio.run(owner.manage_settings(BrowserSettingsCommand(operation='clear_data',data_types=['cookies'])))
    assert old_cookie.read_text()=='retained Brave fixture'
    assert calls==[('clear',{'profile_id':'default','data_types':['cookies']})]
