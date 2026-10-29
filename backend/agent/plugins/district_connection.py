"""Official District MCP using Vellum's own registered client and grant."""
from functools import lru_cache
import hashlib
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent.contracts.district_connection import DistrictFlowStart, DistrictFlowStatus, DistrictMcpTool, DistrictStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = 'https://mcp-server.district.in/mcp'
CALLBACK = 'http://localhost:8000/api/plugins/district/oauth/callback'
DOCS = 'https://chatgpt.com/plugins/plugin_asdk_app_699d871f7dfc819192b74090657868fb'
SCOPES = ''
# Reviewed against District's authenticated catalog descriptions and inputs.
# Missing readOnlyHint metadata must not turn discovery into booking approvals.
# Keep this exact: new tools retain the provider/default classification.
READ_TOOLS = frozenset({
    'search_dining_restaurants', 'get_dynamic_filters',
    'get_dining_restaurants_details', 'get_table_reservation_slots',
    'get_booking_details', 'get_dynamic_filters_movie', 'search_movies',
    'search_theatres', 'search_shows', 'get_movie_critique_reviews',
    'get_dynamic_filters_event', 'search_events', 'search_event_venues',
    'search_artists',
})


class DistrictError(ValueError):
    pass


def tool_name(name):
    value = 'district_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


class DistrictService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider('district', 'District', SERVER,
        'https://mcp-server.district.in/authorize', 'https://mcp-server.district.in/token',
        'https://mcp-server.district.in/register', '', CALLBACK, SCOPES)
    error_type = DistrictError
    status_model, tool_model = DistrictStatus, DistrictMcpTool
    flow_status_model, flow_start_model = DistrictFlowStatus, DistrictFlowStart

    def client_fields(self, data):
        return {key: data[key] for key in ('client_id', 'client_secret', 'token_endpoint_auth_method') if data.get(key)}

    def register_client(self, data):
        if data.get('client_id'):
            return self.client_fields(data)
        value = data.get('pending_registration')
        legacy_lost_secret = bool(value and value.get('unexpected_secret') and not value.get('client_secret'))
        if legacy_lost_secret and data.get('registration_replacement_attempted'):
            raise DistrictError('District app registration needs review before another retry. No account was connected.')
        if value is None or legacy_lost_secret:
            if legacy_lost_secret:
                # One replacement for the first version's shape-only record.
                # Subsequent attempts reuse the complete private registration.
                data = {**data, 'registration_replacement_attempted': True}
                self.save(data)
            response = self._json(self.provider.register, json={'client_name': 'Vellum',
                'redirect_uris': [CALLBACK], 'grant_types': ['authorization_code', 'refresh_token'],
                'response_types': ['code'], 'token_endpoint_auth_method': 'client_secret_post'})
            value = {key: response[key] for key in ('client_id', 'client_secret', 'redirect_uris', 'token_endpoint_auth_method') if key in response}
            if len(str(value)) > 20000:
                raise DistrictError('District returned an oversized registration. No account was connected.')
            # Keep the candidate privately so a shape correction cannot create
            # a duplicate remote client on the next click.
            self.save({**data, 'pending_registration': value})
        identifier = value.get('client_id')
        valid = isinstance(identifier, str) and 1 <= len(identifier) <= 1024 and identifier.isascii() and all(32 < ord(char) < 127 for char in identifier)
        method = value.get('token_endpoint_auth_method', 'none')
        secret = value.get('client_secret')
        secret_ok = isinstance(secret, str) and 0 < len(secret) <= 16000 and all(32 < ord(char) < 127 for char in secret)
        if (not valid or method not in {'none', 'client_secret_post', 'client_secret_basic'}
                or (method != 'none' and not secret_ok)
                or value.get('redirect_uris', [CALLBACK]) != [CALLBACK]):
            raise DistrictError('District returned incompatible client authentication or callback fields. No account was connected. Diagnostic: district_registration_shape.')
        fields = self.client_fields({**value, 'token_endpoint_auth_method': method})
        current = {**data, **fields}
        current.pop('pending_registration', None)
        current.pop('registration_replacement_attempted', None)
        self.save(current)
        return fields

    def start(self, request):
        with self.lock:
            flow = super().start(request)
            # Its discovery document supplies no RFC 9728 resource identifier.
            # Do not invent an audience or send an empty resource indicator.
            target = urlsplit(flow.authorization_url)
            query = [(key, value) for key, value in parse_qsl(target.query, keep_blank_values=True) if key not in {'resource', 'scope'}]
            address = urlunsplit((target.scheme, target.netloc, target.path, urlencode(query), ''))
            self.flows[flow.flow_id]['authorization_url'] = address
            return flow.model_copy(update={'authorization_url': address})

    def token_request(self, client, parameters):
        data = {'client_id': client['client_id'], **{key: value for key, value in parameters.items() if key != 'resource'}}
        method = client.get('token_endpoint_auth_method', 'none')
        if method == 'client_secret_post' and client.get('client_secret'):
            return self._json(self.provider.token, data={**data, 'client_secret': client['client_secret']})
        if method == 'client_secret_basic' and client.get('client_secret'):
            return self._json(self.provider.token, data=data, auth=(client['client_id'], client['client_secret']))
        if method != 'none':
            raise DistrictError('District app authentication is incomplete. Its client secret is unavailable.')
        return self._json(self.provider.token, data=data)

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
            raise DistrictError('District returned invalid OAuth authorization fields. No sign-in was marked complete.')
        scope = value.get('scope')
        if scope is not None and (not isinstance(scope, str) or len(scope) > 4000):
            raise DistrictError('District returned invalid scope metadata.')
        data = {'access_token': token}
        if refresh is not None:
            data['refresh_token'] = refresh
        if expires is not None:
            data['expires_at'] = self.clock() + expires
        if scope is not None:
            data['granted_scopes'] = scope.split()
        return data

    def identity(self, data):
        return {'account_id': data.get('account_id') or 'district-grant:' + data['revision'],
            'account_name': 'Authorized District account', 'granted_scopes': data.get('granted_scopes', [])}

    def public_identity(self, data):
        return {'auth_type': 'oauth' if data.get('access_token') else 'none', 'identity_verified': False}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if tool['name'] in READ_TOOLS:
                tool['read_only'] = True
            elif re.match(r'^(?:district_)?(?:create|update|delete|remove|add|place|checkout|pay|confirm|cancel|apply|clear|set|send|submit|book|reserve|purchase)_?', tool['name'], re.I):
                tool['read_only'] = False
        return tools


@lru_cache(maxsize=1)
def district_service():
    return DistrictService()


def district_plugin_status():
    service = district_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except DistrictError:
        tools = []
    return {'id': 'district', 'configured': status.configured, 'status': status.status, 'notes': status.message,
        'tools': ['district_mcp_catalog', 'district_mcp_describe', 'district_mcp_read', 'district_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata': {'connection': status.model_dump(), 'provider': 'District', 'website': 'https://www.district.in',
            'integration': 'Official District MCP server', 'documentation_url': DOCS,
            'credential_storage': 'Operating system credential store',
            'coverage': 'Complete live catalog for the authorized connection, with deferred schemas. District controls client and callback access.'}}
