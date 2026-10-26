"""Airtable-specific identity and contracts over the shared MCP OAuth lifecycle."""
from functools import lru_cache
import hashlib
import re

from agent.contracts.airtable import AirtableFlowStart, AirtableFlowStatus, AirtableMcpTool, AirtableStatus
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider

SERVER = "https://mcp.airtable.com/mcp"
AUTHORIZE = "https://airtable.com/oauth2/v1/authorize"
TOKEN = "https://airtable.com/oauth2/v1/token"
REGISTER = "https://airtable.com/oauth2/v1/register"
RESOURCE = "https://mcp.airtable.com"
CALLBACK = "http://127.0.0.1:8000/api/plugins/airtable/oauth/callback"
SCOPES = "data.records:read data.records:write schema.bases:read schema.bases:write data.recordComments:read data.recordComments:write workspacesAndBases:read"



class AirtableError(ValueError):
    pass


def tool_name(name):
    value = "airtable_tool_" + name
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]


class AirtableService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider("airtable", "Airtable", SERVER, AUTHORIZE, TOKEN, REGISTER, RESOURCE, CALLBACK, SCOPES)
    error_type = AirtableError
    status_model, tool_model = AirtableStatus, AirtableMcpTool
    flow_status_model, flow_start_model = AirtableFlowStatus, AirtableFlowStart

    def identity(self, data):
        value = self._json('https://api.airtable.com/v0/meta/whoami', method='GET', headers={'Authorization': 'Bearer ' + data['access_token']})
        if not isinstance(value.get('id'), str) or not re.fullmatch('usr[A-Za-z0-9]{8,40}', value['id']):
            raise AirtableError('Airtable did not verify this account. Reconnect in Plugins.')
        scopes = value.get('scopes', [])
        if not isinstance(scopes, list) or any((not isinstance(item, str) for item in scopes)):
            raise AirtableError('Airtable returned invalid permission information.')
        return {'account_id': value['id'], 'account_name': str(value.get('email') or value['id']), 'granted_scopes': sorted(set(scopes))}

@lru_cache(maxsize=1)
def airtable_service():
    return AirtableService()


def airtable_plugin_status():
    service = airtable_service()
    status = service.status()
    try:
        published = service.cached_tools()
    except AirtableError:
        published = []
    return {"id": "airtable", "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["airtable_mcp_catalog", "airtable_mcp_describe", "airtable_mcp_read", "airtable_mcp_execute", *[tool_name(tool["name"]) for tool in published]],
        "metadata": {"connection": status.model_dump(), "provider": "Airtable", "website": "https://airtable.com",
            "integration": "Official Airtable MCP server", "documentation_url": "https://airtable.com/developers/agents/mcp/getting-started",
            "credential_storage": "Operating system credential store", "coverage": "Complete live MCP catalog; selected bases, Airtable permissions and plan limits determine access. MCP coverage differs from the REST API."}}
