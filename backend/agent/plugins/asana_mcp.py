"""Asana tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.asana_connection import AsanaMcpOperation
from agent.plugins.asana_connection import asana_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class AsanaMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or asana_service(), runtime)


def agent_tools():
    return deferred_tools(asana_service, AsanaMcpOperation, tool_name)
