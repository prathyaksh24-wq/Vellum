import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.app_actions import browser as actions
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.contracts.browser import BrowserControl, BrowserSettingsCommand, BrowserPreferences, BrowserDownload
from agent.mcp import dedicated_browser, browser_api
from agent.mcp.dedicated_browser import DedicatedBrowser
from agent.mcp.browser_settings import profile_relative_root, site_origin, download_directory
from agent.mcp.playwright_tools import _PlaywrightMcpClient


@pytest.fixture
def owner(monkeypatch, tmp_path):
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path: tmp_path / path)
    monkeypatch.setattr(dedicated_browser, 'browser_readiness', lambda: (True, ''))
    return DedicatedBrowser()


def manage(owner, **arguments):
    return asyncio.run(owner.manage_settings(BrowserSettingsCommand(**arguments)))


def test_profile_creation_is_durable_and_does_not_open_or_switch(owner):
    view = manage(owner, operation='create_profile', name=' Work ')
    profile = view.preferences.profiles[-1]
    assert profile.name == 'Work' and len(profile.id) == 32
    assert view.preferences.active_profile_id == 'default'
    assert not view.running and owner.context is None
    assert DedicatedBrowser.read_preferences().profiles[-1] == profile
    assert owner._profile_root('default') / 'profile' != owner._profile_root(profile.id) / 'profile'


def test_switch_waits_for_close_and_selects_separate_owned_history(owner, monkeypatch):
    view = manage(owner, operation='create_profile', name='Work')
    profile = view.preferences.profiles[-1]
    owner._record_activity('page_visited', 'https://personal.example/', 'Personal')
    owner.context = object()
    observed = []
    async def close():
        observed.append(owner._browser_preferences().active_profile_id)
        owner.context = None
    monkeypatch.setattr(owner, 'close', close)
    result = manage(owner, operation='select_profile', profile_id=profile.id)
    assert observed == ['default'] and not result.running
    assert result.preferences.active_profile_id == profile.id
    assert not result.activity
    manage(owner, operation='select_profile', profile_id='default')
    assert asyncio.run(owner.settings_view()).activity[0].title == 'Personal'


def test_default_sign_ins_keep_the_existing_profile_path(owner):
    assert profile_relative_root('default').as_posix() == 'data/browser-session'
    with pytest.raises(ValueError): profile_relative_root('../profile')
    with pytest.raises(ValidationError): BrowserSettingsCommand(operation='delete_profile', profile_id='../profile')
    with pytest.raises(ValueError, match='Personal'): manage(owner, operation='delete_profile', profile_id='default')


def test_deleted_profile_does_not_touch_another_profile_or_downloaded_files(owner):
    view = manage(owner, operation='create_profile', name='Delete me')
    identity = view.preferences.profiles[-1].id
    doomed = owner._profile_root(identity) / 'profile/Default/Cookies'
    doomed.parent.mkdir(parents=True); doomed.write_text('test sign-in')
    retained = owner._profile_root('default') / 'profile/Default/Cookies'
    retained.parent.mkdir(parents=True); retained.write_text('keep')
    owner._downloads['pending'] = BrowserDownload(id='pending',name='pending.zip',state='awaiting_approval')
    owner._pending_downloads['pending'] = object()
    owner._persist_downloads()
    result = manage(owner, operation='delete_profile', profile_id=identity)
    assert len(result.preferences.profiles) == 1 and not doomed.exists()
    assert retained.read_text() == 'keep'
    assert result.downloads[0].state == 'awaiting_approval' and 'pending' in owner._pending_downloads


def test_clear_data_is_scoped_and_keeps_files_and_preferences(owner):
    root = owner._profile_root()
    paths = [root/'profile/Default/History',root/'profile/Default/Network/Cookies',root/'profile/Default/Cache/file']
    for path in paths:
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text('test')
    file = root/'saved.txt'; file.write_text('keep')
    owner._downloads['saved'] = BrowserDownload(id='saved',name='saved.txt',state='saved')
    owner._paths['saved'] = file
    owner._persist_downloads(); owner._record_activity('page_visited','https://example.org/')
    manage(owner,operation='clear_data',profile_id='default',data_types=['history','cookies','downloads'])
    assert not paths[0].exists() and not paths[1].exists()
    assert paths[2].exists() and file.exists()
    view = asyncio.run(owner.settings_view())
    assert not view.history and not view.activity and not view.downloads
    assert view.preferences.profiles[0].id == 'default'


def test_content_settings_preserve_brave_preferences_and_use_exact_site_rules(owner):
    path = owner._profile_root()/'profile/Default/Preferences'
    path.parent.mkdir(parents=True); path.write_text(json.dumps({'unrelated':{'keep':True},'profile':{'name':'existing'}}))
    manage(owner,operation='site_rule',rule={'origin':'HTTPS://Example.org:443/','browsing':'block','downloads':'ask',
        'permissions':{'camera':'block','javascript':'block'}})
    owner._write_native_preferences()
    data = json.loads(path.read_text())
    assert data['unrelated'] == {'keep':True} and data['profile']['name'] == 'existing'
    assert data['profile']['content_settings']['exceptions']['javascript'] == {'https://example.org,*':{'setting':2}}
    assert data['profile']['default_content_setting_values']['notifications'] == 2
    assert owner.agent_policy('https://example.org/path') == 'block'
    assert owner.agent_policy('https://other.example/path') == 'allow'


@pytest.mark.parametrize('value',['https://user:secret@example.org','https://example.org/path','https://example.org/?a=b','*.example.org','file:///tmp'])
def test_site_rules_reject_credentials_paths_and_wildcards(value):
    with pytest.raises(ValueError): site_origin(value)


def test_unused_device_grants_expire_without_changing_agent_blocks(owner):
    manage(owner,operation='site_rule',rule={'origin':'https://example.org','browsing':'block','downloads':'block','permissions':{'camera':'allow'}})
    prefs = owner._browser_preferences().model_copy(deep=True)
    prefs.profiles[0].site_rules[0].updated_at = (datetime.now(timezone.utc)-timedelta(days=100)).isoformat()
    owner._store_preferences(prefs)
    owner._expire_site_permissions()
    rule = owner._profile().site_rules[0]
    assert rule.permissions.camera == 'ask' and rule.browsing == 'block'


def test_agent_disable_and_screenshot_policy_are_enforced_at_tool_boundary(owner):
    manage(owner,operation='preferences',patch={'agent_enabled':False})
    owner.control = 'agent'
    with pytest.raises(ValueError,match='disabled'): asyncio.run(owner.tool({'action':'snapshot'}))
    with pytest.raises(ValueError,match='Enable BrowserAgent'): asyncio.run(owner.ui_control(BrowserControl(operation='resume')))
    manage(owner,operation='preferences',patch={'agent_enabled':True,'agent_screenshots':'block'})
    owner.control = 'agent'
    with pytest.raises(ValueError,match='screenshots'): asyncio.run(owner.tool({'action':'vision'}))


def test_pending_download_requires_approval_then_persists_receipt_only(owner, tmp_path):
    class Download:
        suggested_filename = '../archive.zip'
        page = SimpleNamespace(url='https://example.org/')
        async def save_as(self,path): Path(path).write_bytes(b'test download')
        async def cancel(self): pass
    owner.control='agent'
    owner._download(Download())
    item = next(iter(owner._downloads.values()))
    assert item.state == 'awaiting_approval' and not owner._paths
    result = manage(owner,operation='save_download',profile_id='default',download_id=item.id,directory=str(tmp_path/'downloads'))
    assert result.downloads[0].state=='saved'
    restored = DedicatedBrowser()
    assert restored._downloads[item.id].state=='saved', (owner._load_activity(), owner.activity)
    assert restored._paths[item.id].read_bytes()==b'test download'
    manage(owner,operation='remove_download',profile_id='default',download_id=item.id)
    assert restored._paths[item.id].is_file()


def test_network_download_directories_are_rejected(tmp_path):
    for value in ['relative/folder', '//host/share', r'\\host\share', r'\\?\C:\Windows']:
        with pytest.raises(ValueError): download_directory(value,tmp_path)


def test_settings_api_and_worker_do_not_launch_brave(owner, monkeypatch):
    client = _PlaywrightMcpClient()
    async def no_open(): raise AssertionError('Settings launched a browser')
    monkeypatch.setattr(DedicatedBrowser,'open',no_open)
    result = asyncio.run(client.session('settings'))
    assert not result.running and client._dedicated.context is None
    app=FastAPI();app.include_router(browser_api.router,prefix='/api')
    monkeypatch.setattr(browser_api,'browser_session',lambda operation: result)
    with TestClient(app) as http:
        response=http.get('/api/browser/settings')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert response.json()['preferences']['profiles'][0]['id']=='default'


def test_data_action_cannot_skip_confirmation_or_change_profile_binding(owner,monkeypatch):
    calls=[]
    def session(operation, arguments):
        calls.append(arguments)
        return manage(owner,**arguments)
    monkeypatch.setattr(actions,'browser_session',session)
    runtime=AppActionRuntime()
    context=AppActionContext(source='ui')
    request=AppActionRequest(action_id='browser.settings.data',action_version='1',arguments={'operation':'clear_data','profile_id':'default','data_types':['history']})
    receipt=runtime.dispatch(request,context)
    assert receipt.status=='confirmation_required' and not calls
    altered=request.model_copy(update={'arguments':{**request.arguments,'data_types':['cookies']}})
    result=runtime.confirm(receipt.confirmation.token,altered,context)
    assert result.status=='failed' and not calls
    result=runtime.confirm(receipt.confirmation.token,request,context)
    assert result.status=='applied' and len(calls)==1
    assert 'history' not in str(result.result) and 'url' not in str(result.result)
    bad=AppActionRequest(action_id='browser.settings.manage',action_version='1',arguments=request.arguments)
    assert runtime.dispatch(bad,context).status=='failed'
    assert runtime.dispatch(request,AppActionContext(source='nlp')).status=='failed'


def test_browser_profile_policy_allows_permission_reads_but_still_requires_navigation_confirmation(monkeypatch):
    from agent.profiles.models import builtin_profiles
    from agent.profiles import profile_policy
    from agent.tools.capabilities import browser_service
    from agent.tools.registry import ToolPermissionError
    profile = builtin_profiles()['BrowserAgent']
    registry = browser_service.BrowserCapabilityService().build_registry()
    calls = []
    def session(operation, arguments=None):
        calls.append(operation)
        return {'permission':'ask'} if operation=='permission' else 'Observed navigation'
    monkeypatch.setattr(browser_service,'browser_session',session)
    with profile_policy(profile_id='BrowserAgent',allowed_tools=frozenset(profile.tools.allow)):
        assert registry.invoke('browser.session.permission',{'url':'https://example.org'},agent_name='BrowserAgent')=={'permission':'ask'}
        with pytest.raises(ToolPermissionError):
            registry.invoke('browser.confirmed_navigation',{'url':'https://example.org'},agent_name='BrowserAgent')
        assert registry.invoke('browser.confirmed_navigation',{'url':'https://example.org','confirm':True},agent_name='BrowserAgent')=='Observed navigation'
    assert calls==['permission','confirmed_navigation']


def test_navigation_approval_is_bound_to_the_current_session_and_denies_blocked_sites(owner):
    client=_PlaywrightMcpClient();client._dedicated=owner
    owner.control='agent';owner.session_id='current-session';owner.snapshot_id='snapshot'
    payload={'url':'https://example.org','snapshot_id':'snapshot','session_id':'old-session','confirm':True}
    with pytest.raises(ValueError,match='browser changed'):
        asyncio.run(client.session('confirmed_navigation',payload))
    assert not owner._approved_origins
    payload['session_id']='current-session'
    manage(owner,operation='preferences',patch={'agent_browsing':'block'})
    with pytest.raises(ValueError,match='blocked'):
        asyncio.run(client.session('confirmed_navigation',payload))
    assert not owner._approved_origins


def test_history_policy_blocks_the_reader_without_launching_a_profile(owner,monkeypatch):
    from agent.plugins.youtube_browser_history import MESSAGES
    manage(owner,operation='preferences',patch={'agent_history':'block'})
    async def forbidden(**_): raise AssertionError('History reader ran while blocked')
    monkeypatch.setattr(owner,'youtube_history',forbidden)
    client=_PlaywrightMcpClient();client._dedicated=owner
    result=asyncio.run(client.session('youtube_history',{'url':'https://www.youtube.com/feed/history'}))
    assert result=={'status':'history_access_blocked'} and owner.context is None
    assert 'Settings' in MESSAGES['history_access_blocked']
