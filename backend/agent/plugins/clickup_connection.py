"""ClickUp's official OAuth-only MCP connection, using Vellum's own client."""
from functools import lru_cache
import hashlib
import logging
import math
import re

from agent.contracts.clickup_connection import ClickUpFlowStart, ClickUpFlowStatus, ClickUpMcpTool, ClickUpStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = 'https://mcp.clickup.com/mcp'
RESOURCE = 'https://mcp.clickup.com'
CALLBACK = 'http://127.0.0.1:8000/api/plugins/clickup/oauth/callback'
REGISTER = 'https://mcp.clickup.com/oauth/register'
DOCS = 'https://developer.clickup.com/docs/mcp-tools'
SCOPES = 'read write'
logger = logging.getLogger(__name__)


class ClickUpError(ValueError):
    pass


def tool_name(name):
    value = 'clickup_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


class ClickUpService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider('clickup', 'ClickUp', SERVER, 'https://mcp.clickup.com/oauth/authorize',
        'https://mcp.clickup.com/oauth/token', REGISTER, RESOURCE, CALLBACK, SCOPES)
    error_type = ClickUpError
    status_model, tool_model = ClickUpStatus, ClickUpMcpTool
    flow_status_model, flow_start_model = ClickUpFlowStatus, ClickUpFlowStart

    def register_client(self, data):
        if data.get('client_id'):
            return self.client_fields(data)
        # ClickUp advertises authorization_code only, not refresh_token grants.
        value = data.get('pending_registration')
        if value is None:
            value = self._json(REGISTER, json={'client_name':'Vellum', 'redirect_uris':[CALLBACK],
                'grant_types':['authorization_code'], 'response_types':['code'],
                'token_endpoint_auth_method':'none', 'scope':SCOPES})
            # Retain a bounded registration privately before validation, so a
            # format correction does not create another remote client on retry.
            value = {key:value[key] for key in ('client_id','token_endpoint_auth_method','redirect_uris') if key in value}
            if len(str(value)) > 12000:
                raise ClickUpError('ClickUp returned an oversized client registration. No account was connected.')
            self.save({**data, 'pending_registration':value})
        identifier = value.get('client_id')
        # OAuth client IDs are opaque strings; they need not use a UUID alphabet.
        valid_id = isinstance(identifier,str) and 1 <= len(identifier) <= 1024 and identifier.isascii() and all(32 < ord(c) < 127 for c in identifier)
        method_ok = value.get('token_endpoint_auth_method','none') == 'none'
        callback_ok = value.get('redirect_uris',[CALLBACK]) == [CALLBACK]
        if not valid_id or not method_ok or not callback_ok:
            method = value.get('token_endpoint_auth_method','none')
            safe_method = method if method in {'none','client_secret_basic','client_secret_post'} else 'unexpected'
            logger.warning('ClickUp registration rejected: id_valid=%s auth_method=%s callback_matches=%s',valid_id,safe_method,callback_ok)
            raise ClickUpError('ClickUp returned an incompatible client registration. No account was connected. Diagnostic: clickup_registration_shape.')
        data.pop('pending_registration', None)
        self.save({**data, 'client_id':identifier})
        return {'client_id':identifier}

    def _tokens(self, value):
        token, refresh, expires = value.get('access_token'), value.get('refresh_token'), value.get('expires_in')
        token_ok = isinstance(token,str) and bool(token) and len(token) <= 16000
        type_ok = str(value.get('token_type','')).strip().lower() == 'bearer'
        refresh_ok = refresh is None or (isinstance(refresh,str) and bool(refresh) and len(refresh) <= 16000)
        # ClickUp currently issues 315,360,000-second (ten-year) grants. OAuth
        # does not impose a one-year maximum; honor the provider's finite TTL.
        try:
            expires_ok = expires is None or (type(expires) in (int,float) and expires > 0
                and math.isfinite(expires) and math.isfinite(self.clock() + expires))
        except (OverflowError, ValueError):
            expires_ok = False
        if not all((token_ok, type_ok, refresh_ok, expires_ok)):
            fields = [name for name,valid in (('access_token',token_ok),('token_type',type_ok),
                ('refresh_token',refresh_ok),('expires_in',expires_ok)) if not valid]
            # Report field shape only. Never log response bodies, token strings,
            # authorization codes or credential-bearing callback addresses.
            logger.warning('ClickUp token validation rejected fields: %s', ','.join(fields))
            raise ClickUpError('ClickUp returned an invalid OAuth authorization response. Diagnostic fields: ' + ', '.join(fields) + '.')
        scope = value.get('scope', SCOPES)
        if not isinstance(scope,str) or not scope.split() or not set(scope.split()) <= {'read','write'}:
            raise ClickUpError('ClickUp returned unexpected OAuth permissions.')
        data = {'access_token':token, 'granted_scopes':scope.split()}
        if refresh is not None:
            data['refresh_token'] = refresh
        if expires is not None:
            data['expires_at'] = self.clock() + expires
        return data

    def status(self):
        status = super().status()
        if status.connected:
            data = self.load()
            if data.get('expires_at') and self.clock() >= data['expires_at'] - 60:
                return status.model_copy(update={'connected':False, 'status':'reauthorization_required',
                    'message':'ClickUp authorization expired. Sign in again to renew access.'})
        return status

    def identity(self, data):
        # Authenticated tools/list proves access, not a person's identity.
        return {'account_id':data.get('account_id') or 'clickup-grant:' + data['revision'],
            'account_name':'Authorized ClickUp account', 'granted_scopes':data.get('granted_scopes',[])}

    def public_identity(self, data):
        return {'auth_type':'oauth' if data.get('access_token') else 'none', 'identity_verified':False}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if re.match(r'^(?:clickup_)?(?:create|update|delete|remove|add|move|send|start|stop|set|attach|upload)_', tool['name'], re.I):
                tool['read_only'] = False
        return tools


@lru_cache(maxsize=1)
def clickup_service():
    return ClickUpService()


def clickup_plugin_status():
    service = clickup_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except ClickUpError:
        tools = []
    return {'id':'clickup', 'configured':status.configured, 'status':status.status, 'notes':status.message,
        'tools':['clickup_mcp_catalog','clickup_mcp_describe','clickup_mcp_read','clickup_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata':{'connection':status.model_dump(), 'provider':'ClickUp', 'website':'https://clickup.com',
            'integration':'Official ClickUp MCP server', 'documentation_url':DOCS,
            'credential_storage':'Operating system credential store',
            'coverage':'Complete catalog published for this OAuth connection, with deferred schemas. Workspace permissions and provider usage limits apply.'}}
