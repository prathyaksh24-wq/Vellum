"""HTTP adapter for local plugin MCP approval decisions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from agent.contracts.mcp_catalog import PublishedMcpCatalog

from agent.mcp.plugin_approvals import (
    PluginMcpApprovalError,
    get_plugin_mcp_approval_store,
)


router = APIRouter(prefix="/plugins/mcp", tags=["plugin-mcp"])


@router.get("/connectors/{plugin_id}/{connector_name}/tools", response_model=PublishedMcpCatalog)
async def published_connector_tools(plugin_id: str, connector_name: str) -> dict[str, Any]:
    """Inspect one enabled connector's catalog without executing its tools."""
    from agent.mcp.plugin_runtime import PluginMcpRuntime, PluginMcpRuntimeError
    from agent.plugins.registry import get_plugin_registry
    try:
        tools = await PluginMcpRuntime(get_plugin_registry()).list_tools(plugin_id, connector_name)
    except PluginMcpRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"plugin_id": plugin_id, "connector": connector_name, "tools": tools}


@router.get("/approvals")
async def list_plugin_mcp_approvals(
    status: str | None = Query(default="pending"),
) -> dict[str, Any]:
    return {"approvals": get_plugin_mcp_approval_store().list(status=status or None)}


@router.post("/approvals/{approval_id}/approve")
async def approve_plugin_mcp_call(approval_id: str) -> dict[str, Any]:
    try:
        approval = get_plugin_mcp_approval_store().approve(approval_id)
    except PluginMcpApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"approval": approval}


@router.post("/approvals/{approval_id}/reject")
async def reject_plugin_mcp_call(approval_id: str) -> dict[str, Any]:
    try:
        approval = get_plugin_mcp_approval_store().reject(approval_id)
    except PluginMcpApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"approval": approval}
