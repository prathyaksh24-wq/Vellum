"""Run only by the disposable Electron integration smoke, never against a user's profile."""
import asyncio
import os
from pathlib import Path
import re
from agent.contracts.browser import BrowserControl,BrowserSettingsCommand

from agent.mcp import dedicated_browser, electron_browser, playwright_tools
from agent.agents.browser import BrowserAgent
from agent.tools.capabilities.browser_service import BrowserCapabilityService

root=Path(os.environ['VELLUM_NATIVE_TEST_ROOT'])
dedicated_browser._resolve_against_repo=lambda value:root/Path(value)
electron_browser._resolve_against_repo=lambda value:root/Path(value)
fixture=os.environ['VELLUM_NATIVE_FIXTURE_URL']
state=playwright_tools.browser_session('agent_open')
assert state.render_transport=='native' and state.running and len(state.tabs)==1
assert state.browser_name=='Chromium' and state.native_target_id

step=0
def plan(goal,snapshot,history):
    global step
    step+=1
    if step==1:return {'action':'navigate','url':fixture}
    if step==2:
        line=next(row for row in snapshot.splitlines() if 'Search fixture' in row)
        return {'action':'type','ref':re.search(r'@e\d+',line)[0],'text':'black holes'}
    if step==3:
        line=next(row for row in snapshot.splitlines() if 'Apply fixture' in row and '@e' in row)
        return {'action':'click','ref':re.search(r'@e\d+',line)[0]}
    return {'action':'done','summary':'Typed the search and applied it in the embedded page.'}

agent=BrowserAgent(tool_registry=BrowserCapabilityService().build_registry(),planner=plan)
result=agent.answer('Use the browser to type black holes in the fixture search and click Apply fixture')
assert result.status=='answered',(result.summary,result.analysis)

async def inspect():
    owner=playwright_tools._client._dedicated
    assert await owner.active_page.locator('#result').inner_text()=='Applied: black holes'
    assert await owner.active_page.locator('[data-vellum-agent-cursor]').count()==1
    assert await owner.active_page.evaluate('typeof window.VellumDesktop')=='undefined'
    assert len(owner._pages)==1 and len(owner.context.pages)==1
    snapshot=await owner.snapshot(full=True)
    row=next(row for row in snapshot.splitlines() if 'Google Search' in row and '@e' in row)
    assert not await owner.sensitive_interaction({'action':'click','ref':re.search(r'@e\d+',row)[0]})
    file_handle=await owner.active_page.locator('input[type=file]').element_handle()
    owner._refs['fixture-file']=file_handle
    assert await owner.sensitive_interaction({'action':'click','ref':'fixture-file'})
    del owner._refs['fixture-file'];await file_handle.dispose()
    try:await owner.frame()
    except ValueError:pass
    else:raise AssertionError('A native tab must never start a frame stream')
    original=owner.active_page
    await owner.tool({'action':'scroll','direction':'bottom'})
    assert await original.evaluate('window.scrollY')>1000
    await owner.tool({'action':'tabs','tab_action':'new'})
    assert len((await owner.status()).tabs)==2
    await owner.tool({'action':'tabs','tab_action':'close','index':'1'})
    assert len((await owner.status()).tabs)==1
    await original.locator('button',has_text='Fullscreen fixture').click()
    for _ in range(40):
        if await original.evaluate('Boolean(document.fullscreenElement)'):break
        await asyncio.sleep(.05)
    assert await original.evaluate('Boolean(document.fullscreenElement)')
    await original.keyboard.press('Escape')
    for _ in range(40):
        if not await original.evaluate('Boolean(document.fullscreenElement)'):break
        await asyncio.sleep(.05)
    assert not await original.evaluate('Boolean(document.fullscreenElement)')
    assert len((await owner.status()).tabs)==1
    print('Native actions and tabs passed; checking profile isolation.',flush=True)
    # Named profiles have independent cookie jars, while reopening retains sign-ins.
    await original.evaluate("document.cookie='fixture_session=personal; path=/'")
    view=await owner.manage_settings(BrowserSettingsCommand(operation='create_profile',name='Second fixture'))
    second=next(profile.id for profile in view.preferences.profiles if profile.name=='Second fixture')
    await owner.manage_settings(BrowserSettingsCommand(operation='open_profile',profile_id=second))
    await owner.ui_control(BrowserControl(operation='navigate',url=fixture))
    while owner._tab_loads:await asyncio.sleep(.03)
    assert await owner.active_page.evaluate('document.cookie')==''
    print('Second profile is isolated; checking reopen.',flush=True)
    await owner.manage_settings(BrowserSettingsCommand(operation='open_profile',profile_id='default'))
    await owner.ui_control(BrowserControl(operation='navigate',url=fixture))
    while owner._tab_loads:await asyncio.sleep(.03)
    assert 'fixture_session=personal' in await owner.active_page.evaluate('document.cookie')
    print('Profile sign-in data persisted; checking clear.',flush=True)
    legacy=root/'data/browser-session/profile/Default/Network/Cookies'
    legacy.parent.mkdir(parents=True,exist_ok=True);legacy.write_text('retained Brave cookie fixture')
    await owner.manage_settings(BrowserSettingsCommand(operation='clear_data',profile_id='default',data_types=['cookies']))
    assert legacy.read_text()=='retained Brave cookie fixture'
    await owner.ui_control(BrowserControl(operation='open'))
    await owner.ui_control(BrowserControl(operation='navigate',url=fixture))
    while owner._tab_loads:await asyncio.sleep(.03)
    assert await owner.active_page.evaluate('document.cookie')==''
    print('Cookie clearing retained the old Brave data; checking downloads.',flush=True)
    # A native download still enters the canonical owner and saved-file receipt.
    download=fixture.rsplit('/',1)[0]+'/download'
    await owner.ui_control(BrowserControl(operation='navigate',url=download))
    for _ in range(80):
        state=await owner.status()
        if state.downloads and state.downloads[-1].state=='saved':break
        await asyncio.sleep(.1)
    assert any(item.state=='saved' for item in state.downloads),state.downloads
    await owner.close()
    assert not (await owner.status()).running

try:
    playwright_tools._worker.submit(inspect()).result(timeout=30)
    search_step=0
    def search_plan(goal,snapshot,history):
        global search_step
        search_step+=1
        if search_step==1:return {'action':'navigate','url':fixture.rsplit('/',1)[0]+'/wiki/Jailer_2'}
        if search_step==2:return {'action':'navigate','url':fixture.rsplit('/',1)[0]+'/'}
        if search_step==3:
            row=next(row for row in snapshot.splitlines() if 'Search fixture' in row)
            return {'action':'type','ref':re.search(r'@e\d+',row)[0],'text':'jailer'}
        if search_step==4:
            row=next(row for row in snapshot.splitlines() if 'Jailer 2 - Wikipedia' in row and '@e' in row)
            return {'action':'click','ref':re.search(r'@e\d+',row)[0]}
        return {'action':'done','summary':'Typed jailer and clicked the visible Wikipedia suggestion.'}
    search_result=BrowserAgent(tool_registry=BrowserCapabilityService().build_registry(),planner=search_plan).answer('Use the browser to search for Jailer 2 on Wikipedia')
    assert search_result.status=='answered',(search_result.summary,search_result.analysis)
    assert search_step==5
    async def check_search():
        owner=playwright_tools._client._dedicated
        assert owner.active_page.url.endswith('/article')
        await owner.close()
    playwright_tools._worker.submit(check_search()).result(timeout=10)
    print('Visible native search passed: rejected guessed URL, typed query, observed delayed suggestion, clicked its real link.')
    print('Verified BrowserAgent actions, cursor, tabs, fullscreen exit, separate profiles, cookie clearing, downloads, and no streaming.')
finally:
    playwright_tools.shutdown()
