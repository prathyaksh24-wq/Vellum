"""Obsidian vault access backed by the Local REST API MCP endpoint."""

from langchain_core.tools import tool

from agent.mcp.obsidian_tools import run_tool as obsidian_run


@tool
def obsidian_api(
    action: str = "list",
    path: str = "",
    query: str = "",
    content: str = "",
    operation: str = "",
    target: str = "",
    target_type: str = "",
    period: str = "",
    command_id: str = "",
) -> str:
    """Read, search, and write Obsidian through the Local REST API MCP endpoint.

    Common actions: list, read, search, tags, write, append, patch, delete.
    Writes require OBSIDIAN_MCP_ALLOW_WRITES=true. Deletes require
    OBSIDIAN_MCP_ALLOW_DESTRUCTIVE=true. Command execution requires
    OBSIDIAN_MCP_ALLOW_COMMANDS=true.
    """

    return obsidian_run(
        {
            "action": action,
            "path": path,
            "query": query,
            "content": content,
            "operation": operation,
            "target": target,
            "target_type": target_type,
            "period": period,
            "command_id": command_id,
        }
    )
