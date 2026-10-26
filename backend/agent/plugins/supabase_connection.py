"""Supabase platform OAuth, separate from Vellum's own sign-in configuration."""
from functools import lru_cache
import hashlib
import re

import httpx

from agent.contracts.supabase_connection import SupabaseFlowStart, SupabaseFlowStatus, SupabaseMcpTool, SupabaseStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = 'https://mcp.supabase.com/mcp?features=docs,account,database,debugging,development,functions,branching,storage'
RESOURCE = 'https://mcp.supabase.com/mcp'
CALLBACK = 'http://127.0.0.1:8000/api/plugins/supabase/oauth/callback'
REGISTER = 'https://api.supabase.com/platform/oauth/apps/register'
DOCS = 'https://supabase.com/docs/guides/ai-tools/mcp'
SCOPES = 'organizations:read projects:read projects:write database:write database:read analytics:read secrets:read edge_functions:read edge_functions:write environment:read environment:write storage:read storage:write'


class SupabaseError(ValueError):
    pass


def tool_name(name):
    value = 'supabase_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


class SupabaseService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider('supabase', 'Supabase', SERVER,
        'https://api.supabase.com/v1/oauth/authorize', 'https://api.supabase.com/v1/oauth/token',
        REGISTER, RESOURCE, CALLBACK, SCOPES)
    error_type = SupabaseError
    status_model, tool_model = SupabaseStatus, SupabaseMcpTool
    flow_status_model, flow_start_model = SupabaseFlowStatus, SupabaseFlowStart

    def client_fields(self, data):
        return {key: data[key] for key in ('client_id', 'client_secret', 'token_auth_method') if data.get(key)}

    def register_client(self, data):
        if data.get('client_id') and data.get('client_secret'):
            return self.client_fields(data)
        value = self._json(REGISTER, json={'client_name': 'Vellum', 'redirect_uris': [CALLBACK],
            'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
            'token_endpoint_auth_method': 'client_secret_basic', 'scope': SCOPES})
        identifier, secret = value.get('client_id'), value.get('client_secret')
        method = value.get('token_endpoint_auth_method', 'client_secret_basic')
        if (not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,200}', identifier)
                or not isinstance(secret, str) or not 8 <= len(secret) <= 4096
                or method not in {'client_secret_basic', 'client_secret_post'}
                or value.get('redirect_uris', [CALLBACK]) != [CALLBACK]):
            raise SupabaseError('Supabase did not register the expected Vellum OAuth client. No account was connected.')
        return {'client_id': identifier, 'client_secret': secret, 'token_auth_method': method}

    def token_request(self, client, parameters):
        secret = client.get('client_secret')
        if not secret:
            raise SupabaseError('Supabase client registration is incomplete. Start sign-in again.')
        if client.get('token_auth_method') == 'client_secret_post':
            return self._json(self.provider.token, data={**parameters,
                'client_id': client['client_id'], 'client_secret': secret})
        return self._json(self.provider.token, data=parameters, auth=httpx.BasicAuth(client['client_id'], secret))

    def identity(self, data):
        # The authenticated MCP catalog verifies authorization. Do not fetch project data
        # or claim a person identity when the connection check supplies none.
        return {'account_id': data.get('account_id') or 'supabase-grant:' + data['revision'],
            'account_name': 'Authorized Supabase account', 'granted_scopes': SCOPES.split()}

    def public_identity(self, data):
        return {'auth_type': 'oauth' if data.get('access_token') else 'none', 'identity_verified': False}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if tool['name'] in {'execute_sql', 'apply_migration', 'confirm_cost'}:
                tool['read_only'] = False
        return tools


@lru_cache(maxsize=1)
def supabase_service():
    return SupabaseService()


def supabase_plugin_status():
    service = supabase_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except SupabaseError:
        tools = []
    return {'id': 'supabase', 'configured': status.configured, 'status': status.status, 'notes': status.message,
        'tools': ['supabase_mcp_catalog', 'supabase_mcp_describe', 'supabase_mcp_read', 'supabase_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata': {'connection': status.model_dump(), 'provider': 'Supabase', 'website': 'https://supabase.com',
            'integration': 'Official Supabase MCP server', 'documentation_url': DOCS,
            'credential_storage': 'Operating system credential store',
            'coverage': 'All documented feature groups, including Storage; complete published tool catalog with deferred schemas. Supabase scopes, project permissions, plan limits and server confirmations apply.'}}
