#!/usr/bin/env python3
"""Browser OAuth setup for official X API v2 account actions."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
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


X_API_BASE_URL = "https://api.x.com/2"
X_API_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_API_TOKEN_URL = "https://api.x.com/2/oauth2/token"
X_API_OAUTH_SCOPE = "tweet.read users.read tweet.write bookmark.read offline.access"
X_API_REDIRECT_HOST = "127.0.0.1"
X_API_REDIRECT_PORT = 56122
X_API_REDIRECT_PATH = "/callback"
DEFAULT_TIMEOUT_SECS = 180


class XApiSetupError(RuntimeError):
    """X API OAuth setup failed."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(*, client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    query = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": X_API_OAUTH_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })
    return f"{X_API_AUTHORIZE_URL}?{query}"


def _callback_handler(expected_path: str) -> tuple[type[BaseHTTPRequestHandler], dict[str, Any]]:
    result: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
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
                b"<html><body><h1>X API OAuth complete</h1>"
                b"<p>You can close this tab and return to Vellum.</p>"
                b"</body></html>"
            )

    return Handler, result


def start_callback_server() -> tuple[ThreadingHTTPServer, dict[str, Any], str]:
    handler, result = _callback_handler(X_API_REDIRECT_PATH)
    try:
        server = ThreadingHTTPServer((X_API_REDIRECT_HOST, X_API_REDIRECT_PORT), handler)
    except OSError as exc:
        raise XApiSetupError(f"Could not bind callback server at {X_API_REDIRECT_HOST}:{X_API_REDIRECT_PORT}.") from exc
    threading.Thread(target=server.serve_forever, daemon=True).start()
    redirect_uri = f"http://{X_API_REDIRECT_HOST}:{X_API_REDIRECT_PORT}{X_API_REDIRECT_PATH}"
    return server, result, redirect_uri


def wait_for_callback(result: dict[str, Any], timeout_secs: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        if result:
            return dict(result)
        time.sleep(0.1)
    raise XApiSetupError("Timed out waiting for the X OAuth browser callback.")


def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    timeout_secs: int,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret
    response = httpx.post(X_API_TOKEN_URL, data=data, timeout=timeout_secs)
    if response.status_code in (401, 403):
        raise XApiSetupError("X API OAuth token exchange was rejected. Check app scopes, callback URL, and API access.")
    if response.status_code >= 400:
        raise XApiSetupError(f"X API OAuth token exchange returned HTTP {response.status_code}.")
    tokens = response.json()
    if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
        raise XApiSetupError("X API OAuth token exchange did not return an access token.")
    return tokens


def save_oauth_file(path: Path, *, client_id: str, tokens: dict[str, Any]) -> None:
    payload = {
        "provider": "x-api-oauth",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "base_url": X_API_BASE_URL,
        "client_id": client_id,
        "scope": X_API_OAUTH_SCOPE,
        "token_endpoint": X_API_TOKEN_URL,
        "tokens": tokens,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(project_root: Path, oauth_file: Path, timeout_secs: int, no_browser: bool) -> int:
    client_id = os.environ.get("X_API_CLIENT_ID", "").strip()
    client_secret = os.environ.get("X_API_CLIENT_SECRET", "").strip()
    if not client_id:
        raise XApiSetupError("Set X_API_CLIENT_ID in .env before running X API OAuth setup.")

    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(32)
    server, result, redirect_uri = start_callback_server()
    try:
        authorize_url = build_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=challenge,
        )
        print("Open this URL to authorize Vellum for X API account actions:")
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
        raise XApiSetupError(f"X API OAuth failed: {detail}")
    if callback.get("state") != state:
        raise XApiSetupError("X API OAuth state mismatch. Please rerun setup.")
    code = str(callback.get("code") or "").strip()
    if not code:
        raise XApiSetupError("X API OAuth callback did not include an authorization code.")

    tokens = exchange_authorization_code(
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        timeout_secs=timeout_secs,
    )
    save_oauth_file(oauth_file, client_id=client_id, tokens=tokens)
    print(f"\nX API OAuth configured at {oauth_file.relative_to(project_root)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-secs", type=int, default=DEFAULT_TIMEOUT_SECS)
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--oauth-file", type=Path, help="Defaults to <project-root>/data/x-api-oauth.json")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    oauth_file = args.oauth_file.resolve() if args.oauth_file else project_root / "data" / "x-api-oauth.json"
    try:
        return run(project_root, oauth_file, args.timeout_secs, args.no_browser)
    except XApiSetupError as exc:
        print(f"X API OAuth setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
