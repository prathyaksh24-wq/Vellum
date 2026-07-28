"""
OpenRouter chat client.

Privacy constraints:
- Every request uses provider.data_collection="deny".
- Every request uses provider.zdr=true when ZDR_ONLY is enabled.
- Audit logs contain metadata only, never prompt or response text.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from agent.config import get_settings
from agent.llm.routing.runtime import get_routing_runtime
from agent.privacy.classifier import classify
from agent.privacy.disclosure import (
    DisclosureBroker,
    DisclosureGrant,
    ProtectionMode,
)
from agent.telemetry.turn_audit import TurnAudit
from agent.telemetry.usage_ledger import UsageLedger

logger = logging.getLogger(__name__)

AUDIT_LOG = Path("data/memory/audit_log.jsonl")

_or_ledger = UsageLedger(Path("data/memory/usage.db"))


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
    reviewed_providers = list(settings.reviewed_openrouter_providers)
    provider: dict[str, Any] = {
        "data_collection": "deny",
        "only": reviewed_providers,
        "order": reviewed_providers,
        "allow_fallbacks": True,
        "zdr": True,
    }

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
    thread_id: str,
    model: str,
    privacy_class: str,
    prompt_len: int,
    response_len: int,
    usage: dict[str, Any] | None = None,
) -> None:
    audit = TurnAudit(
        thread_id=thread_id,
        model=model,
        provider="openrouter",
        privacy_class=privacy_class,
        path=AUDIT_LOG,
        saved=False,
    )
    audit.observe_usage(
        usage
        or {
            "prompt_tokens": prompt_len // 4,
            "completion_tokens": response_len // 4,
        }
    )
    audit.mark_first_token()
    audit.finalize("completed")


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
    broker: DisclosureBroker,
    privacy_mode: ProtectionMode | str | None,
    disclosure_grant: DisclosureGrant | None,
    disclosure_purpose: str,
) -> str:
    settings = get_settings()
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    prepared = broker.prepare_messages(
        [SystemMessage(content=system), HumanMessage(content=user)],
        destination="openrouter",
        model=model,
        purpose=disclosure_purpose,
        thread_id=session_id or "background",
        mode=privacy_mode,
        grant=disclosure_grant,
    )
    payload = _build_payload(
        system=str(prepared.messages[0].content),
        user=str(prepared.messages[1].content),
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        session_id=session_id,
    )
    try:
        response = await client.post(
            _chat_url(settings.openrouter_base_url),
            headers=_headers(settings.openrouter_api_key),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        answer = _extract_answer(data)
    except BaseException as exc:
        broker.complete(prepared, outcome="failed")
        if isinstance(exc, httpx.HTTPStatusError):
            raise OpenRouterError(_http_error_message(exc)) from exc
        raise
    broker.complete(prepared, outcome="success")
    answer = str(prepared.restore_message(AIMessage(content=answer)).content)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    _audit(
        thread_id=session_id or "background",
        model=str(data.get("model") or model),
        privacy_class=classify(user)[0].value,
        prompt_len=len(system) + len(user),
        response_len=len(answer),
        usage=usage,
    )
    try:
        if usage:
            in_tok = int(usage.get("prompt_tokens") or 0)
            out_tok = int(usage.get("completion_tokens") or 0)
            if in_tok or out_tok:
                _or_ledger.record(
                    thread_id="background",
                    model=str(data.get("model") or model),
                    in_tokens=in_tok,
                    out_tokens=out_tok,
                    source="cli",
                )
    except Exception:
        pass
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
    broker: DisclosureBroker | None = None,
    privacy_mode: ProtectionMode | str | None = None,
    disclosure_grant: DisclosureGrant | None = None,
    disclosure_purpose: str = "chat",
) -> str:
    settings = get_settings()
    primary_model = model_override or settings.primary_model
    fallback_model = settings.fallback_model

    if client is None:
        from langchain_core.messages import HumanMessage, SystemMessage

        result = await get_routing_runtime().engine.ainvoke(
            messages=[
                SystemMessage(content=system),
                HumanMessage(content=user),
            ],
            primary_model=primary_model,
            temperature=temperature,
            max_tokens=max_tokens,
            thread_id=session_id or "background",
            privacy_mode=privacy_mode,
            disclosure_grant=disclosure_grant,
            disclosure_purpose=disclosure_purpose,
        )
        answer = getattr(result, "content", None)
        if not isinstance(answer, str) or not answer.strip():
            raise OpenRouterError("Routed model returned an empty answer.")
        return answer.strip()

    broker = broker or get_routing_runtime().broker
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
                broker=broker,
                privacy_mode=privacy_mode,
                disclosure_grant=disclosure_grant,
                disclosure_purpose=disclosure_purpose,
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
                broker=broker,
                privacy_mode=privacy_mode,
                disclosure_grant=disclosure_grant,
                disclosure_purpose=disclosure_purpose,
            )
    except asyncio.CancelledError:
        TurnAudit(
            thread_id=session_id or "background",
            model=primary_model,
            provider="openrouter",
            privacy_class=classify(user)[0].value,
            path=AUDIT_LOG,
        ).finalize("cancelled")
        raise
    except Exception:
        TurnAudit(
            thread_id=session_id or "background",
            model=primary_model,
            provider="openrouter",
            privacy_class=classify(user)[0].value,
            path=AUDIT_LOG,
        ).finalize("failed")
        raise


def openrouter_chat_sync(**kwargs: Any) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(openrouter_chat(**kwargs))
    raise RuntimeError("openrouter_chat_sync cannot run inside an active event loop; use openrouter_chat.")
