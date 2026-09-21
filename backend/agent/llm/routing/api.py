from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent.llm.providers import get_provider_registry
from agent.llm.routing.models import (
    CredentialStrategy,
    FallbackTarget,
    ProviderRoutingPolicy,
)
from agent.llm.routing.runtime import get_routing_runtime
from agent.app_actions.settings_runtime import (
    ROUTING_CREDENTIAL_REMOVE_ACTION_ID,
    ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
    ROUTING_FALLBACKS_SET_ACTION_ID,
    ROUTING_MODEL_POLICY_REMOVE_ACTION_ID,
    ROUTING_MODEL_POLICY_SET_ACTION_ID,
    ROUTING_POLICY_SET_ACTION_ID,
    ROUTING_POOL_RESET_ACTION_ID,
)


router = APIRouter(prefix="/llm-routing", tags=["llm-routing"])
_action_dispatcher: Callable[[str, dict[str, Any]], Any] | None = None


def configure_action_dispatcher(dispatcher: Callable[[str, dict[str, Any]], Any]) -> None:
    global _action_dispatcher
    _action_dispatcher = dispatcher


def _dispatch_action(action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if _action_dispatcher is None:
        raise HTTPException(status_code=503, detail="App Action runtime is unavailable.")
    receipt = _action_dispatcher(action_id, arguments)
    if receipt.status != "applied":
        status_code = 422 if receipt.error_code == "INVALID_ACTION_ARGUMENTS" else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": receipt.error_code or "APP_ACTION_FAILED", "message": receipt.message},
        )
    return dict(receipt.result)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FallbackChainBody(StrictModel):
    targets: list[FallbackTarget]


class CredentialCreateBody(StrictModel):
    provider: Literal["openrouter", "openai"]
    label: str = Field(min_length=1, max_length=120)
    secret: str = Field(min_length=1, repr=False, exclude=True)


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
    # Catalog IDs use vendor namespaces inside OpenRouter; they are not
    # native-provider selections. Native routes must be explicitly configured.
    primary_provider = "openrouter"
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
    arguments = policy.model_dump(mode="json", exclude={"data_collection", "zdr"})
    return _dispatch_action(ROUTING_POLICY_SET_ACTION_ID, arguments)["global_policy"]


@router.put("/policies/models/{model_id:path}")
def replace_model_policy(model_id: str, policy: ProviderRoutingPolicy) -> dict:
    return _dispatch_action(
        ROUTING_MODEL_POLICY_SET_ACTION_ID,
        {
            "model_id": model_id,
            "policy": policy.model_dump(mode="json", exclude={"data_collection", "zdr"}),
        },
    )["policy"]


@router.delete("/policies/models/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
def remove_model_policy(model_id: str) -> Response:
    _dispatch_action(ROUTING_MODEL_POLICY_REMOVE_ACTION_ID, {"model_id": model_id})
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
    models = [target.model for target in body.targets if target.provider == "openrouter"]
    result = _dispatch_action(ROUTING_FALLBACKS_SET_ACTION_ID, {"models": models})
    return {"targets": result["fallbacks"]}


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
    raise HTTPException(
        status_code=410,
        detail={
            "code": "APP_ACTION_REQUIRED",
            "message": "Use llm.routing.credential.add so the secret is confirmation-bound.",
        },
    )


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_credential(credential_id: str) -> Response:
    _dispatch_action(ROUTING_CREDENTIAL_REMOVE_ACTION_ID, {"credential_id": credential_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/credentials/{provider}/strategy")
def replace_strategy(provider: Literal["openrouter", "openai"], body: StrategyBody) -> dict:
    result = _dispatch_action(
        ROUTING_CREDENTIAL_STRATEGY_SET_ACTION_ID,
        {"provider": provider, "strategy": body.strategy.value},
    )
    return {"provider": result["provider"], "strategy": result["strategy"]}


@router.post("/credentials/{provider}/reset")
def reset_pool(provider: Literal["openrouter", "openai"]) -> dict:
    result = _dispatch_action(ROUTING_POOL_RESET_ACTION_ID, {"provider": provider})
    return {"ok": True, "provider": provider, "changed": result["changed"], "reset_count": result["reset_count"]}


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
