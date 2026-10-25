"""Local GitHub management API. Provider callbacks reuse account OAuth routing."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.account_api import trusted_view, local_client, AccountRoute
from agent.contracts.github_connection import GitHubConnectionStatus, GitHubFlowStatus, GitHubMcpCatalog, GitHubMcpOperation, GitHubMcpResult
from agent.plugins.github_connection import GitHubConnectionError, github_service

router = APIRouter(prefix="/plugins/github", tags=["github"], route_class=AccountRoute, dependencies=[Depends(trusted_view)])
oauth_router = APIRouter(prefix="/plugins/github", dependencies=[Depends(local_client)])


@router.get("/status", response_model=GitHubConnectionStatus)
def status():
    return github_service().status()


@router.get("/oauth/status", response_model=GitHubFlowStatus)
def oauth_status(flow_id: str):
    try:
        return github_service().flow_status(flow_id)
    except GitHubConnectionError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/mcp/tools", response_model=GitHubMcpCatalog)
def tools(refresh: bool = False):
    try:
        return GitHubMcpCatalog(tools=github_service().catalog(refresh=refresh))
    except Exception:
        raise HTTPException(400, "GitHub's official catalog is unavailable. Verify the connection and organization access.") from None


@router.post("/mcp/read", response_model=GitHubMcpResult)
def read(operation: GitHubMcpOperation):
    from agent.plugins.github_mcp import GitHubMcpAdapter
    try:
        return GitHubMcpResult(tool_name=operation.tool_name, result=GitHubMcpAdapter().read(operation))
    except Exception:
        raise HTTPException(400, "GitHub could not complete this read. Verify the connection and tool arguments.") from None


@oauth_router.get("/oauth/return")
def oauth_return(flow_id: str):
    from html import escape
    import json
    import secrets
    from urllib.parse import urlsplit
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}
    try:
        service = github_service()
        with service.lock:
            flow = service.flow_status(flow_id)
            destination = service.return_url(flow_id)
            popup = service.flows[flow_id].get("popup", True)
    except GitHubConnectionError:
        return HTMLResponse("<h1>GitHub sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400, headers=headers)
    if flow.status != "pending":
        if not popup:
            return RedirectResponse(destination, status_code=303, headers=headers)
        nonce = secrets.token_urlsafe(24)
        origin = urlsplit(destination)
        target_origin = origin.scheme + "://" + origin.netloc
        message = {"type": "vellum:github:oauth", "flow_id": flow_id}
        script = "(()=>{try{if(window.opener&&!window.opener.closed){window.opener.postMessage(" + json.dumps(message) + "," + json.dumps(target_origin) + ");window.opener.focus();}}catch{}window.close();})();"
        headers["Content-Security-Policy"] = f"default-src 'none'; script-src 'nonce-{nonce}'; frame-ancestors 'none'; base-uri 'none'"
        title = "GitHub connected" if flow.status == "connected" else "GitHub sign-in finished"
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{title}</title><h1>{title}</h1><p>{escape(flow.message)}</p>'
            '<p>This sign-in window can close. Continue in your original Vellum window.</p>'
            f'<p><a href="{escape(destination, quote=True)}" target="_blank" rel="noopener noreferrer">Open Vellum</a></p>'
            f'<script nonce="{nonce}">{script}</script></html>', headers=headers)
    headers["Refresh"] = "1"
    link_target = ' target="_blank" rel="noopener noreferrer"' if popup else ''
    return HTMLResponse('<!doctype html><meta name="viewport" content="width=device-width"><title>Connecting GitHub</title>'
        '<h1>Connecting GitHub to Vellum…</h1><p>Verifying the account and official MCP access.</p>'
        f'<p><a href="{escape(destination, quote=True)}"{link_target}>Return to Vellum</a></p>', headers=headers)


@oauth_router.get("/oauth/open")
def oauth_open(flow_id: str):
    """Navigate a desktop-owned auth window into an existing, validated flow."""
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    try:
        service = github_service()
        with service.lock:
            flow = service.flow_status(flow_id)
            if flow.status != "pending":
                return RedirectResponse("/api/plugins/github/oauth/return?flow_id=" + flow_id, status_code=303, headers=headers)
            destination = service.flows[flow_id]["authorization_url"]
        return RedirectResponse(destination, status_code=303, headers=headers)
    except GitHubConnectionError:
        return HTMLResponse("<h1>GitHub sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400, headers=headers)
