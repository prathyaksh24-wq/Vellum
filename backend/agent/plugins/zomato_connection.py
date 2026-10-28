"""Official Zomato MCP using Vellum's own local OAuth client and grant."""
from functools import lru_cache
import hashlib
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent.contracts.zomato_connection import ZomatoFlowStart, ZomatoFlowStatus, ZomatoMcpTool, ZomatoStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = 'https://mcp-server.zomato.com/mcp'
CALLBACK = 'http://localhost:8000/api/plugins/zomato/oauth/callback'
DOCS = 'https://github.com/Zomato/mcp-server-manifest'
SCOPES = 'mcp:tools mcp:resources mcp:prompts'


class ZomatoError(ValueError):
    pass


def tool_name(name):
    value = 'zomato_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


class ZomatoService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider('zomato', 'Zomato', SERVER,
        'https://mcp-server.zomato.com/authorize', 'https://mcp-server.zomato.com/token',
        'https://mcp-server.zomato.com/register', '', CALLBACK, SCOPES)
    error_type = ZomatoError
    status_model, tool_model = ZomatoStatus, ZomatoMcpTool
    flow_status_model, flow_start_model = ZomatoFlowStatus, ZomatoFlowStart

    def register_client(self, data):
        if data.get('client_id'):
            return self.client_fields(data)
        value = data.get('pending_registration')
        if value is None:
            response = self._json(self.provider.register, json={'client_name': 'Vellum',
                'redirect_uris': [CALLBACK], 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'none', 'scope': SCOPES})
            value = {key: response[key] for key in ('client_id', 'redirect_uris', 'token_endpoint_auth_method') if key in response}
            value['unexpected_secret'] = bool(response.get('client_secret'))
            if len(str(value)) > 12000:
                raise ZomatoError('Zomato returned an oversized registration. No account was connected.')
            # Keep the candidate privately so a shape correction cannot create
            # a duplicate remote client on the next click.
            self.save({**data, 'pending_registration': value})
        identifier = value.get('client_id')
        valid = isinstance(identifier, str) and 1 <= len(identifier) <= 1024 and identifier.isascii() and all(32 < ord(char) < 127 for char in identifier)
        if (not valid or value.get('unexpected_secret')
                or value.get('token_endpoint_auth_method', 'none') != 'none'
                or value.get('redirect_uris', [CALLBACK]) != [CALLBACK]):
            raise ZomatoError('Zomato did not register the requested public Vellum client. Check its callback approval. Diagnostic: zomato_registration_shape.')
        current = {**data, 'client_id': identifier}
        current.pop('pending_registration', None)
        self.save(current)
        return {'client_id': identifier}

    def start(self, request):
        with self.lock:
            flow = super().start(request)
            # Its discovery document supplies no RFC 9728 resource identifier.
            # Do not invent an audience or send an empty resource indicator.
            target = urlsplit(flow.authorization_url)
            query = [(key, value) for key, value in parse_qsl(target.query, keep_blank_values=True) if key != 'resource']
            address = urlunsplit((target.scheme, target.netloc, target.path, urlencode(query), ''))
            self.flows[flow.flow_id]['authorization_url'] = address
            return flow.model_copy(update={'authorization_url': address})

    def token_request(self, client, parameters):
        return self._json(self.provider.token, data={'client_id': client['client_id'],
            **{key: value for key, value in parameters.items() if key != 'resource'}})

    def _tokens(self, value):
        token, refresh, expires = value.get('access_token'), value.get('refresh_token'), value.get('expires_in')
        try:
            valid_expiry = expires is None or (type(expires) in (int, float) and expires > 0
                and math.isfinite(expires) and math.isfinite(self.clock() + expires))
        except (OverflowError, ValueError):
            valid_expiry = False
        if (not isinstance(token, str) or not 0 < len(token) <= 16000
                or str(value.get('token_type', '')).strip().lower() != 'bearer'
                or not valid_expiry or (refresh is not None and (not isinstance(refresh, str) or not 0 < len(refresh) <= 16000))):
            raise ZomatoError('Zomato returned invalid OAuth authorization fields. No sign-in was marked complete.')
        scope = value.get('scope')
        if scope is not None and (not isinstance(scope, str) or len(scope) > 4000):
            raise ZomatoError('Zomato returned invalid scope metadata.')
        data = {'access_token': token}
        if refresh is not None:
            data['refresh_token'] = refresh
        if expires is not None:
            data['expires_at'] = self.clock() + expires
        if scope is not None:
            data['granted_scopes'] = scope.split()
        return data

    def identity(self, data):
        return {'account_id': data.get('account_id') or 'zomato-grant:' + data['revision'],
            'account_name': 'Authorized Zomato account', 'granted_scopes': data.get('granted_scopes', [])}

    def public_identity(self, data):
        return {'auth_type': 'oauth' if data.get('access_token') else 'none', 'identity_verified': False}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if re.match(r'^(?:zomato_)?(?:create|update|delete|remove|add|place|checkout|pay|confirm|cancel|apply|clear|set|send|submit)_?', tool['name'], re.I):
                tool['read_only'] = False
        return tools


@lru_cache(maxsize=1)
def zomato_service():
    return ZomatoService()


def zomato_plugin_status():
    service = zomato_service()
    status = service.status()
    tools = service.cached_tools()
    return {'id': 'zomato', 'configured': status.configured, 'status': status.status, 'notes': status.message,
        'tools': ['zomato_mcp_catalog', 'zomato_mcp_describe', 'zomato_mcp_read', 'zomato_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata': {'connection': status.model_dump(), 'provider': 'Zomato', 'website': 'https://www.zomato.com',
            'integration': 'Official Zomato MCP server', 'documentation_url': DOCS,
            'credential_storage': 'Operating system credential store',
            'coverage': 'Complete live catalog for the authorized connection, with deferred schemas. Zomato controls client and callback access.'}}
