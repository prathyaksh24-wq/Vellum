"""Disposable UI/Brave fixture. Never load the user's API, profile or conversations."""
from contextlib import asynccontextmanager
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
    action_api.get_app_action_runtime = lambda: runtime
    runtime = AppActionRuntime()
    @asynccontextmanager
    async def lifespan(_app):
        yield
        await playwright_tools.shutdown_async()
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
                {'id':'assistant-1','role':'assistant','text':'The dedicated browser is ready. You can watch here or take over.'},
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
    @app.get('/fixture/details')
    def details():
        async def read():
            page = playwright_tools._client._dedicated.active_page
            field = page.locator('#test-field')
            return {'box':await field.bounding_box(), 'value':await field.input_value()}
        return playwright_tools._worker.submit(read()).result(timeout=10)
    return app
