"""SerpAPI's official hosted MCP connection and local credential owner."""
from functools import lru_cache
import hashlib
import secrets

from agent.config import get_settings
from agent.contracts.serpapi_connection import SerpApiMcpTool, SerpApiStatus
from agent.plugins.mcp_oauth import OfficialOAuthProvider
from agent.plugins.web_mcp import WebMcpConnection

SERVER = 'https://mcp.serpapi.com/mcp'
CALLBACK = "http://127.0.0.1:8000/api/plugins/serpapi/oauth/callback"
DOCS = 'https://github.com/serpapi/serpapi-mcp'

class SerpApiError(ValueError):
    pass

def tool_name(name):
    value = "serpapi_tool_" + name.replace("-", "_")
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]

class SerpApiService(WebMcpConnection):
    provider = OfficialOAuthProvider('serpapi', 'SerpAPI', SERVER, '',
        '', '', 'https://mcp.serpapi.com/mcp', CALLBACK, '')
    error_type = SerpApiError
    status_model, tool_model = SerpApiStatus, SerpApiMcpTool

    def configured_credential(self):
        return get_settings().serpapi_api_key

    def identity(self, data):
        # Account API requires api_key in the query; keep it server-side and never log URLs/bodies.
        value = self._json('https://serpapi.com/account.json', method='GET', params={'api_key': data['access_token']})
        identifier = value.get('account_id')
        if not isinstance(identifier, str) or not identifier:
            raise SerpApiError('SerpAPI did not verify this key. Check your dashboard and account status.')
        return {'account_id': identifier, 'account_name': value.get('account_email') or 'SerpAPI account',
            'workspace_name': 'SerpAPI account', 'identity_verified': True, 'granted_scopes': []}

    def start(self, request):
        raise SerpApiError('SerpAPI uses an API key. Open its connection form in Vellum.')

    def status(self):
        value = super().status()
        if not value.configured:
            value.message = 'Connect your SerpAPI key to use web search and the official MCP tools.'
        return value

    def stage(self, token):
        token = token.strip()
        if not 8 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise SerpApiError('Enter a valid SerpAPI key in the local connection form.')
        with self.lock:
            pending = {k:v for k,v in getattr(self, '_pending', {}).items() if v[1] > self.clock()}
            if len(pending) >= 16:
                raise SerpApiError('Too many pending connections. Wait a few minutes and retry.')
            reference = secrets.token_urlsafe(32)
            pending[reference] = (token, self.clock() + 600)
            self._pending = pending
        return reference

    def discard(self, reference):
        with self.lock:
            getattr(self, '_pending', {}).pop(reference, None)

    def connect(self, reference):
        with self.lock:
            pending = getattr(self, '_pending', {}).pop(reference, None)
        if not pending or pending[1] <= self.clock():
            raise SerpApiError('The staged key expired. Enter it again in Vellum.')
        return self.connect_key(pending[0])

@lru_cache(maxsize=1)
def serpapi_service():
    return SerpApiService()

def serpapi_plugin_status():
    service = serpapi_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except SerpApiError:
        tools = []
    return {"id": 'serpapi', "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["serpapi_mcp_catalog", "serpapi_mcp_describe", "serpapi_mcp_read", "serpapi_mcp_execute", *[tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": 'SerpAPI', "website": 'https://serpapi.com',
            "integration": "Official SerpAPI MCP server", "documentation_url": DOCS,
            "credential_storage": "Operating system credential store",
            "coverage": "Complete selected official MCP tool catalog; schemas load on demand. Provider account, plan and usage limits apply."}}
