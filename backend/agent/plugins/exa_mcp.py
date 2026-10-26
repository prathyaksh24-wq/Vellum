"""Exa tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.exa_connection import ExaMcpOperation
from agent.plugins.exa_connection import exa_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class ExaMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or exa_service(), runtime)


def agent_tools():
    return deferred_tools(exa_service, ExaMcpOperation, tool_name)
