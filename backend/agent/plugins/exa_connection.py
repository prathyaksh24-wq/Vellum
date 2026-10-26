"""Exa's official hosted MCP connection and local credential owner."""
from functools import lru_cache
import hashlib

from agent.config import get_settings
from agent.contracts.exa_connection import ExaFlowStart, ExaFlowStatus, ExaMcpTool, ExaStatus
from agent.plugins.mcp_oauth import OfficialOAuthProvider
from agent.plugins.web_mcp import WebMcpConnection

SERVER = 'https://mcp.exa.ai/mcp?login&tools=web_search_exa,web_fetch_exa,agent_run,web_search_advanced_exa'
CALLBACK = "http://127.0.0.1:8000/api/plugins/exa/oauth/callback"
DOCS = 'https://github.com/exa-labs/exa-mcp-server'

class ExaError(ValueError):
    pass

def tool_name(name):
    value = "exa_tool_" + name.replace("-", "_")
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]

class ExaService(WebMcpConnection):
    provider = OfficialOAuthProvider('exa', 'Exa', SERVER, 'https://auth.exa.ai/oauth/authorize',
        'https://auth.exa.ai/api/oauth/token', 'https://auth.exa.ai/api/oauth/register', 'https://mcp.exa.ai/mcp', CALLBACK, 'mcp:tools')
    error_type = ExaError
    status_model, tool_model = ExaStatus, ExaMcpTool
    flow_status_model, flow_start_model = ExaFlowStatus, ExaFlowStart

    def configured_credential(self):
        return ''

    def identity(self, data):
        # MCP authenticates this grant but publishes no user profile. Do not invent identity.
        return {"account_id": data.get("account_id") or "exa-grant:" + data["revision"],
            "account_name": "Authorized Exa account", "workspace_name": "Exa account",
            "identity_verified": False, "granted_scopes": self.provider.scopes.split() if data.get("auth_type") == "oauth" else []}

    def _tokens(self, value):
        data = super()._tokens(value)
        # The official server verifies JWT signature, issuer, audience and team claims.
        # Reject a plain API key here: public catalog listing alone does not validate one.
        if len(data['access_token'].split('.')) != 3:
            raise ExaError('Exa did not return an OAuth access token. Start sign-in again.')
        return data

    def use_configured(self):
        raise ExaError('Use Sign in with Exa to verify this MCP connection.')

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if tool['name'] == 'agent_run':
                tool['read_only'] = False
        return tools

@lru_cache(maxsize=1)
def exa_service():
    return ExaService()

def exa_plugin_status():
    service = exa_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except ExaError:
        tools = []
    return {"id": 'exa', "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["exa_mcp_catalog", "exa_mcp_describe", "exa_mcp_read", "exa_mcp_execute", *[tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": 'Exa', "website": 'https://exa.ai',
            "integration": "Official Exa MCP server", "documentation_url": DOCS,
            "credential_storage": "Operating system credential store",
            "coverage": "Complete selected official MCP tool catalog; schemas load on demand. Provider account, plan and usage limits apply."}}
