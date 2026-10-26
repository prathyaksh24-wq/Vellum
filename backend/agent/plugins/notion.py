"""Official Notion MCP identity and public-client OAuth."""
import asyncio
from functools import lru_cache
import hashlib
import json
import re

from agent.contracts.notion import NotionFlowStart, NotionFlowStatus, NotionMcpTool, NotionStatus
from agent.mcp.plugin_runtime import SdkPluginMcpTransport
from agent.plugins.mcp_oauth import OfficialMcpOAuthService, OfficialOAuthProvider
from agent.tools.plugin_mcp import _run_async

SERVER = "https://mcp.notion.com/mcp"
AUTHORIZE = "https://mcp.notion.com/authorize"
TOKEN = "https://mcp.notion.com/token"
REGISTER = "https://mcp.notion.com/register"
RESOURCE = "https://mcp.notion.com"
CALLBACK = "http://127.0.0.1:8000/api/plugins/notion/oauth/callback"
SCOPES = "default"


class NotionError(ValueError):
    pass


def tool_name(name):
    value = "notion_tool_" + name.replace("-", "_")
    return value if len(value) <= 64 else value[:45] + "_" + hashlib.sha256(value.encode()).hexdigest()[:12]


class NotionService(OfficialMcpOAuthService):
    provider = OfficialOAuthProvider("notion", "Notion", SERVER, AUTHORIZE, TOKEN, REGISTER, RESOURCE, CALLBACK, SCOPES)
    error_type = NotionError
    status_model, tool_model = NotionStatus, NotionMcpTool
    flow_status_model, flow_start_model = NotionFlowStatus, NotionFlowStart
    identity_keys = ("account_id", "workspace_id")

    def identity(self, data):
        try:
            raw = _run_async(asyncio.wait_for((self.transport or SdkPluginMcpTransport()).call_tool(
                self.connector(data), "notion-get-self", {}), timeout=40))
            if not isinstance(raw, str) or len(raw) > 256000:
                raise ValueError()
            value = json.loads(raw)
            # Some Notion versions return their JSON as text content blocks.
            if isinstance(value, dict) and isinstance(value.get("content"), list):
                content = value["content"]
                value = json.loads(next(item["text"] for item in content if item.get("type") == "text"))
            workspace, user = value["workspace"], value["user"]
            for identifier in (workspace.get("id"), user.get("id")):
                if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", identifier):
                    raise ValueError()
            if user.get("type") not in {"person", "bot"}:
                raise ValueError()
            return {"account_id": user["id"], "account_name": str(user.get("name") or user.get("email") or user["id"]),
                "workspace_id": workspace["id"], "workspace_name": str(workspace.get("name") or workspace["id"]),
                "granted_scopes": ["default"]}
        except Exception:
            raise NotionError("Notion did not verify the current user and workspace through its official MCP server. Reconnect in Plugins.") from None

    def public_identity(self, data):
        return {"workspace_name": data.get("workspace_name")}


@lru_cache(maxsize=1)
def notion_service():
    return NotionService()


def notion_plugin_status():
    service = notion_service()
    status = service.status()
    try:
        tools = service.cached_tools()
    except NotionError:
        tools = []
    return {"id": "notion", "configured": status.configured, "status": status.status, "notes": status.message,
        "tools": ["notion_mcp_catalog", "notion_mcp_describe", "notion_mcp_read", "notion_mcp_execute", *[tool_name(tool["name"]) for tool in tools]],
        "metadata": {"connection": status.model_dump(), "provider": "Notion", "website": "https://www.notion.com",
            "integration": "Official Notion MCP server", "documentation_url": "https://developers.notion.com/guides/mcp/get-started-with-mcp",
            "credential_storage": "Operating system credential store",
            "coverage": "Complete live MCP catalog; workspace permissions, plan limits and the connection's available tools determine access."}}
