"""Direct xAI OAuth-backed X search client.

Calls the xAI Responses API with the `x_search` tool and normalizes cited X
posts into the existing ingest item shape.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.3"
DEFAULT_TIMEOUT_SECS = 180
SOURCE_LABEL = "xAI X Search OAuth"

TWEET_ARCHIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tweets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "url": {"type": "string"},
                    "created_at": {"type": ["string", "null"]},
                    "is_reply": {"type": ["boolean", "null"]},
                    "is_retweet": {"type": ["boolean", "null"]},
                    "is_quote": {"type": ["boolean", "null"]},
                    "media": {
                        "type": ["array", "null"],
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {},
                        },
                    },
                },
                "required": ["text", "url"],
            },
        }
    },
    "required": ["tweets"],
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_STATUS_RE = re.compile(r"https?://(?:x|twitter)\.com/([^/\s]+)/status/(\d+)", re.IGNORECASE)


class XAISearchError(RuntimeError):
    """xAI completed but did not return usable search data."""


class XAIAuthError(XAISearchError):
    """xAI OAuth credentials are missing or invalid."""


def _date(value: datetime) -> str:
    return value.astimezone(timezone.utc).date().isoformat()


def _prompt(handle: str, start: datetime, end: datetime, max_items: int) -> str:
    start_date = _date(start)
    end_date = _date(end)
    return f"""Find original posts from @{handle} on X.

Search constraints:
- allowed_x_handles: ["{handle}"]
- from_date: "{start_date}"
- to_date: "{end_date}"
- maximum records: {max_items}

Return only valid JSON, with no prose or markdown. Shape:
{{
  "tweets": [
    {{
      "text": "exact post text when visible",
      "url": "https://x.com/{handle}/status/<status_id>",
      "created_at": "ISO-8601 timestamp or YYYY-MM-DD when available",
      "is_reply": false,
      "is_retweet": false,
      "is_quote": false,
      "media": []
    }}
  ]
}}

Include only records with a cited X status URL and clear post text. Omit uncertain records."""


def _search_prompt(query: str, start: datetime, end: datetime, max_items: int) -> str:
    return f"""Search X for posts matching this query:
{query}

Search constraints:
- from_date: "{_date(start)}"
- to_date: "{_date(end)}"
- maximum records: {max_items}

Return only valid JSON, with no prose or markdown. Shape:
{{
  "tweets": [
    {{
      "text": "exact post text when visible",
      "url": "https://x.com/<handle>/status/<status_id>",
      "created_at": "ISO-8601 timestamp or YYYY-MM-DD when available",
      "is_reply": false,
      "is_retweet": false,
      "is_quote": false,
      "media": []
    }}
  ]
}}

Include only records with a cited X status URL and clear post text. Omit uncertain records."""


def _extract_json(stdout: str) -> Any:
    text = stdout.strip()
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise XAISearchError("xAI X Search did not return valid JSON.") from exc


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise XAISearchError("xAI X Search JSON must be an object or array.")
    for key in ("tweets", "items", "posts", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _candidate_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("url", "x_url", "tweetUrl", "tweet_url", "citation_url", "source_url"):
        value = item.get(key)
        if isinstance(value, str):
            urls.append(value)
    for key in ("citations", "inline_citations", "sources"):
        value = item.get(key)
        if isinstance(value, list):
            for citation in value:
                if isinstance(citation, dict) and isinstance(citation.get("url"), str):
                    urls.append(citation["url"])
                elif isinstance(citation, str):
                    urls.append(citation)
    return urls


def _status_from_item(item: dict[str, Any]) -> tuple[str, str] | None:
    for url in _candidate_urls(item):
        match = _STATUS_RE.search(url)
        if match:
            handle, status_id = match.groups()
            return status_id, f"https://x.com/{handle}/status/{status_id}"
    status_id = item.get("id") or item.get("status_id") or item.get("tweetId") or item.get("tweet_id")
    if status_id:
        handle = str(item.get("handle") or item.get("author") or "").lstrip("@")
        if handle:
            return str(status_id), f"https://x.com/{handle}/status/{status_id}"
    return None


def _created_at(item: dict[str, Any], start: datetime) -> str:
    raw = item.get("createdAt") or item.get("created_at") or item.get("posted_at") or item.get("date")
    if isinstance(raw, str) and raw.strip():
        value = raw.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return f"{value}T00:00:00+00:00"
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return start.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_item(item: dict[str, Any], *, start: datetime) -> dict[str, Any] | None:
    status = _status_from_item(item)
    if status is None:
        return None
    status_id, url = status

    text = str(item.get("text") or item.get("full_text") or item.get("content") or "").strip()
    if not text:
        return None

    return {
        "id": status_id,
        "url": url,
        "text": text,
        "createdAt": _created_at(item, start),
        "isReply": bool(item.get("isReply") or item.get("is_reply")),
        "isRetweet": bool(item.get("isRetweet") or item.get("is_retweet")),
        "isQuote": bool(item.get("isQuote") or item.get("is_quote")),
        "media": item.get("media") if isinstance(item.get("media"), list) else [],
    }


def _auth_error_message() -> str:
    return (
        "xAI OAuth is unavailable. Set XAI_OAUTH_ACCESS_TOKEN or configure "
        "data/xai-oauth.json with an access token and optional refresh token."
    )


def _load_oauth_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XAIAuthError(_auth_error_message()) from exc


def _token_container(data: dict[str, Any]) -> dict[str, Any]:
    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        return tokens
    return data


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


def _should_refresh(token: str, *, has_refresh_token: bool) -> bool:
    if not has_refresh_token:
        return False
    exp = _jwt_exp(token)
    if exp is None:
        return token.count(".") == 2
    return exp <= int(time.time()) + 60


def _save_tokens(path: Path, data: dict[str, Any], fresh: dict[str, Any]) -> None:
    container = _token_container(data)
    container["access_token"] = fresh["access_token"]
    if fresh.get("refresh_token"):
        container["refresh_token"] = fresh["refresh_token"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _refresh_token(path: Path, data: dict[str, Any], timeout_secs: int) -> str:
    tokens = _token_container(data)
    refresh_token = str(tokens.get("refresh_token") or "")
    token_endpoint = (
        data.get("token_endpoint")
        or (data.get("discovery") if isinstance(data.get("discovery"), dict) else {}).get("token_endpoint")
    )
    if not refresh_token or not token_endpoint:
        raise XAIAuthError(_auth_error_message())

    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    client_id = os.environ.get("XAI_OAUTH_CLIENT_ID", "").strip() or str(data.get("client_id") or "").strip()
    if client_id:
        form["client_id"] = client_id

    try:
        response = httpx.post(str(token_endpoint), data=form, timeout=timeout_secs)
    except httpx.HTTPError as exc:
        raise XAIAuthError("xAI OAuth token refresh failed. Reconfigure data/xai-oauth.json or XAI_OAUTH_ACCESS_TOKEN.") from exc
    if response.status_code in (401, 403):
        raise XAIAuthError("xAI OAuth token refresh was rejected. Reconfigure data/xai-oauth.json or XAI_OAUTH_ACCESS_TOKEN.")
    if response.status_code >= 400:
        raise XAISearchError(f"xAI OAuth token refresh returned HTTP {response.status_code}.")
    fresh = response.json()
    access_token = fresh.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise XAIAuthError("xAI OAuth token refresh did not return an access token.")
    _save_tokens(path, data, fresh)
    return access_token


def _access_token(oauth_file: Path | None, timeout_secs: int) -> str:
    env_token = os.environ.get("XAI_OAUTH_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if api_key:
        return api_key

    if oauth_file is None or not oauth_file.exists():
        raise XAIAuthError(_auth_error_message())

    data = _load_oauth_file(oauth_file)
    tokens = _token_container(data)
    token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not token:
        raise XAIAuthError(_auth_error_message())
    if _should_refresh(token, has_refresh_token=bool(refresh_token)):
        return _refresh_token(oauth_file, data, timeout_secs)
    return token


def _response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    collected: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                collected.append(content["text"])
    return "\n".join(collected)


def fetch_tweets(
    *,
    handle: str,
    start: datetime,
    end: datetime,
    max_items: int,
    oauth_file: Path | None = None,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """Fetch cited X posts through xAI OAuth and normalize for ingest."""
    token = _access_token(oauth_file, timeout_secs)
    body = {
        "model": os.environ.get("XAI_MODEL", model).strip() or model,
        "input": _prompt(handle, start, end, max_items),
        "tools": [
            {
                "type": "x_search",
                "allowed_x_handles": [handle],
                "from_date": _date(start),
                "to_date": _date(end),
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "x_tweet_archive",
                "schema": TWEET_ARCHIVE_SCHEMA,
                "strict": True,
            }
        },
    }

    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_secs,
        )
    except httpx.HTTPError as exc:
        raise XAISearchError("xAI X Search request failed.") from exc

    if response.status_code in (401, 403):
        raise XAIAuthError("xAI OAuth request was rejected. Check XAI_OAUTH_ACCESS_TOKEN or data/xai-oauth.json.")
    if response.status_code >= 400:
        raise XAISearchError(f"xAI Responses API returned HTTP {response.status_code}.")

    search_payload = _extract_json(_response_text(response.json()))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _items(search_payload):
        record = _normalize_item(item, start=start)
        if record is None or record["id"] in seen:
            continue
        seen.add(record["id"])
        normalized.append(record)
        if len(normalized) >= max_items:
            break
    return normalized


def search_x(
    *,
    query: str,
    start: datetime,
    end: datetime,
    max_items: int,
    oauth_file: Path | None = None,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """Search public X through xAI X Search and normalize cited posts."""
    token = _access_token(oauth_file, timeout_secs)
    body = {
        "model": os.environ.get("XAI_MODEL", model).strip() or model,
        "input": _search_prompt(query, start, end, max_items),
        "tools": [
            {
                "type": "x_search",
                "from_date": _date(start),
                "to_date": _date(end),
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "x_tweet_archive",
                "schema": TWEET_ARCHIVE_SCHEMA,
                "strict": True,
            }
        },
    }
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_secs,
        )
    except httpx.HTTPError as exc:
        raise XAISearchError("xAI X Search request failed.") from exc
    if response.status_code in (401, 403):
        raise XAIAuthError("xAI OAuth request was rejected. Check XAI_OAUTH_ACCESS_TOKEN or data/xai-oauth.json.")
    if response.status_code >= 400:
        raise XAISearchError(f"xAI Responses API returned HTTP {response.status_code}.")

    search_payload = _extract_json(_response_text(response.json()))
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _items(search_payload):
        record = _normalize_item(item, start=start)
        if record is None or record["id"] in seen:
            continue
        seen.add(record["id"])
        normalized.append(record)
        if len(normalized) >= max_items:
            break
    return normalized
