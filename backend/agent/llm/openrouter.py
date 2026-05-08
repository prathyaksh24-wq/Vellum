"""
OpenRouter chat client.

Privacy constraints:
- Every request uses provider.data_collection="deny".
- Every request uses provider.zdr=true when ZDR_ONLY is enabled.
- Audit logs contain metadata only, never prompt or response text.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from agent.config import get_settings

logger = logging.getLogger(__name__)

AUDIT_LOG = Path("data/memory/audit_log.jsonl")


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter cannot return a usable response."""


def _chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "PersonalAgent",
    }


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    try:
        data = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] if text else str(exc)

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            code = error.get("code")
            if message:
                return f"{message} (code: {code or response.status_code})"
        message = data.get("message")
        if message:
            return str(message)
    return str(exc)


def _build_payload(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    session_id: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    provider: dict[str, Any] = {
        "data_collection": "deny",
        "allow_fallbacks": True,
    }
    if settings.zdr_only:
        provider["zdr"] = True

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "provider": provider,
        "stream": False,
    }
    if session_id:
        payload["session_id"] = session_id[:256]
    return payload


def _audit(
    *,
    model: str,
    prompt_len: int,
    response_len: int,
    response_id: str | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "model": model,
        "response_id": response_id,
        "prompt_tokens_approx": prompt_len // 4,
        "response_tokens_approx": response_len // 4,
        "usage": usage or {},
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _extract_answer(data: dict[str, Any]) -> str:
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("OpenRouter response did not contain choices[0].message.content.") from exc

    if isinstance(answer, list):
        parts = []
        for item in answer:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        answer = "".join(parts)

    if not isinstance(answer, str) or not answer.strip():
        raise OpenRouterError("OpenRouter returned an empty answer.")
    return answer.strip()


async def _request_once(
    *,
    client: httpx.AsyncClient,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    temperature: float,
    session_id: str | None,
) -> str:
    settings = get_settings()
    payload = _build_payload(
        system=system,
        user=user,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        session_id=session_id,
    )
    response = await client.post(
        _chat_url(settings.openrouter_base_url),
        headers=_headers(settings.openrouter_api_key),
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise OpenRouterError(_http_error_message(exc)) from exc
    data = response.json()
    answer = _extract_answer(data)
    _audit(
        model=str(data.get("model") or model),
        prompt_len=len(system) + len(user),
        response_len=len(answer),
        response_id=data.get("id"),
        usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
    )
    return answer


async def openrouter_chat(
    *,
    system: str,
    user: str,
    model_override: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    session_id: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    settings = get_settings()
    primary_model = model_override or settings.primary_model
    fallback_model = settings.fallback_model

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=90.0)

    try:
        try:
            return await _request_once(
                client=client,
                system=system,
                user=user,
                model=primary_model,
                max_tokens=max_tokens,
                temperature=temperature,
                session_id=session_id,
            )
        except (httpx.HTTPError, OpenRouterError) as exc:
            if primary_model == fallback_model:
                raise
            logger.warning(
                "OpenRouter model '%s' failed; trying fallback '%s': %s",
                primary_model,
                fallback_model,
                exc,
            )
            return await _request_once(
                client=client,
                system=system,
                user=user,
                model=fallback_model,
                max_tokens=max_tokens,
                temperature=temperature,
                session_id=session_id,
            )
    finally:
        if owns_client:
            await client.aclose()


def openrouter_chat_sync(**kwargs: Any) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(openrouter_chat(**kwargs))
    raise RuntimeError("openrouter_chat_sync cannot run inside an active event loop; use openrouter_chat.")
