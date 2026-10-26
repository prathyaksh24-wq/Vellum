"""Official Vercel MCP OAuth; Vellum identifies itself as its own client."""
from functools import lru_cache
import hashlib
import re

from agent.contracts.vercel_connection import VercelFlowStart, VercelFlowStatus, VercelMcpTool, VercelStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = 'https://mcp.vercel.com'
RESOURCE = 'https://mcp.vercel.com/'
CALLBACK = 'http://127.0.0.1:8000/api/plugins/vercel/oauth/callback'
REGISTER = 'https://vercel.com/api/login/oauth/register'
DOCS = 'https://vercel.com/docs/agent-resources/vercel-mcp'
SCOPES = 'openid email profile offline_access'


class VercelError(ValueError):
    pass


def tool_name(name):
    value = 'vercel_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


class VercelService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider('vercel', 'Vercel', SERVER, 'https://vercel.com/oauth/authorize',
        'https://vercel.com/api/login/oauth/token', REGISTER, RESOURCE, CALLBACK, SCOPES)
    error_type = VercelError
    status_model, tool_model = VercelStatus, VercelMcpTool
    flow_status_model, flow_start_model = VercelFlowStatus, VercelFlowStart

    def register_client(self, data):
        if data.get('client_id'):
            return self.client_fields(data)
        value = self._json(REGISTER, json={'client_name':'Vellum', 'application_type':'native',
            'redirect_uris':[CALLBACK], 'grant_types':['authorization_code','refresh_token'],
            'response_types':['code'], 'token_endpoint_auth_method':'none', 'scope':SCOPES})
        identifier = value.get('client_id')
        if (not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{5,200}',identifier)
                or value.get('client_secret') or value.get('token_endpoint_auth_method','none') != 'none'
                or value.get('redirect_uris',[CALLBACK]) != [CALLBACK]):
            raise VercelError('Vercel did not register the expected Vellum public client. Review Vercel client approval and callback requirements.')
        return {'client_id':identifier}

    def identity(self, data):
        # Verification is on the authenticated MCP resource. Its catalog does not
        # establish a person's identity or which team owns a selected project.
        return {'account_id':data.get('account_id') or 'vercel-grant:' + data['revision'],
            'account_name':'Authorized Vercel account', 'granted_scopes':SCOPES.split()}

    def public_identity(self, data):
        return {'auth_type':'oauth' if data.get('access_token') else 'none', 'identity_verified':False}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if tool['name'] in {'create_deployment', 'deploy_to_vercel', 'execute_cli_command'}:
                tool['read_only'] = False
        return tools


@lru_cache(maxsize=1)
def vercel_service():
    return VercelService()


def vercel_plugin_status():
    service = vercel_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except VercelError:
        tools = []
    return {'id':'vercel', 'configured':status.configured, 'status':status.status, 'notes':status.message,
        'tools':['vercel_mcp_catalog','vercel_mcp_describe','vercel_mcp_read','vercel_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata':{'connection':status.model_dump(), 'provider':'Vercel', 'website':'https://vercel.com',
            'integration':'Official Vercel MCP server', 'documentation_url':DOCS,
            'credential_storage':'Operating system credential store',
            'coverage':'Complete catalog published for this OAuth connection, with deferred schemas. Vercel client approval, team grants and project permissions determine access.'}}
