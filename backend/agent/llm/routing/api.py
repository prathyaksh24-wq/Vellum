from __future__ import annotations

from collections import Counter
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent.llm.providers import get_provider_registry
from agent.llm.routing.models import (
    CredentialStrategy,
    FallbackTarget,
    ProviderRoutingPolicy,
)
from agent.llm.routing.runtime import get_routing_runtime


router = APIRouter(prefix="/llm-routing", tags=["llm-routing"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FallbackChainBody(StrictModel):
    targets: list[FallbackTarget]


class CredentialCreateBody(StrictModel):
    provider: Literal["openrouter", "openai"]
    label: str = Field(min_length=1, max_length=120)
    secret: str = Field(min_length=1)


class StrategyBody(StrictModel):
    strategy: CredentialStrategy


def _public_credential(record) -> dict:
    body = record.model_dump(mode="json")
    fingerprint = str(body["fingerprint"])
    body["fingerprint"] = fingerprint[-16:]
    return body


@router.get("/status")
def routing_status() -> dict:
    runtime = get_routing_runtime()
    active = get_provider_registry().current_model().id
    health: dict[str, dict[str, int]] = {}
    for provider in ("openrouter", "openai"):
        counts = Counter(item.status.value for item in runtime.store.list_credentials(provider))
        health[provider] = {
            "healthy": counts["healthy"],
            "cooldown": counts["cooldown"],
            "invalid": counts["invalid"],
            "unavailable": counts["unavailable"],
            "total": sum(counts.values()),
        }
    attempts = runtime.store.list_attempts(limit=50, offset=0)
    latest = attempts[-1].model_dump(mode="json") if attempts else None
    primary_provider = (
        "openai"
        if active.startswith("openai/") and health["openai"]["healthy"] > 0
        else "openrouter"
    )
    return {
        "active_model": active,
        "primary_provider": primary_provider,
        "global_policy": runtime.store.get_global_policy().model_dump(mode="json"),
        "fallbacks": [item.model_dump(mode="json") for item in runtime.store.list_fallbacks()],
        "credential_health": health,
        "latest_attempt": latest,
    }


@router.get("/policies")
def list_policies() -> dict:
    runtime = get_routing_runtime()
    return {
        "global": runtime.store.get_global_policy().model_dump(mode="json"),
        "models": {
            model: policy.model_dump(mode="json")
            for model, policy in runtime.store.list_model_policies().items()
        },
    }


@router.put("/policies/global")
def replace_global_policy(policy: ProviderRoutingPolicy) -> dict:
    runtime = get_routing_runtime()
    runtime.store.set_global_policy(policy)
    return runtime.store.get_global_policy().model_dump(mode="json")


@router.put("/policies/models/{model_id:path}")
def replace_model_policy(model_id: str, policy: ProviderRoutingPolicy) -> dict:
    runtime = get_routing_runtime()
    runtime.store.set_model_policy(model_id, policy)
    saved = runtime.store.get_model_policy(model_id)
    return saved.model_dump(mode="json")


@router.delete("/policies/models/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
def remove_model_policy(model_id: str) -> Response:
    runtime = get_routing_runtime()
    if not runtime.store.delete_model_policy(model_id):
        raise HTTPException(status_code=404, detail="Model routing policy not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fallbacks")
def list_fallbacks() -> dict:
    return {
        "targets": [
            item.model_dump(mode="json")
            for item in get_routing_runtime().store.list_fallbacks()
        ]
    }


@router.put("/fallbacks")
def replace_fallbacks(body: FallbackChainBody) -> dict:
    runtime = get_routing_runtime()
    try:
        runtime.store.replace_fallbacks(body.targets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return list_fallbacks()


@router.get("/credentials")
def list_credentials() -> dict:
    runtime = get_routing_runtime()
    return {
        "credentials": [
            _public_credential(item) for item in runtime.store.list_credentials()
        ],
        "strategies": {
            provider: runtime.store.get_pool_state(provider)[0].value
            for provider in ("openrouter", "openai")
        },
    }


@router.post("/credentials", status_code=status.HTTP_201_CREATED)
def add_credential(body: CredentialCreateBody) -> dict:
    runtime = get_routing_runtime()
    try:
        record = runtime.secrets.add_manual(body.provider, body.label, body.secret)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Credential could not be stored.") from exc
    return _public_credential(record)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_credential(credential_id: str) -> Response:
    runtime = get_routing_runtime()
    try:
        runtime.secrets.remove_manual(credential_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Credential not found.") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/credentials/{provider}/strategy")
def replace_strategy(provider: Literal["openrouter", "openai"], body: StrategyBody) -> dict:
    runtime = get_routing_runtime()
    runtime.pool.set_strategy(provider, body.strategy)
    return {"provider": provider, "strategy": body.strategy.value}


@router.post("/credentials/{provider}/reset")
def reset_pool(provider: Literal["openrouter", "openai"]) -> dict:
    get_routing_runtime().pool.reset_provider(provider)
    return {"ok": True, "provider": provider}


@router.get("/attempts")
def list_attempts(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    rows = get_routing_runtime().store.list_attempts(limit=limit, offset=offset)
    return {
        "attempts": [row.model_dump(mode="json") for row in rows],
        "limit": limit,
        "offset": offset,
    }
