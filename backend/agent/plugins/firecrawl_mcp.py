"""Firecrawl tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.firecrawl_connection import FirecrawlMcpOperation
from agent.plugins.firecrawl_connection import firecrawl_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class FirecrawlMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or firecrawl_service(), runtime)


def agent_tools():
    return deferred_tools(firecrawl_service, FirecrawlMcpOperation, tool_name)
