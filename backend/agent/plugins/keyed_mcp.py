"""Small setup adapters over existing MCP transport and OS credential ownership."""
from functools import lru_cache
from pathlib import Path
import secrets
import shutil

from agent.config import get_settings
from agent.contracts.keyed_mcp import KeyedMcpStatus, KeyedMcpTool
from agent.plugins.mcp_oauth import OfficialOAuthProvider
from agent.plugins.web_mcp import WebMcpConnection

CONTEXT7_URL = 'https://mcp.context7.com/mcp'
BRAVE_PACKAGE = '@brave/brave-search-mcp-server@2.1.4'
BRAVE_ARGS = ('-y', BRAVE_PACKAGE, '--transport', 'stdio')
PROVIDERS = {
    'brave': ('Brave Search', 'https://brave.com/search/api/', 'https://github.com/brave/brave-search-mcp-server'),
    'context7': ('Context7', 'https://context7.com', 'https://github.com/upstash/context7'),
}

class KeyedMcpError(ValueError):
    pass

class KeyedMcpService(WebMcpConnection):
    error_type = KeyedMcpError
    status_model, tool_model = KeyedMcpStatus, KeyedMcpTool
    identity_keys = ()

    def __init__(self, provider, **kwargs):
        if provider not in PROVIDERS:
            raise KeyedMcpError('Unknown documentation/search connector.')
        name = PROVIDERS[provider][0]
        self.provider = OfficialOAuthProvider(provider, name, CONTEXT7_URL if provider == 'context7' else '', '', '', '', '', '', '')
        super().__init__(**kwargs)

    def configured_credential(self):
        settings = get_settings()
        return settings.brave_api_key if self.provider.plugin_id == 'brave' else settings.context7_api_key

    def identity(self, data):
        # Catalog access verifies a credential, not the identity of a person.
        return {'workspace_name': self.provider.name + ' API', 'identity_verified': False}

    def connector(self, data):
        from agent.mcp.plugin_runtime import PluginMcpConnector
        common = dict(plugin_id=self.provider.plugin_id, name=self.provider.plugin_id,
            root=Path(__file__).parent, credential_digest=data['revision'])
        if self.provider.plugin_id == 'brave':
            command = shutil.which('npx')
            if not command:
                raise KeyedMcpError('Install Node.js 22 or later to run Brave’s official MCP server.')
            return PluginMcpConnector(**common, transport='stdio', command=command, args=BRAVE_ARGS,
                env={'BRAVE_API_KEY': data['access_token']})
        return PluginMcpConnector(**common, transport='http', url=CONTEXT7_URL,
            headers={'Authorization': 'Bearer ' + data['access_token']})

    def _catalog(self, data, **kwargs):
        tools = super()._catalog(data, **kwargs)
        known_reads = {'resolve-library-id', 'query-docs'} if self.provider.plugin_id == 'context7' else {
            'brave_web_search', 'brave_local_search', 'brave_video_search', 'brave_image_search',
            'brave_news_search', 'brave_summarizer'}
        for tool in tools:
            if tool['name'] in known_reads:
                tool['read_only'] = True
        return tools

    def status(self):
        status = super().status()
        if not status.configured and status.status != 'keyring_unavailable':
            status.message = ('Verify the configured API key to connect ' if self.configured_credential()
                else 'Add an API key in this local form to connect ') + self.provider.name + '.'
        return status

    def stage(self, token):
        token = token.strip()
        if not 8 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise KeyedMcpError('Enter a valid API key in the local connection form.')
        with self.lock:
            pending = {key: value for key, value in getattr(self, '_pending', {}).items() if value[1] > self.clock()}
            if len(pending) >= 16:
                raise KeyedMcpError('Too many pending keys. Wait before trying again.')
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
            raise KeyedMcpError('This staged key expired. Enter it again.')
        return self.connect_key(pending[0])

    def api_key(self):
        if not self.enabled():
            raise KeyedMcpError('Enable ' + self.provider.name + ' before using it.')
        data = self.load()
        if data.get('managed'):
            return self.require()['access_token']
        return self.configured_credential()

@lru_cache(maxsize=2)
def keyed_mcp_service(provider):
    return KeyedMcpService(provider)

def keyed_mcp_status(provider):
    service = keyed_mcp_service(provider)
    status = service.status()
    return {'id': provider, 'configured': status.configured, 'status': status.status, 'notes': status.message,
        'metadata': {'connection': status.model_dump(), 'provider': service.provider.name,
            'website': PROVIDERS[provider][1], 'documentation_url': PROVIDERS[provider][2],
            'integration': 'Official ' + service.provider.name + ' MCP server',
            'credential_storage': 'Operating system credential store'}}
