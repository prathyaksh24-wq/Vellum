#!/usr/bin/env python3
"""Browser OAuth setup for xAI X Search.

Runs a local OAuth 2.0 PKCE loopback flow and writes `data/xai-oauth.json`,
which is consumed by `xai_x_search_client.py`.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


XAI_BASE_URL = "https://api.x.ai/v1"
XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_OAUTH_REDIRECT_HOST = "127.0.0.1"
XAI_OAUTH_REDIRECT_PORT = 56121
XAI_OAUTH_REDIRECT_PATH = "/callback"
DEFAULT_TIMEOUT_SECS = 180


class XAISetupError(RuntimeError):
    """OAuth setup failed before tokens could be saved."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def discover_oauth(timeout_secs: int) -> dict[str, str]:
    response = httpx.get(XAI_OAUTH_DISCOVERY_URL, timeout=timeout_secs)
    if response.status_code >= 400:
        raise XAISetupError(f"xAI OAuth discovery returned HTTP {response.status_code}.")
    payload = response.json()
    authorization_endpoint = str(payload.get("authorization_endpoint") or "").strip()
    token_endpoint = str(payload.get("token_endpoint") or "").strip()
    if not authorization_endpoint or not token_endpoint:
        raise XAISetupError("xAI OAuth discovery did not return authorization and token endpoints.")
    return {
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
    }


def build_authorize_url(
    *,
    authorization_endpoint: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    query = urlencode({
        "response_type": "code",
        "client_id": XAI_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": XAI_OAUTH_SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{authorization_endpoint}?{query}"


def _callback_handler(expected_path: str) -> tuple[type[BaseHTTPRequestHandler], dict[str, Any]]:
    result: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlparse(self.path)
            if parsed.path != expected_path:
                self.send_response(404)
                self.end_headers()
                return

            query = parse_qs(parsed.query)
            result.clear()
            for key, value in query.items():
                result[key] = value[0] if value else ""

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>xAI OAuth complete</h1>"
                b"<p>You can close this browser tab and return to Vellum.</p>"
                b"</body></html>"
            )

    return Handler, result


def start_callback_server(
    *,
    host: str = XAI_OAUTH_REDIRECT_HOST,
    port: int = XAI_OAUTH_REDIRECT_PORT,
    path: str = XAI_OAUTH_REDIRECT_PATH,
) -> tuple[ThreadingHTTPServer, threading.Thread, dict[str, Any], str]:
    handler, result = _callback_handler(path)
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise XAISetupError(f"Could not bind OAuth callback server at {host}:{port}.") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    redirect_uri = f"http://{host}:{port}{path}"
    return server, thread, result, redirect_uri


def wait_for_callback(result: dict[str, Any], timeout_secs: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        if result:
            return dict(result)
        time.sleep(0.1)
    raise XAISetupError("Timed out waiting for the xAI OAuth browser callback.")


def exchange_authorization_code(
    *,
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    code_challenge: str,
    timeout_secs: int,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": XAI_OAUTH_CLIENT_ID,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    response = httpx.post(token_endpoint, data=data, timeout=timeout_secs)
    if response.status_code in (401, 403):
        raise XAISetupError("xAI OAuth token exchange was rejected. Check account subscription/API access.")
    if response.status_code >= 400:
        raise XAISetupError(f"xAI OAuth token exchange returned HTTP {response.status_code}.")
    tokens = response.json()
    if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
        raise XAISetupError("xAI OAuth token exchange did not return an access token.")
    return tokens


def save_oauth_file(path: Path, *, tokens: dict[str, Any], discovery: dict[str, str]) -> None:
    payload = {
        "provider": "xai-oauth",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "base_url": XAI_BASE_URL,
        "client_id": XAI_OAUTH_CLIENT_ID,
        "scope": XAI_OAUTH_SCOPE,
        "tokens": tokens,
        "discovery": {
            "authorization_endpoint": discovery["authorization_endpoint"],
            "token_endpoint": discovery["token_endpoint"],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(project_root: Path, oauth_file: Path, timeout_secs: int, no_browser: bool) -> int:
    discovery = discover_oauth(timeout_secs)
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    server, _thread, result, redirect_uri = start_callback_server()
    try:
        authorize_url = build_authorize_url(
            authorization_endpoint=discovery["authorization_endpoint"],
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=challenge,
        )
        print("Open this URL to sign in with xAI/X:")
        print(authorize_url)
        print(f"\nWaiting for OAuth callback on {redirect_uri}")
        if not no_browser:
            webbrowser.open(authorize_url)

        callback = wait_for_callback(result, timeout_secs)
    finally:
        server.shutdown()
        server.server_close()

    if callback.get("error"):
        detail = callback.get("error_description") or callback["error"]
        raise XAISetupError(f"xAI OAuth failed: {detail}")
    if callback.get("state") != state:
        raise XAISetupError("xAI OAuth state mismatch. Please rerun setup.")
    code = str(callback.get("code") or "").strip()
    if not code:
        raise XAISetupError("xAI OAuth callback did not include an authorization code.")

    tokens = exchange_authorization_code(
        token_endpoint=discovery["token_endpoint"],
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        code_challenge=challenge,
        timeout_secs=timeout_secs,
    )
    save_oauth_file(oauth_file, tokens=tokens, discovery=discovery)
    print(f"\nxAI OAuth configured at {oauth_file.relative_to(project_root)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-secs", type=int, default=DEFAULT_TIMEOUT_SECS)
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--oauth-file", type=Path, help="Defaults to <project-root>/data/xai-oauth.json")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    oauth_file = args.oauth_file.resolve() if args.oauth_file else project_root / "data" / "xai-oauth.json"
    try:
        return run(project_root, oauth_file, args.timeout_secs, args.no_browser)
    except XAISetupError as exc:
        print(f"xAI OAuth setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
