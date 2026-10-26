"""Guarded SerpAPI key staging, connection status and published MCP reads."""
from fastapi import APIRouter, Depends, HTTPException

from agent.account_api import AccountRoute, trusted_view
from agent.contracts.serpapi_connection import SerpApiMcpCatalog, SerpApiMcpOperation, SerpApiMcpResult, SerpApiStatus
from agent.plugins.serpapi_connection import SerpApiError, serpapi_service

router = APIRouter(prefix="/plugins/serpapi", tags=["serpapi"], route_class=AccountRoute, dependencies=[Depends(trusted_view)])



@router.get("/status", response_model=SerpApiStatus)
def status():
    return serpapi_service().status()


@router.get("/mcp/tools", response_model=SerpApiMcpCatalog)
def tools(refresh: bool = False):
    try:
        return SerpApiMcpCatalog(tools=serpapi_service().catalog(refresh=refresh))
    except SerpApiError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/mcp/read", response_model=SerpApiMcpResult)
def read(operation: SerpApiMcpOperation):
    from agent.plugins.serpapi_mcp import SerpApiMcpAdapter
    try:
        return SerpApiMcpResult(tool_name=operation.tool_name, result=SerpApiMcpAdapter().read(operation))
    except (ValueError, RuntimeError):
        raise HTTPException(400, "SerpApi did not complete this read. Verify the connection and published tool arguments.") from None



from pydantic import BaseModel, ConfigDict, Field, SecretStr

class StagedKey(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: SecretStr = Field(min_length=8, max_length=4096, repr=False)

class KeyReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credential_id: str = Field(min_length=30, max_length=100)

class StagedKeyResult(KeyReference):
    expires_in: int = 600

@router.post('/credentials/stage', response_model=StagedKeyResult)
def stage(body: StagedKey):
    try:
        return StagedKeyResult(credential_id=serpapi_service().stage(body.token.get_secret_value()))
    except SerpApiError as exc:
        raise HTTPException(400, str(exc)) from None

@router.post('/credentials/discard')
def discard(body: KeyReference):
    serpapi_service().discard(body.credential_id)
    return {'discarded': True}
