"""Official X API v2 client for Vellum account actions."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.x.com/2"
DEFAULT_OAUTH_FILE = Path(__file__).resolve().parents[1] / "data" / "x-api-oauth.json"
DEFAULT_TIMEOUT_SECS = 60


class XApiError(RuntimeError):
    """X API request failed."""


class XApiAuthError(XApiError):
    """X API OAuth credentials are missing or invalid."""


def _auth_error_message() -> str:
    return (
        "X API OAuth is unavailable. Set X_API_CLIENT_ID and run "
        "`scripts/setup_x_api_oauth.ps1` to create data/x-api-oauth.json."
    )


def _load_oauth_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XApiAuthError(_auth_error_message()) from exc


def _jwt_exp(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None
    exp = payload.get("exp")
    return exp if isinstance(exp, int) else None


def _should_refresh(token: str, refresh_token: str) -> bool:
    if not refresh_token:
        return False
    exp = _jwt_exp(token)
    if exp is None:
        return token.count(".") == 2
    return exp <= int(time.time()) + 60


def _save_tokens(path: Path, data: dict[str, Any], fresh: dict[str, Any]) -> None:
    tokens = data.setdefault("tokens", {})
    tokens["access_token"] = fresh["access_token"]
    if fresh.get("refresh_token"):
        tokens["refresh_token"] = fresh["refresh_token"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _refresh_token(path: Path, data: dict[str, Any], timeout_secs: int) -> str:
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    client_id = str(data.get("client_id") or "").strip()
    token_endpoint = str(data.get("token_endpoint") or "https://api.x.com/2/oauth2/token").strip()
    if not refresh_token or not client_id:
        raise XApiAuthError(_auth_error_message())
    response = httpx.post(
        token_endpoint,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        timeout=timeout_secs,
    )
    if response.status_code in (401, 403):
        raise XApiAuthError("X API OAuth token refresh was rejected. Rerun scripts/setup_x_api_oauth.ps1.")
    if response.status_code >= 400:
        raise XApiError(f"X API OAuth token refresh returned HTTP {response.status_code}.")
    fresh = response.json()
    if not isinstance(fresh.get("access_token"), str) or not fresh["access_token"]:
        raise XApiAuthError("X API OAuth token refresh did not return an access token.")
    _save_tokens(path, data, fresh)
    return fresh["access_token"]


def _access_token(oauth_file: Path, timeout_secs: int) -> str:
    if not oauth_file.exists():
        raise XApiAuthError(_auth_error_message())
    data = _load_oauth_file(oauth_file)
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not access_token:
        raise XApiAuthError(_auth_error_message())
    if _should_refresh(access_token, refresh_token):
        return _refresh_token(oauth_file, data, timeout_secs)
    return access_token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _handle_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code in (401, 403):
        raise XApiAuthError("X API OAuth request was rejected. Check X API OAuth scopes, developer app access, or rerun setup.")
    if response.status_code == 429:
        raise XApiError("X API rate limit reached. Try again later.")
    if response.status_code >= 400:
        raise XApiError(f"X API returned HTTP {response.status_code}.")
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def get_me(*, oauth_file: Path = DEFAULT_OAUTH_FILE, timeout_secs: int = DEFAULT_TIMEOUT_SECS) -> dict[str, Any]:
    token = _access_token(oauth_file, timeout_secs)
    response = httpx.get(
        f"{DEFAULT_BASE_URL}/users/me",
        headers=_headers(token),
        timeout=timeout_secs,
    )
    return _handle_response(response)


def get_bookmarks(
    *,
    user_id: str,
    max_results: int = 10,
    pagination_token: str = "",
    oauth_file: Path = DEFAULT_OAUTH_FILE,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
) -> dict[str, Any]:
    token = _access_token(oauth_file, timeout_secs)
    params = {
        "max_results": max(1, min(int(max_results), 100)),
        "tweet.fields": "id,text,author_id,created_at,public_metrics,referenced_tweets,entities",
    }
    if pagination_token:
        params["pagination_token"] = pagination_token
    response = httpx.get(
        f"{DEFAULT_BASE_URL}/users/{user_id}/bookmarks",
        headers=_headers(token),
        params=params,
        timeout=timeout_secs,
    )
    return _handle_response(response)


def post_tweet(*, text: str, oauth_file: Path = DEFAULT_OAUTH_FILE, timeout_secs: int = DEFAULT_TIMEOUT_SECS) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise XApiError("Tweet text is required.")
    response = httpx.post(
        f"{DEFAULT_BASE_URL}/tweets",
        headers=_headers(_access_token(oauth_file, timeout_secs)),
        json={"text": text},
        timeout=timeout_secs,
    )
    return _handle_response(response)
