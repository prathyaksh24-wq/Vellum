"""Guarded, write-only key staging and selected-provider catalog inspection."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from agent.account_api import AccountRoute, trusted_view
from agent.contracts.keyed_mcp import (Provider, KeyedMcpStatus, KeyedMcpCatalog,
    StagedMcpKey, McpKeyReference, StagedMcpKeyResult)
from agent.plugins.keyed_mcp import keyed_mcp_service, KeyedMcpError

router = APIRouter(prefix='/plugins/keyed', route_class=AccountRoute, dependencies=[Depends(trusted_view)])

@router.get('/{provider}/status', response_model=KeyedMcpStatus)
def status(provider: Provider):
    return keyed_mcp_service(provider).status()

@router.get('/{provider}/mcp/tools', response_model=KeyedMcpCatalog)
async def tools(provider: Provider, refresh: bool = False):
    try:
        values = await asyncio.to_thread(keyed_mcp_service(provider).catalog, refresh=refresh)
        return KeyedMcpCatalog(tools=values)
    except KeyedMcpError as exc:
        raise HTTPException(409, str(exc)) from None

@router.post('/{provider}/credentials/stage', response_model=StagedMcpKeyResult)
def stage(provider: Provider, body: StagedMcpKey):
    try:
        return StagedMcpKeyResult(credential_id=keyed_mcp_service(provider).stage(body.token.get_secret_value()))
    except KeyedMcpError as exc:
        raise HTTPException(400, str(exc)) from None

@router.post('/{provider}/credentials/discard')
def discard(provider: Provider, body: McpKeyReference):
    keyed_mcp_service(provider).discard(body.credential_id)
    return {'discarded': True}
