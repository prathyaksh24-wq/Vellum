"""Local Linear UI transport; secrets never cross the action boundary."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.account_api import local_client
from agent.contracts.linear import LinearStatus, LinearOAuthStatus, LinearMcpOperation, LinearMcpCatalog, LinearMcpResult
from agent.plugins.linear import LinearError, linear_service


def trusted_linear_view(request: Request, response: Response):
    local_client(request)
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (4242, 5173, 1420, 8000)}
    if request.headers.get("origin") not in origins or request.headers.get("x-vellum-linear") != "1":
        raise HTTPException(403, "Open Linear from the local Vellum app.")
    response.headers["Cache-Control"] = "no-store"


class LinearRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def redacted(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, "Check the Linear credential or request fields.") from None
        return redacted


router = APIRouter(prefix="/plugins/linear", tags=["linear"], route_class=LinearRoute, dependencies=[Depends(trusted_linear_view)])


@router.get("/status", response_model=LinearStatus)
def status():
    return linear_service().status()


@router.get("/mcp/tools",response_model=LinearMcpCatalog)
def mcp_tools():
    from agent.plugins.linear_mcp import LinearMcpAdapter
    try:return LinearMcpCatalog(tools=LinearMcpAdapter().catalog())
    except LinearError as exc:raise HTTPException(400,str(exc)) from None


@router.post("/mcp/read",response_model=LinearMcpResult)
def mcp_read(operation:LinearMcpOperation):
    from agent.plugins.linear_mcp import LinearMcpAdapter
    try:return LinearMcpResult(tool_name=operation.tool_name,result=LinearMcpAdapter().read(operation))
    except LinearError as exc:raise HTTPException(400,str(exc)) from None


@router.get("/oauth/status",response_model=LinearOAuthStatus)
def oauth_status(flow_id:str):
    from agent.plugins.linear_oauth import oauth_status as poll
    try:return poll(flow_id)
    except LinearError as exc:raise HTTPException(400,str(exc)) from None


# Provider redirects do not carry Vellum's custom Origin/header guard. Keep only
# this loopback, state-validated callback outside the guarded management router.
oauth_router=APIRouter(prefix="/plugins/linear",dependencies=[Depends(local_client)])


@oauth_router.get("/oauth/callback",response_class=HTMLResponse)
def oauth_callback(code:str="",state:str="",error:str=""):
    from agent.plugins.linear_oauth import receive_callback
    try:flow=receive_callback(code,state,error)
    except LinearError:
        return HTMLResponse("<h1>Linear sign-in expired</h1><p>Return to Vellum and connect again.</p>",status_code=400,headers={"Cache-Control":"no-store"})
    return RedirectResponse("/api/plugins/linear/oauth/return?flow_id="+flow.id,status_code=303,
        headers={"Cache-Control":"no-store","Referrer-Policy":"no-referrer"})


@oauth_router.get("/oauth/return")
def oauth_return(flow_id:str):
    from html import escape
    from agent.plugins.linear_oauth import return_flow
    headers={"Cache-Control":"no-store","Referrer-Policy":"no-referrer"}
    try:flow=return_flow(flow_id)
    except LinearError:
        return HTMLResponse("<h1>Linear sign-in expired</h1><p>Open Vellum and connect again.</p>",status_code=400,headers=headers)
    if flow.status!="pending":
        return RedirectResponse(flow.return_url,status_code=303,headers=headers)
    # The clean return page refreshes while the SDK exchanges the code, verifies
    # the MCP identity and persists authorization. Never claim success early.
    headers["Refresh"]="1"
    return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width">'
        '<title>Connecting Linear to Vellum</title><body style="background:#171614;color:#eee7df;'
        'font:16px system-ui;max-width:32rem;margin:15vh auto;padding:2rem">'
        '<h1>Connecting Linear…</h1><p>Verifying access and saving your authorization on this device.</p>'
        f'<p><a style="color:#bdb9ff" href="{escape(flow.return_url,quote=True)}">Return to Vellum</a></p></body>',headers=headers)
