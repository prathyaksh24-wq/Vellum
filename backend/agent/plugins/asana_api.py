"""Loopback-only Asana management and state-validated OAuth callbacks."""
from html import escape
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.account_api import AccountRoute, local_client, trusted_view
from agent.contracts.asana_connection import AsanaFlowStatus, AsanaMcpCatalog, AsanaMcpOperation, AsanaMcpResult, AsanaStatus
from agent.plugins.asana_connection import AsanaError, asana_service
from agent.contracts.asana_connection import AsanaAppCredentials, AsanaStagedCredential, AsanaStagedReference, AsanaDiscardResult

router = APIRouter(prefix="/plugins/asana", tags=["asana"], route_class=AccountRoute, dependencies=[Depends(trusted_view)])
oauth_router = APIRouter(prefix="/plugins/asana", dependencies=[Depends(local_client)])


@router.post('/credentials/stage', response_model=AsanaStagedCredential)
def stage(credentials: AsanaAppCredentials):
    try:
        return AsanaStagedCredential(credential_id=asana_service().stage(credentials))
    except AsanaError as exc:
        raise HTTPException(400,str(exc)) from None


@router.post('/credentials/discard', response_model=AsanaDiscardResult)
def discard(reference: AsanaStagedReference):
    asana_service().discard(reference.credential_id)
    return AsanaDiscardResult()


@router.get("/status", response_model=AsanaStatus)
def status():
    return asana_service().status()


@router.get("/oauth/status", response_model=AsanaFlowStatus)
def oauth_status(flow_id: str):
    try:
        return asana_service().flow_status(flow_id)
    except AsanaError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/mcp/tools", response_model=AsanaMcpCatalog)
def tools(refresh: bool = False):
    try:
        return AsanaMcpCatalog(tools=asana_service().catalog(refresh=refresh))
    except AsanaError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/mcp/read", response_model=AsanaMcpResult)
def read(operation: AsanaMcpOperation):
    from agent.plugins.asana_mcp import AsanaMcpAdapter
    try:
        return AsanaMcpResult(tool_name=operation.tool_name, result=AsanaMcpAdapter().read(operation))
    except (ValueError, RuntimeError):
        raise HTTPException(400, "Asana did not complete this read. Verify the connection and published tool arguments.") from None


@oauth_router.get("/oauth/callback")
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    try:
        identifier = asana_service().callback(state, code, error)
    except AsanaError:
        return HTMLResponse("<h1>Asana sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return RedirectResponse("/api/plugins/asana/oauth/return?flow_id=" + identifier, status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@oauth_router.get("/oauth/open")
def oauth_open(flow_id: str):
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    try:
        service = asana_service()
        with service.lock:
            flow = service.flow_status(flow_id)
            destination = service.flows[flow_id]["authorization_url"] if flow.status == "pending" else "/api/plugins/asana/oauth/return?flow_id=" + flow_id
        return RedirectResponse(destination, status_code=303, headers=headers)
    except AsanaError:
        return HTMLResponse("<h1>Asana sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400, headers=headers)


@oauth_router.get("/oauth/return")
def oauth_return(flow_id: str):
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"}
    try:
        service = asana_service()
        with service.lock:
            flow, destination = service.flow_status(flow_id), service.return_url(flow_id)
            popup = service.flows[flow_id]["popup"]
    except AsanaError:
        return HTMLResponse("<h1>Asana sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400, headers=headers)
    if flow.status != "pending":
        if not popup:
            return RedirectResponse(destination, status_code=303, headers=headers)
        nonce = secrets.token_urlsafe(24)
        target = urlsplit(destination)
        origin = target.scheme + "://" + target.netloc
        script = """(()=>{try{if(window.opener&&!window.opener.closed){
const data=document.body.dataset;
window.opener.postMessage({type:"vellum:asana:oauth",flow_id:data.flowId},data.targetOrigin);
window.opener.focus();}}catch{}window.close();})();"""
        headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{nonce}'; frame-ancestors 'none'; base-uri 'none'"
        title = "Asana connected" if flow.status == "connected" else "Asana sign-in finished"
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{title}</title><body data-flow-id="{escape(flow_id, quote=True)}" data-target-origin="{escape(origin, quote=True)}">'
            f'<h1>{title}</h1><p>{escape(flow.message)}</p><p>Continue in your original Vellum window.</p>'
            f'<p><a href="{escape(destination, quote=True)}" target="_blank" rel="noopener noreferrer">Open Vellum</a></p>'
            f'<script nonce="{nonce}">{script}</script></body></html>', headers=headers)
    headers["Refresh"] = "1"
    return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width"><title>Connecting Asana</title>'
        '<h1>Connecting Asana to Vellum…</h1><p>Verifying your account and official MCP access.</p>'
        f'<p><a href="{escape(destination, quote=True)}" target="_blank" rel="noopener noreferrer">Return to Vellum</a></p>', headers=headers)
