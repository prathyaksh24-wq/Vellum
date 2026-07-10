"""Backend-owned LLM routing controls for Vellum."""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import tool

from agent.llm.providers import canonical_model_id
from agent.llm.routing.models import (
    CredentialStrategy,
    FallbackTarget,
    ProviderRoutingPolicy,
)
from agent.llm.routing.runtime import get_routing_runtime


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _status_payload() -> dict:
    runtime = get_routing_runtime()
    attempts = runtime.store.list_attempts(limit=10, offset=0)
    latest = attempts[-1].model_dump(mode="json") if attempts else None
    credentials = runtime.store.list_credentials()
    health: dict[str, dict[str, int]] = {}
    for provider in ("openrouter", "openai"):
        provider_credentials = [item for item in credentials if item.provider == provider]
        health[provider] = {
            "healthy": sum(1 for item in provider_credentials if item.status.value == "healthy"),
            "cooldown": sum(1 for item in provider_credentials if item.status.value == "cooldown"),
            "invalid": sum(1 for item in provider_credentials if item.status.value == "invalid"),
            "unavailable": sum(1 for item in provider_credentials if item.status.value == "unavailable"),
            "total": len(provider_credentials),
            "strategy": runtime.store.get_pool_state(provider)[0].value,
        }
    return {
        "ok": True,
        "global_policy": runtime.store.get_global_policy().model_dump(mode="json"),
        "fallbacks": [item.model_dump(mode="json") for item in runtime.store.list_fallbacks()],
        "credential_health": health,
        "latest_attempt": latest,
    }


@tool
def llm_routing(
    action: str,
    sort: Literal["price", "latency", "throughput"] | str | None = None,
    require_parameters: bool | None = None,
    allow_fallbacks: bool | None = None,
    fallback_models: list[str] | None = None,
    fallback_model: str = "",
    credential_provider: Literal["openrouter", "openai"] | str = "openrouter",
    credential_strategy: Literal["fill_first", "round_robin", "least_used", "random"] | str = "fill_first",
) -> str:
    """Inspect or change backend-owned LLM routing.

    Actions: status, set_provider_routing, set_fallbacks, add_fallback,
    clear_fallbacks, set_credential_strategy, reset_credential_pool.

    Do not use this tool for API key secrets. Credential secrets are configured
    through backend env/keyring paths, not through chat.
    """

    runtime = get_routing_runtime()
    normalized = action.strip().casefold().replace("-", "_")

    if normalized in {"status", "inspect", "show"}:
        return _json({"action": normalized, **_status_payload()})

    if normalized in {"set_provider_routing", "set_routing", "provider_routing"}:
        current = runtime.store.get_global_policy()
        selected_sort = sort if sort in {"price", "latency", "throughput"} else current.sort
        policy = ProviderRoutingPolicy(
            sort=selected_sort,
            only=current.only,
            ignore=current.ignore,
            order=current.order,
            require_parameters=current.require_parameters if require_parameters is None else require_parameters,
            allow_fallbacks=current.allow_fallbacks if allow_fallbacks is None else allow_fallbacks,
            data_collection="deny",
            zdr=True,
        )
        runtime.store.set_global_policy(policy)
        return _json({"action": normalized, "ok": True, "global_policy": policy.model_dump(mode="json")})

    if normalized in {"set_fallbacks", "replace_fallbacks"}:
        models = [canonical_model_id(item) for item in (fallback_models or []) if item and item.strip()]
        runtime.store.replace_fallbacks([FallbackTarget(provider="openrouter", model=model) for model in models])
        return _json({"action": normalized, **_status_payload()})

    if normalized == "add_fallback":
        model = canonical_model_id(fallback_model.strip())
        if not model:
            return _json({"action": normalized, "ok": False, "error": "fallback_model is required"})
        current = runtime.store.list_fallbacks()
        target = FallbackTarget(provider="openrouter", model=model)
        if target.identity not in {item.identity for item in current}:
            runtime.store.replace_fallbacks([*current, target])
        return _json({"action": normalized, **_status_payload()})

    if normalized == "clear_fallbacks":
        runtime.store.replace_fallbacks([])
        return _json({"action": normalized, **_status_payload()})

    if normalized == "set_credential_strategy":
        provider = credential_provider.strip().casefold()
        if provider not in {"openrouter", "openai"}:
            return _json({"action": normalized, "ok": False, "error": "unsupported credential provider"})
        try:
            strategy = CredentialStrategy(credential_strategy)
        except ValueError:
            return _json({"action": normalized, "ok": False, "error": "unsupported credential strategy"})
        runtime.pool.set_strategy(provider, strategy)
        return _json({"action": normalized, **_status_payload()})

    if normalized == "reset_credential_pool":
        provider = credential_provider.strip().casefold()
        if provider not in {"openrouter", "openai"}:
            return _json({"action": normalized, "ok": False, "error": "unsupported credential provider"})
        runtime.pool.reset_provider(provider)
        return _json({"action": normalized, **_status_payload()})

    return _json({"action": normalized, "ok": False, "error": "unsupported routing action"})
