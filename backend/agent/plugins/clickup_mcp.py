"""ClickUp tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.clickup_connection import ClickUpMcpOperation
from agent.plugins.clickup_connection import clickup_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class ClickUpMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or clickup_service(), runtime)


def agent_tools():
    return deferred_tools(clickup_service, ClickUpMcpOperation, tool_name)
