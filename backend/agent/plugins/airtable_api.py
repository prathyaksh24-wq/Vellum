"""Loopback-only Airtable management and state-validated OAuth callbacks."""
from html import escape
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.account_api import AccountRoute, local_client, trusted_view
from agent.contracts.airtable import AirtableFlowStatus, AirtableMcpCatalog, AirtableMcpOperation, AirtableMcpResult, AirtableStatus
from agent.plugins.airtable import AirtableError, airtable_service

router = APIRouter(prefix="/plugins/airtable", tags=["airtable"], route_class=AccountRoute, dependencies=[Depends(trusted_view)])
oauth_router = APIRouter(prefix="/plugins/airtable", dependencies=[Depends(local_client)])


@router.get("/status", response_model=AirtableStatus)
def status():
    return airtable_service().status()


@router.get("/oauth/status", response_model=AirtableFlowStatus)
def oauth_status(flow_id: str):
    try:
        return airtable_service().flow_status(flow_id)
    except AirtableError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/mcp/tools", response_model=AirtableMcpCatalog)
def tools(refresh: bool = False):
    try:
        return AirtableMcpCatalog(tools=airtable_service().catalog(refresh=refresh))
    except AirtableError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/mcp/read", response_model=AirtableMcpResult)
def read(operation: AirtableMcpOperation):
    from agent.plugins.airtable_mcp import AirtableMcpAdapter
    try:
        return AirtableMcpResult(tool_name=operation.tool_name, result=AirtableMcpAdapter().read(operation))
    except (ValueError, RuntimeError):
        raise HTTPException(400, "Airtable did not complete this read. Verify the connection and published tool arguments.") from None


@oauth_router.get("/oauth/callback")
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    try:
        identifier = airtable_service().callback(state, code, error)
    except AirtableError:
        return HTMLResponse("<h1>Airtable sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return RedirectResponse("/api/plugins/airtable/oauth/return?flow_id=" + identifier, status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@oauth_router.get("/oauth/open")
def oauth_open(flow_id: str):
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    try:
        service = airtable_service()
        with service.lock:
            flow = service.flow_status(flow_id)
            destination = service.flows[flow_id]["authorization_url"] if flow.status == "pending" else "/api/plugins/airtable/oauth/return?flow_id=" + flow_id
        return RedirectResponse(destination, status_code=303, headers=headers)
    except AirtableError:
        return HTMLResponse("<h1>Airtable sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400, headers=headers)


@oauth_router.get("/oauth/return")
def oauth_return(flow_id: str):
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"}
    try:
        service = airtable_service()
        with service.lock:
            flow, destination = service.flow_status(flow_id), service.return_url(flow_id)
            popup = service.flows[flow_id]["popup"]
    except AirtableError:
        return HTMLResponse("<h1>Airtable sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400, headers=headers)
    if flow.status != "pending":
        if not popup:
            return RedirectResponse(destination, status_code=303, headers=headers)
        nonce = secrets.token_urlsafe(24)
        target = urlsplit(destination)
        origin = target.scheme + "://" + target.netloc
        script = """(()=>{try{if(window.opener&&!window.opener.closed){
const data=document.body.dataset;
window.opener.postMessage({type:"vellum:airtable:oauth",flow_id:data.flowId},data.targetOrigin);
window.opener.focus();}}catch{}window.close();})();"""
        headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{nonce}'; frame-ancestors 'none'; base-uri 'none'"
        title = "Airtable connected" if flow.status == "connected" else "Airtable sign-in finished"
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{title}</title><body data-flow-id="{escape(flow_id, quote=True)}" data-target-origin="{escape(origin, quote=True)}">'
            f'<h1>{title}</h1><p>{escape(flow.message)}</p><p>Continue in your original Vellum window.</p>'
            f'<p><a href="{escape(destination, quote=True)}" target="_blank" rel="noopener noreferrer">Open Vellum</a></p>'
            f'<script nonce="{nonce}">{script}</script></body></html>', headers=headers)
    headers["Refresh"] = "1"
    return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width"><title>Connecting Airtable</title>'
        '<h1>Connecting Airtable to Vellum…</h1><p>Verifying your account and official MCP access.</p>'
        f'<p><a href="{escape(destination, quote=True)}" target="_blank" rel="noopener noreferrer">Return to Vellum</a></p>', headers=headers)
