"""Opt-in local Ollama + actual Brave vertical slice on disposable content."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('VELLUM_BROWSER_PLANNER_SMOKE') != '1', reason='Requires installed local model and Brave')


def test_local_model_reads_actual_dedicated_browser_page(monkeypatch, tmp_path):
    from agent.agents.browser import BrowserAgent
    from agent.llm.providers import get_provider_registry
    from agent.mcp import dedicated_browser, playwright_tools
    from agent.tools.capabilities.browser_service import BrowserCapabilityService
    class Pages(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<title>Browser fixture</title><h1>A separate place to browse</h1><p>Synthetic local test content.</p>')
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Pages)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(dedicated_browser, '_resolve_against_repo', lambda path: tmp_path/path.name)
    registry = get_provider_registry()
    registry.refresh_local_models(force=True)
    available = [model for model in registry.list_models('ollama') if 'embed' not in model.id]
    assert available, 'Install a local chat model first.'
    registry.set_active(available[0].id)
    try:
        url = f'http://127.0.0.1:{server.server_port}/'
        response = BrowserAgent(tool_registry=BrowserCapabilityService().build_registry()).answer(f'Open {url} and report its heading. Read only; stay on this URL.')
        print(f'Local model: {available[0].id}; browser response: {response.model_dump_json()}')
        assert response.status == 'answered'
        assert 'separate place' in response.summary.lower()
        assert playwright_tools.browser_session('status').tabs[0].url == url
    finally:
        asyncio.run(playwright_tools.shutdown_async())
        server.shutdown()
        server.server_close()
