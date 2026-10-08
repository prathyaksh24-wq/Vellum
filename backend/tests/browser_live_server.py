"""Disposable UI/Brave fixture. Never load the user's API, profile or conversations."""
from contextlib import asynccontextmanager
from collections import deque
import asyncio
from pathlib import Path
import os

ROOT = Path(os.environ['BROWSER_QA_ROOT']).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
os.environ['OBSIDIAN_VAULT_PATH'] = str(ROOT)
os.environ['PLAYWRIGHT_MCP_ALLOW_MUTATIONS'] = 'true'

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from agent.app_actions import api as action_api
from agent.app_actions.runtime import AppActionRuntime
from agent.contracts.capabilities import public_capability_contract
from agent.mcp import browser_api, dedicated_browser, playwright_tools


def create_app():
    dedicated_browser._resolve_against_repo = lambda path: ROOT / path.name
    # Every native browser in this explicitly disposable fixture is silent.
    # This prevents public-media QA from playing audio beside the user's work.
    from types import SimpleNamespace
    original_asyncio = dedicated_browser.asyncio
    original_spawn = original_asyncio.create_subprocess_exec
    async def silent_spawn(*args, **kwargs):
        return await original_spawn(*args, '--mute-audio', **kwargs)
    dedicated_browser.asyncio = SimpleNamespace(**vars(original_asyncio))
    dedicated_browser.asyncio.create_subprocess_exec = silent_spawn
    # Public media QA only; retain categories/statuses, never URLs or headers.
    media_requests = deque(maxlen=80)
    original_add_page = dedicated_browser.DedicatedBrowser._add_page
    def add_page(browser, page):
        original_add_page(browser, page)
        def category(url):
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            if parsed.path.endswith('/timedtext'): return 'captions'
            if parsed.hostname and parsed.hostname.endswith('.googlevideo.com'): return 'video'
            if parsed.path.endswith('/youtubei/v1/player'): return 'player'
            return ''
        def response(item):
            kind = category(item.url)
            if kind: media_requests.append({'kind':kind,'status':item.status})
        async def finished(item):
            if category(item.url) == 'captions':
                try:
                    response = await item.response()
                    media_requests.append({'kind':'caption_body','bytes':len(await response.body())})
                except Exception: pass
        def failed(item):
            kind = category(item.url)
            if kind: media_requests.append({'kind':kind,'failure':item.failure})
        page.on('response', response)
        page.on('requestfailed', failed)
        page.on('requestfinished', finished)
    dedicated_browser.DedicatedBrowser._add_page = add_page
    action_api.get_app_action_runtime = lambda: runtime
    runtime = AppActionRuntime()
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await playwright_tools.shutdown_async()
            dedicated_browser.DedicatedBrowser._add_page = original_add_page
            dedicated_browser.asyncio = original_asyncio
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5180'], allow_methods=['*'], allow_headers=['Content-Type'])
    app.include_router(browser_api.router, prefix='/api')
    app.include_router(action_api.router, prefix='/api')
    @app.get('/api/capabilities')
    def capabilities(): return public_capability_contract()
    @app.get('/api/conversations')
    @app.get('/api/conversations/library')
    def conversations():
        return {'conversations':[{'id':'browser-fixture','thread_id':'browser-fixture','title':'Browser session test',
            'model':'ollama/qwen3.5:9b', 'updated_at':'2026-10-03T12:00:00Z', 'messages':[
                {'id':'user-1','role':'user','text':'Open the browser test page. (Synthetic test)'},
                {'id':'assistant-1','role':'assistant','text':'The dedicated browser is ready. You can watch here or take over.',
                 'sources':[{'url':'https://en.wikipedia.org/wiki/Brave_(web_browser)','title':'Disposable source fixture','domain':'en.wikipedia.org','snippet':'Synthetic source for drawer regression testing.'}]},
            ]}], 'spaces':[], 'smart_views':[]}
    @app.get('/api/models')
    def models(): return {'models':[{'id':'ollama/qwen3.5:9b','label':'Local model (test fixture)','provider':'ollama'}], 'active':{'id':'ollama/qwen3.5:9b'}}
    @app.get('/api/{unused:path}')
    def empty(unused:str): return {'plugins':[], 'items':[], 'automations':[], 'agents':[]}
    @app.get('/fixture/page', response_class=HTMLResponse)
    def page():
        return '''<!doctype html><html><head><title>Browser test page</title><style>
        body{font:20px/1.7 system-ui;background:#f8f7f3;color:#272629;max-width:900px;margin:80px auto;padding:0 48px}
        h1{font-size:46px;line-height:1.15;font-weight:600}p{max-width:650px}nav{font-size:16px;margin-bottom:70px}
        input{font:inherit;padding:12px;border:1px solid #ccc;border-radius:8px;width:320px}a{color:#315b8b}
        </style></head><body><nav>Vellum · Disposable browser fixture</nav><h1>A separate place to browse.</h1>
        <p>This is a synthetic local page for testing tabs, manual input, navigation and downloads.</p>
        <label>Your test text<br><input id="test-field" aria-label="Your test text"></label>
        <p><a href="/fixture/download">Download a test file</a></p><p><a href="/fixture/page?next=1">Another page</a></p></body></html>'''
    @app.get('/fixture/download')
    def download(): return Response(b'Disposable Vellum browser fixture.', media_type='text/plain', headers={'Content-Disposition':'attachment; filename="browser-test.txt"'})
    @app.get('/fixture/slow', response_class=HTMLResponse)
    async def slow():
        await asyncio.sleep(4)
        return page()
    @app.get('/fixture/video', response_class=HTMLResponse)
    def video():
        return '''<!doctype html><title>Local video fixture</title><style>
        body{margin:30px;font:20px system-ui;background:#ddd}video{display:block;width:85vw;height:65vh;background:black}
        </style><video id="video" autoplay muted controls></video><button id="fullscreen">Fullscreen</button><canvas hidden width="640" height="360"></canvas>
        <script>const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),video=document.querySelector('video');
        function draw(t){ctx.fillStyle='#203147';ctx.fillRect(0,0,640,360);ctx.fillStyle='#e6bc65';ctx.fillRect((t/5)%550,100,80,80);requestAnimationFrame(draw)}
        requestAnimationFrame(draw);video.srcObject=canvas.captureStream(30);
        const captions=video.addTextTrack('captions','English','en');captions.addCue(new VTTCue(0,600,'Visible local caption'));captions.mode='showing';
        document.querySelector('button').onclick=()=>video.requestFullscreen();</script>'''
    @app.get('/fixture/media-details')
    def media_details():
        async def read():
            page = playwright_tools._client._dedicated.active_page
            details = await page.evaluate('''() => {
              const v=document.querySelector('video'),b=document.querySelector('#fullscreen'),r=b?.getBoundingClientRect();
              return {fullscreen:!!document.fullscreenElement,box:r&&{x:r.x,y:r.y,width:r.width,height:r.height},
                media:v&&{time:v.currentTime,paused:v.paused,ready:v.readyState,network:v.networkState,error:v.error?.code||0,
                  captions:[...v.textTracks].map(t=>({mode:t.mode,active:t.activeCues?.length||0}))},
                playerError:(document.querySelector('.ytp-error-content-wrap')?.innerText||'').slice(0,200),
                captionText:(document.querySelector('.ytp-caption-window-container')?.innerText||'').slice(0,100),
                controls:['.ytp-play-button','.ytp-subtitles-button','.ytp-fullscreen-button'].map(selector=>{
                  const el=document.querySelector(selector),r=el?.getBoundingClientRect();
                  return {selector,pressed:el?.getAttribute('aria-pressed'),box:r&&{x:r.x,y:r.y,width:r.width,height:r.height}};
                })};
            }''')
            details['requests'] = list(media_requests)[-40:]
            return details
        return playwright_tools._worker.submit(read()).result(timeout=10)
    @app.get('/fixture/animation', response_class=HTMLResponse)
    def animation():
        return '''<!doctype html><title>Live frame fixture</title><style>
        body{margin:0;background:#f8f7f3}div{width:80px;height:80px;background:#315b8b;animation:move 1s linear infinite alternate}
        @keyframes move{to{transform:translateX(250px)}}
        </style><div></div>'''
    @app.get('/fixture/details')
    def details():
        async def read():
            page = playwright_tools._client._dedicated.active_page
            field = page.locator('#test-field')
            return {'box':await field.bounding_box(), 'value':await field.input_value()}
        return playwright_tools._worker.submit(read()).result(timeout=10)
    @app.get('/fixture/site-details')
    def site_details():
        async def read():
            page = playwright_tools._client._dedicated.active_page
            # This fixture uses a disposable profile and returns only public-page QA evidence.
            fields = await page.locator('input:not([type="hidden"]):not([type="password"])').evaluate_all('''els => els.slice(0,20).map(el => {
              const r=el.getBoundingClientRect(); return {name:el.getAttribute('aria-label')||el.placeholder||el.name,
              type:el.type, box:{x:r.x,y:r.y,width:r.width,height:r.height}};
            })''')
            links = await page.locator('a:visible').evaluate_all('''els => els.slice(0,30).map(el => {
              const r=el.getBoundingClientRect(); return {text:el.innerText.slice(0,80),href:el.href,
              box:{x:r.x,y:r.y,width:r.width,height:r.height}};
            })''')
            return {'title':await page.title(),'url':page.url,'text':(await page.locator('body').inner_text())[:2000], 'fields':fields,'links':links}
        return playwright_tools._worker.submit(read()).result(timeout=15)
    return app
