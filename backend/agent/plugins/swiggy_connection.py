"""One local Swiggy grant, separately selected Food and Instamart catalogs."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import secrets
from pathlib import Path

from agent.contracts.swiggy_connection import SwiggyFlowStart, SwiggyFlowStatus, SwiggyMcpTool, SwiggyStatus, SwiggyServiceStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVERS = {'food': 'https://mcp.swiggy.com/food', 'instamart': 'https://mcp.swiggy.com/im'}
LABELS = {'food': 'Swiggy', 'instamart': 'Instamart'}
SERVER = SERVERS['food']
RESOURCE = 'https://mcp.swiggy.com'
CALLBACK = 'http://localhost:8000/api/plugins/swiggy/oauth/callback'
DOCS = 'https://mcp.swiggy.com/builders/docs/start/authenticate/'
SCOPES = 'mcp:tools mcp:resources mcp:prompts'


class SwiggyError(ValueError):
    pass


def tool_name(name):
    value = 'swiggy_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


def split_tool(name):
    service, separator, original = name.partition('__')
    if not separator or service not in SERVERS or not original:
        raise SwiggyError('Choose an exact Food or Instamart tool from the Swiggy catalog.')
    return service, original


class SwiggyService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider('swiggy', 'Swiggy', SERVER,
        'https://mcp.swiggy.com/auth/authorize', 'https://mcp.swiggy.com/auth/token',
        'https://mcp.swiggy.com/auth/register', RESOURCE, CALLBACK, SCOPES)
    error_type = SwiggyError
    status_model, tool_model = SwiggyStatus, SwiggyMcpTool
    flow_status_model, flow_start_model = SwiggyFlowStatus, SwiggyFlowStart

    def selected(self, data):
        values = data.get('services', list(SERVERS))
        if not isinstance(values, list) or any(value not in SERVERS for value in values) or len(set(values)) != len(values):
            raise SwiggyError('Saved Swiggy services are invalid. Choose Food or Instamart again.')
        return values

    def client_fields(self, data):
        return {**super().client_fields(data), 'services': self.selected(data)}

    def register_client(self, data):
        if not self.selected(data):
            raise SwiggyError('Select Food or Instamart before signing in.')
        return {**super().register_client(data), 'services': self.selected(data)}

    def token_request(self, client, parameters):
        # Swiggy's published exchange and refresh contract uses JSON, not forms.
        return self._json(self.provider.token, json={'client_id': client['client_id'], **parameters})

    def _tokens(self, value):
        result = super()._tokens(value)
        scope = value.get('scope', '')
        if not isinstance(scope, str) or len(scope) > 4000:
            raise SwiggyError('Swiggy returned invalid scope metadata.')
        result['granted_scopes'] = scope.split()
        return result

    def identity(self, data):
        return {'account_id': data.get('account_id') or 'swiggy-grant:' + data['revision'],
            'account_name': 'Authorized Swiggy account', 'granted_scopes': data.get('granted_scopes', [])}

    def public_identity(self, data):
        return {'auth_type': 'oauth' if data.get('access_token') else 'none', 'identity_verified': False}

    def connector_for(self, data, service):
        from agent.mcp.plugin_runtime import PluginMcpConnector
        if service not in self.selected(data):
            raise SwiggyError('Enable this Swiggy service before using its tools.')
        return PluginMcpConnector(plugin_id='swiggy', name=service, root=Path(__file__).parent,
            transport='http', url=SERVERS[service], headers={'Authorization': 'Bearer ' + data['access_token']})

    def _catalog(self, data):
        result = []
        for service in self.selected(data):
            tools = super()._catalog(data, connector=self.connector_for(data, service))
            for tool in tools:
                original = tool['name']
                # Only known read-shaped verbs can be read tools. Unknown,
                # checkout, cart/address edits and order/payment tools get review.
                read = tool['read_only'] and original.startswith(('get_', 'search_', 'list_', 'fetch_', 'track_', 'check_', 'recommend_', 'your_go_to_'))
                result.append({**tool, 'name': service + '__' + original, 'original_name': original,
                    'service': service, 'read_only': read,
                    'description': LABELS[service] + ': ' + tool['description']})
        if not result:
            raise SwiggyError('Select Food or Instamart before loading tools.')
        return result

    def tools_for(self, service):
        return [{**deepcopy(tool), 'name': tool['original_name']} for tool in self.cached_tools() if tool['service'] == service]

    def configure(self, selection):
        if not self.enabled():
            raise SwiggyError('Enable Swiggy before changing its services.')
        with self.lock:
            data = self.load()
            if self.selected(data) == selection.services:
                return self.status()
            # Selection changes invalidate in-flight callbacks and reviews.
            if data.get('access_token') and selection.services:
                data = self.require()
            candidate = {**data, 'services': selection.services, 'revision': secrets.token_urlsafe(32)}
            self._cancel_flows()
            if data.get('access_token') and selection.services:
                tools = self._catalog(candidate)
            else:
                tools = []
            self.save({**candidate, 'mcp_tool_count': len(tools)})
            self.tools, self.tools_revision = tools, candidate['revision']
        self.invalidator()
        return self.status()

    def status(self):
        status = super().status()
        try:
            selected = self.selected(self.load())
        except SwiggyError:
            selected = []
        return status.model_copy(update={'services': [SwiggyServiceStatus(id=key, name=LABELS[key], enabled=key in selected,
            connected=status.connected and key in selected,
            tool_count=sum(tool.get('service') == key for tool in self.tools)) for key in SERVERS],
            'connected': status.connected and bool(selected),
            'status': status.status if selected else 'disabled',
            'message': status.message if selected else 'Food and Instamart are switched off. Choose a service to use Swiggy.'})


@lru_cache(maxsize=1)
def swiggy_service():
    return SwiggyService()


def swiggy_plugin_status():
    service = swiggy_service()
    status = service.status()
    tools = service.cached_tools()
    return {'id': 'swiggy', 'configured': status.configured, 'status': status.status, 'notes': status.message,
        'tools': ['swiggy_mcp_catalog', 'swiggy_mcp_describe', 'swiggy_mcp_read', 'swiggy_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata': {'connection': status.model_dump(), 'provider': 'Swiggy', 'website': 'https://www.swiggy.com',
            'integration': 'Official Swiggy Food and Instamart MCP servers', 'documentation_url': DOCS,
            'credential_storage': 'Operating system credential store',
            'coverage': 'Complete published catalogs for selected Food and Instamart services; schemas load on demand.'}}
