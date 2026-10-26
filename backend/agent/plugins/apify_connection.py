"""Official Apify MCP connection; OAuth is per user, configured keys are local."""
from functools import lru_cache
import hashlib
import re

from agent.config import get_settings
from agent.contracts.apify_connection import ApifyFlowStart, ApifyFlowStatus, ApifyMcpTool, ApifyStatus
from agent.plugins.mcp_oauth import OfficialOAuthProvider
from agent.plugins.web_mcp import WebMcpConnection

SERVER = 'https://mcp.apify.com?tools=actors,docs,runs,storage,tasks,schedules,report-problem,apify/rag-web-browser,apify/web-fetch&telemetry-enabled=false'
CALLBACK = "http://127.0.0.1:8000/api/plugins/apify/oauth/callback"
DOCS = 'https://docs.apify.com/mcp'


class ApifyError(ValueError):
    pass


def tool_name(name):
    value = "apify_tool_" + name.replace("-", "_")
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]


class ApifyService(WebMcpConnection):
    provider = OfficialOAuthProvider('apify', 'Apify', SERVER, 'https://console.apify.com/authorize/oauth',
        'https://console-backend.apify.com/oauth/apps/token', 'https://console-backend.apify.com/oauth/apps', 'https://mcp.apify.com', CALLBACK, 'full_api_access')
    error_type = ApifyError
    status_model, tool_model = ApifyStatus, ApifyMcpTool
    flow_status_model, flow_start_model = ApifyFlowStatus, ApifyFlowStart

    def configured_credential(self):
        return get_settings().apify_api_token

    def identity(self, data):
        value = self._json("https://api.apify.com/v2/users/me", method="GET",
            headers={"Authorization": "Bearer " + data["access_token"]})
        user = value.get("data")
        if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", user["id"]):
            raise ApifyError("Apify did not verify this account. Reconnect with the intended account.")
        return {"account_id": user["id"], "account_name": str(user.get("username") or user["id"]),
            "workspace_name": "Apify account", "identity_verified": True,
            "granted_scopes": ["full_api_access"] if data.get("auth_type") == "oauth" else []}

    def _catalog(self, data):
        tools = super()._catalog(data)
        for tool in tools:
            if tool["name"] == "call-actor" or "--" in tool["name"]:
                tool["read_only"] = False
        return tools


@lru_cache(maxsize=1)
def apify_service():
    return ApifyService()


def apify_plugin_status():
    service = apify_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except ApifyError:
        tools = []
    return {"id": 'apify', "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["apify_mcp_catalog", "apify_mcp_describe", "apify_mcp_read", "apify_mcp_execute", *[tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": 'Apify', "website": 'https://apify.com',
            "integration": "Official Apify MCP server", "documentation_url": DOCS,
            "credential_storage": "Operating system credential store",
            "coverage": "Complete selected official MCP catalog, with deferred schemas. Provider account, plan and usage limits apply."}}
