"""HubSpot tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.hubspot_connection import HubSpotMcpOperation
from agent.plugins.hubspot_connection import hubspot_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class HubSpotMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or hubspot_service(), runtime)


def agent_tools():
    return deferred_tools(hubspot_service, HubSpotMcpOperation, tool_name)
