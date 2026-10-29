"""SerpApi tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.serpapi_connection import SerpApiMcpOperation
from agent.plugins.serpapi_connection import serpapi_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class SerpApiMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or serpapi_service(), runtime)


def agent_tools():
    return deferred_tools(serpapi_service, SerpApiMcpOperation, tool_name)
