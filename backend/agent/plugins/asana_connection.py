"""Official Asana V2 MCP OAuth with locally staged MCP-app credentials."""
from functools import lru_cache
import hashlib
import math
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent.contracts.asana_connection import AsanaFlowStart, AsanaFlowStatus, AsanaMcpTool, AsanaStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = RESOURCE = 'https://mcp.asana.com/v2/mcp'
CALLBACK = 'http://localhost:8000/api/plugins/asana/oauth/callback'
DOCS = 'https://developers.asana.com/docs/integrating-with-asanas-mcp-server'
SETUP = 'https://app.asana.com/0/my-apps'


class AsanaError(ValueError):
    pass


def tool_name(name):
    value = 'asana_tool_' + name.replace('-', '_')
    return value if len(value) <= 64 else value[:45] + '_' + hashlib.sha256(value.encode()).hexdigest()[:12]


class AsanaService(OfficialMcpOAuthService):
    # V2 requires a pre-registered Asana MCP app. Explicit scopes are omitted;
    # access follows the authorizing user's permissions and app distribution.
    provider = OfficialOAuthProvider('asana','Asana',SERVER,
        'https://app.asana.com/-/oauth_authorize','https://app.asana.com/-/oauth_token','',RESOURCE,CALLBACK,'')
    error_type = AsanaError
    status_model, tool_model = AsanaStatus, AsanaMcpTool
    flow_status_model, flow_start_model = AsanaFlowStatus, AsanaFlowStart

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._staged = {}

    def stage(self, credentials):
        if not self.enabled():
            raise AsanaError('Enable Asana before setting up its app.')
        with self.lock:
            self._staged = {key:item for key,item in self._staged.items() if item[1] > self.clock()}
            if len(self._staged) >= 8:
                raise AsanaError('Too many pending setup requests. Cancel a review or wait before retrying.')
            reference = secrets.token_urlsafe(32)
            self._staged[reference] = ({'client_id':credentials.client_id,
                'client_secret':credentials.client_secret.get_secret_value()}, self.clock()+600)
        return reference

    def discard(self, reference):
        with self.lock:
            self._staged.pop(reference,None)

    def configure(self, reference):
        if not self.enabled():
            raise AsanaError('Enable Asana before setting up its app.')
        with self.lock:
            staged = self._staged.pop(reference,None)
            if not staged or staged[1] <= self.clock():
                raise AsanaError('Asana app setup expired. Enter its credentials through the local form again.')
            data, client = self.load(), staged[0]
            same = data.get('client_id') == client['client_id'] and secrets.compare_digest(
                data.get('client_secret',''),client['client_secret'])
            if data.get('access_token') and not same:
                raise AsanaError('Disconnect Asana before replacing its MCP app credentials.')
            if not same:
                self._cancel_flows()
                self.save({**client,'revision':secrets.token_urlsafe(32)})
                self.tools, self.tools_revision = [], ''
        return self.status()

    def client_fields(self, data):
        return {key:data[key] for key in ('client_id','client_secret') if data.get(key)}

    def register_client(self, data):
        if not data.get('client_id') or not data.get('client_secret'):
            raise AsanaError('Create an Asana MCP app and save its client ID and secret in the local setup form first.')
        return self.client_fields(data)

    def start(self, request):
        with self.lock:
            result = super().start(request)
            # The MCP app uses default permissions; Asana's guide recommends
            # omitting scope to avoid its invalid-scope error.
            target = urlsplit(result.authorization_url)
            query = [(key,value) for key,value in parse_qsl(target.query,keep_blank_values=True) if key != 'scope']
            address = urlunsplit((target.scheme,target.netloc,target.path,urlencode(query),''))
            self.flows[result.flow_id]['authorization_url'] = address
            return result.model_copy(update={'authorization_url':address})

    def token_request(self, client, parameters):
        if not client.get('client_secret'):
            raise AsanaError('Asana app setup is incomplete. Save its credentials in the local form first.')
        return self._json(self.provider.token,data={**parameters,
            'client_id':client['client_id'],'client_secret':client['client_secret']})

    def _tokens(self, value):
        token, refresh, expires = value.get('access_token'), value.get('refresh_token'), value.get('expires_in')
        try:
            valid_expiry = type(expires) in (int,float) and expires > 0 and math.isfinite(expires) and math.isfinite(self.clock()+expires)
        except (OverflowError,ValueError):
            valid_expiry = False
        if (not isinstance(token,str) or not token or len(token)>16000
                or str(value.get('token_type','')).strip().lower() != 'bearer' or not valid_expiry
                or (refresh is not None and (not isinstance(refresh,str) or not refresh or len(refresh)>16000))):
            raise AsanaError('Asana returned an invalid OAuth authorization response. No sign-in was marked complete.')
        scope = value.get('scope',value.get('scopes',[]))
        if isinstance(scope,str):
            scope = scope.split()
        if not isinstance(scope,list) or len(scope)>250 or any(not isinstance(item,str) or not 0<len(item)<=200 for item in scope):
            raise AsanaError('Asana returned invalid OAuth permission metadata.')
        result = {'access_token':token,'expires_at':self.clock()+expires}
        if 'scope' in value or 'scopes' in value:
            result['granted_scopes'] = scope
        if refresh is not None:
            result['refresh_token'] = refresh
        return result

    def status(self):
        status = super().status()
        try:
            registered = bool(self.load().get('client_id') and self.load().get('client_secret'))
        except AsanaError:
            registered = False
        message = status.message
        if not registered and status.status != 'keyring_unavailable':
            message = 'Create an Asana MCP app and save its client ID and secret to enable sign-in.'
        return status.model_copy(update={'oauth_available':registered,'app_registered':registered,'message':message})

    def identity(self, data):
        # Authenticated catalog discovery verifies access without reading tasks.
        return {'account_id':data.get('account_id') or 'asana-grant:'+data['revision'],
            'account_name':'Authorized Asana account','granted_scopes':data.get('granted_scopes',[])}

    def public_identity(self, data):
        return {'auth_type':'oauth' if data.get('access_token') else 'none','identity_verified':False}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if re.match(r'^(?:asana_)?(?:manage|write|create|update|delete|remove|add|send|publish|submit|start|stop|set)_',tool['name'],re.I):
                tool['read_only'] = False
        return tools

    def disconnect(self):
        with self.lock:
            self._staged.clear()
        return super().disconnect()


@lru_cache(maxsize=1)
def asana_service():
    return AsanaService()


def asana_plugin_status():
    service = asana_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except AsanaError:
        tools = []
    return {'id':'asana','configured':status.configured,'status':status.status,'notes':status.message,
        'tools':['asana_mcp_catalog','asana_mcp_describe','asana_mcp_read','asana_mcp_execute',
            *[tool_name(tool['name']) for tool in tools]],
        'metadata':{'connection':status.model_dump(),'provider':'Asana','website':'https://www.asana.com',
            'integration':'Official Asana V2 MCP server','documentation_url':DOCS,
            'credential_storage':'Operating system credential store',
            'coverage':'Complete live catalog from the standard V2 MCP server, with deferred schemas. User permissions and app workspace distribution determine access; the separate Command MCP server is not selected.'}}
