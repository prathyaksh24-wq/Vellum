"""Local-only Google chooser status and a state-validated loopback return."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.account_api import local_client
from agent.contracts.google_workspace import GoogleApiCatalog, GoogleApiDescription, GoogleApiOperation, GoogleApiQuery, GoogleApiResult, GoogleFlow, GoogleRead, GoogleResult, GoogleStatus
from agent.plugins.google_workspace import GoogleError, google_service


def trusted_google_view(request: Request, response: Response):
    local_client(request)
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (4242, 5173, 1420, 8000)}
    if request.headers.get("origin") not in origins or request.headers.get("x-vellum-google") != "1":
        raise HTTPException(403, "Open Google connections from Vellum.")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/plugins/google", tags=["google"], dependencies=[Depends(trusted_google_view)])


@router.get("/catalog", response_model=GoogleApiCatalog | GoogleApiDescription)
def api_catalog(query: GoogleApiQuery = Depends()):
    from agent.plugins.google_api_catalog import catalog, describe
    try:
        return describe(query.service, query.method_id) if query.method_id else catalog(query.service, query.query, query.offset, query.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api-read", response_model=GoogleApiResult)
def api_read(operation: GoogleApiOperation):
    from agent.plugins.google_api import GoogleApiAdapter
    try:
        return GoogleApiAdapter().read(operation)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/status", response_model=GoogleStatus)
def status():
    return google_service().status()


@router.get("/oauth/status", response_model=GoogleFlow)
def flow_status(flow_id: str):
    return google_service().flow_status(flow_id)


@router.post("/read", response_model=GoogleResult)
def read(request: GoogleRead):
    try:
        return google_service().read(**request.model_dump())
    except GoogleError as exc:
        raise HTTPException(400, str(exc)) from None


def receive_callback(code: str = "", state: str = "", error: str = ""):
    try:
        return_url, result = google_service().receive_callback(code=code, state=state, error=error)
    except (ValueError, RuntimeError):
        return HTMLResponse("<h1>Google sign-in expired</h1><p>Return to Vellum and connect again.</p>", status_code=400,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    separator = "&" if "?" in return_url else "?"
    return RedirectResponse(return_url + separator + "view=apps&google_oauth=" + result["flow_id"], status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
