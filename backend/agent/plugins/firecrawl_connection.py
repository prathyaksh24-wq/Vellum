"""Official Firecrawl MCP connection; OAuth is per user, configured keys are local."""
import asyncio
from functools import lru_cache
import hashlib
import json

from agent.config import get_settings
from agent.contracts.firecrawl_connection import FirecrawlFlowStart, FirecrawlFlowStatus, FirecrawlMcpTool, FirecrawlStatus
from agent.mcp.plugin_runtime import SdkPluginMcpTransport
from agent.plugins.mcp_oauth import OfficialOAuthProvider
from agent.plugins.web_mcp import WebMcpConnection
from agent.tools.plugin_mcp import _run_async

SERVER = 'https://mcp.firecrawl.dev/v2/mcp-oauth'
CALLBACK = "http://127.0.0.1:8000/api/plugins/firecrawl/oauth/callback"
DOCS = 'https://docs.firecrawl.dev/mcp-server'


class FirecrawlError(ValueError):
    pass


def tool_name(name):
    value = "firecrawl_tool_" + name.replace("-", "_")
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]


class FirecrawlService(WebMcpConnection):
    provider = OfficialOAuthProvider('firecrawl', 'Firecrawl', SERVER, 'https://www.firecrawl.dev/api/oauth/authorize',
        'https://www.firecrawl.dev/api/oauth/token', 'https://www.firecrawl.dev/api/oauth/register', 'https://mcp.firecrawl.dev/v2/mcp-oauth', CALLBACK, 'firecrawl:global offline_access')
    error_type = FirecrawlError
    status_model, tool_model = FirecrawlStatus, FirecrawlMcpTool
    flow_status_model, flow_start_model = FirecrawlFlowStatus, FirecrawlFlowStart

    def configured_credential(self):
        return get_settings().firecrawl_api_key

    def identity(self, data):
        try:
            raw = _run_async(asyncio.wait_for((self.transport or SdkPluginMcpTransport()).call_tool(
                self.connector(data), "firecrawl_credit_usage", {}), timeout=40))
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("error") or value.get("success") is False:
                raise ValueError()
        except Exception:
            raise FirecrawlError("Firecrawl did not verify team access. Check the selected team and authorization.") from None
        # The public MCP surface verifies team access but does not provide a user profile.
        # Bind reviews to this verified grant, without inventing a provider user identity.
        return {"account_id": data.get("account_id") or "firecrawl-grant:" + data["revision"],
            "account_name": "Authorized Firecrawl team", "workspace_name": "Firecrawl team",
            "identity_verified": False, "granted_scopes": self.provider.scopes.split() if data.get("auth_type") == "oauth" else []}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if tool["name"] == "firecrawl_interact":
                tool["read_only"] = False
        return tools


@lru_cache(maxsize=1)
def firecrawl_service():
    return FirecrawlService()


def firecrawl_plugin_status():
    service = firecrawl_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except FirecrawlError:
        tools = []
    return {"id": 'firecrawl', "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["firecrawl_mcp_catalog", "firecrawl_mcp_describe", "firecrawl_mcp_read", "firecrawl_mcp_execute", *[tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": 'Firecrawl', "website": 'https://www.firecrawl.dev',
            "integration": "Official Firecrawl MCP server", "documentation_url": DOCS,
            "credential_storage": "Operating system credential store",
            "coverage": "Complete selected official MCP catalog, with deferred schemas. Provider account, plan and usage limits apply."}}
