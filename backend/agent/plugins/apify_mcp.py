"""Apify tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.apify_connection import ApifyMcpOperation
from agent.plugins.apify_connection import apify_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class ApifyMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or apify_service(), runtime)


def agent_tools():
    return deferred_tools(apify_service, ApifyMcpOperation, tool_name)
