"""Tavily tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.tavily_connection import TavilyMcpOperation
from agent.plugins.tavily_connection import tavily_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class TavilyMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or tavily_service(), runtime)


def agent_tools():
    return deferred_tools(tavily_service, TavilyMcpOperation, tool_name)
