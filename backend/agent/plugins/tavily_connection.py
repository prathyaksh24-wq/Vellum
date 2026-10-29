"""Tavily's official hosted MCP connection and local credential owner."""
from functools import lru_cache
import hashlib

from agent.config import get_settings
from agent.contracts.tavily_connection import TavilyFlowStart, TavilyFlowStatus, TavilyMcpTool, TavilyStatus
from agent.plugins.mcp_oauth import OfficialOAuthProvider
from agent.plugins.web_mcp import WebMcpConnection

SERVER = 'https://mcp.tavily.com/mcp/'
CALLBACK = "http://127.0.0.1:8000/api/plugins/tavily/oauth/callback"
DOCS = 'https://docs.tavily.com/documentation/mcp'

class TavilyError(ValueError):
    pass

def tool_name(name):
    value = "tavily_tool_" + name.replace("-", "_")
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]

class TavilyService(WebMcpConnection):
    provider = OfficialOAuthProvider('tavily', 'Tavily', SERVER, 'https://mcp.tavily.com/authorize',
        'https://mcp.tavily.com/token', 'https://mcp.tavily.com/register', 'https://mcp.tavily.com/mcp', CALLBACK, 'openid offline_access')
    error_type = TavilyError
    status_model, tool_model = TavilyStatus, TavilyMcpTool
    flow_status_model, flow_start_model = TavilyFlowStatus, TavilyFlowStart

    def configured_credential(self):
        return get_settings().tavily_api_key

    def identity(self, data):
        # MCP authenticates this grant but publishes no user profile. Do not invent identity.
        return {"account_id": data.get("account_id") or "tavily-grant:" + data["revision"],
            "account_name": "Authorized Tavily account", "workspace_name": "Tavily account",
            "identity_verified": False, "granted_scopes": self.provider.scopes.split() if data.get("auth_type") == "oauth" else []}

@lru_cache(maxsize=1)
def tavily_service():
    return TavilyService()

def tavily_plugin_status():
    service = tavily_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except TavilyError:
        tools = []
    return {"id": 'tavily', "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["tavily_mcp_catalog", "tavily_mcp_describe", "tavily_mcp_read", "tavily_mcp_execute", *[tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": 'Tavily', "website": 'https://www.tavily.com',
            "integration": "Official Tavily MCP server", "documentation_url": DOCS,
            "credential_storage": "Operating system credential store",
            "coverage": "Complete selected official MCP tool catalog; schemas load on demand. Provider account, plan and usage limits apply."}}
