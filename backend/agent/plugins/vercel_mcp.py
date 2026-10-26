"""Vercel tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.vercel_connection import VercelMcpOperation
from agent.plugins.vercel_connection import vercel_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class VercelMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or vercel_service(), runtime)


def agent_tools():
    return deferred_tools(vercel_service, VercelMcpOperation, tool_name)
