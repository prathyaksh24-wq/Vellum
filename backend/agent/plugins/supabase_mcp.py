"""Supabase tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.supabase_connection import SupabaseMcpOperation
from agent.plugins.supabase_connection import supabase_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class SupabaseMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or supabase_service(), runtime)


def agent_tools():
    return deferred_tools(supabase_service, SupabaseMcpOperation, tool_name)
