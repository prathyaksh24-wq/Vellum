"""Local UI-only account transport; OAuth callbacks use one-use provider state."""
from functools import lru_cache
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute

from agent.accounts import AccountError, AccountService
from agent.contracts.accounts import AccountSelection, AccountStatus, EmailCredentials, EmailSignUp, EmailSignUpResult, FlowRequest, SignInFlow, SignInRequest


def local_client(request: Request):
    if (request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not request.client or request.client.host not in {"127.0.0.1", "::1"}):
        raise HTTPException(403, "Accounts are available only on this device.")


def trusted_view(request: Request, response: Response):
    local_client(request)
    origins = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in (4242, 5173, 1420, 8000)}
    origins.update({"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"})
    if request.headers.get("origin") not in origins or request.headers.get("x-vellum-accounts") != "1":
        raise HTTPException(403, "Open Accounts from the local Vellum app.")
    response.headers["Cache-Control"] = "no-store"


class AccountRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def redacted_validation(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Default validation details can echo an entire body, including a password.
                raise HTTPException(422, "The account request is invalid. Check the entered fields.") from None
        return redacted_validation


router = APIRouter(prefix="/accounts", tags=["accounts"], route_class=AccountRoute)


@lru_cache(maxsize=1)
def service() -> AccountService:
    return AccountService()


def call(method, *args):
    try:
        return method(*args)
    except AccountError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/status", response_model=AccountStatus, dependencies=[Depends(trusted_view)])
def status():
    return service().status()


@router.post("/start", response_model=SignInFlow, dependencies=[Depends(trusted_view)])
def start(body: SignInRequest):
    return call(service().start, body.provider, body.return_url, body.open_browser)


@router.post("/poll", response_model=SignInFlow, dependencies=[Depends(trusted_view)])
def poll(body: FlowRequest):
    return call(service().poll, body.flow_id)


@router.post("/cancel", response_model=SignInFlow, dependencies=[Depends(trusted_view)])
def cancel(body: FlowRequest):
    return call(service().cancel, body.flow_id)


@router.post("/select", response_model=AccountStatus, dependencies=[Depends(trusted_view)])
def select(body: AccountSelection):
    return call(service().select, body.account_id)


@router.post("/sign-out", response_model=AccountStatus, dependencies=[Depends(trusted_view)])
def sign_out(body: AccountSelection):
    return call(service().sign_out, body.account_id)


@router.post("/logout", response_model=AccountStatus, dependencies=[Depends(trusted_view)])
def logout():
    return call(service().logout)


@router.post("/continue-local", response_model=AccountStatus, dependencies=[Depends(trusted_view)])
def continue_local():
    return call(service().continue_local)


@router.post("/email/sign-in", response_model=AccountStatus, dependencies=[Depends(trusted_view)])
def email_sign_in(body: EmailCredentials):
    return call(service().email_sign_in, body.email, body.password.get_secret_value())


@router.post("/email/sign-up", response_model=EmailSignUpResult, dependencies=[Depends(trusted_view)])
def email_sign_up(body: EmailSignUp):
    return call(service().email_sign_up, body.email, body.password.get_secret_value(), body.return_url)


def callback_response(provider: str, state: str, code: str, error: str):
    ok, return_url = service().complete_callback(provider, state, code, error)
    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}
    if ok:
        return RedirectResponse(return_url, status_code=303, headers=headers)
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>Return to Vellum</title><body><h1>Sign-in did not complete</h1>'
        f'<p><a href="{escape(return_url, quote=True)}">Return to Vellum</a> to try again.</p></body></html>',
        status_code=400, headers=headers,
    )


@router.get("/callback/google", dependencies=[Depends(local_client)])
def google_callback(state: str = "", code: str = "", error: str = ""):
    return callback_response("google", state, code, error)


@router.get("/callback/github", dependencies=[Depends(local_client)])
def github_callback(state: str = "", code: str = "", error: str = ""):
    return callback_response("github", state, code, error)


@router.get("/callback/email", dependencies=[Depends(local_client)])
def email_callback(state: str = "", code: str = "", error: str = ""):
    return callback_response("email", state, code, error)
