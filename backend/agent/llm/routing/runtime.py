from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Any

from agent.config import get_settings
from agent.llm.routing.adapters import OpenRouterAdapter
from agent.llm.routing.chat_model import RoutedChatModel
from agent.llm.routing.engine import RoutingEngine
from agent.llm.routing.models import FallbackTarget
from agent.llm.routing.pool import CredentialPool
from agent.llm.routing.secrets import KeyringBackend, SecretResolver
from agent.llm.routing.store import RoutingStore
from agent.privacy.disclosure import (
    DestinationPolicy,
    DisclosureBroker,
    DisclosureModelAdapter,
    DisclosurePolicy,
    ProtectionMode,
)



@dataclass(frozen=True)
class RoutingRuntime:
    store: RoutingStore
    secrets: SecretResolver
    pool: CredentialPool
    broker: DisclosureBroker
    engine: RoutingEngine
    chat_model: RoutedChatModel


def _active_model() -> str:
    from agent.llm.providers import get_provider_registry

    return get_provider_registry().current_model().id


def build_routing_runtime(
    *,
    settings: Any | None = None,
    keyring_backend: KeyringBackend | None = None,
    fingerprint_salt: bytes | None = None,
) -> RoutingRuntime:
    settings = settings or get_settings()
    store = RoutingStore(settings.llm_routing_db_path)
    resolver = SecretResolver(
        store,
        keyring_backend,
        service=settings.llm_routing_keyring_service,
        fingerprint_salt=fingerprint_salt,
    )
    resolver.reconcile_environment({"openrouter": "OPENROUTER_API_KEY"})
    borrowed = {
        "openrouter": ("OPENROUTER_API_KEY", getattr(settings, "openrouter_api_key", None)),
    }
    for provider, (variable, value) in borrowed.items():
        if value and not os.environ.get(variable):
            resolver.reconcile_borrowed(provider, variable, value)

    if not store.fallbacks_initialized() and getattr(settings, "fallback_model", ""):
        store.replace_fallbacks(
            [FallbackTarget(provider="openrouter", model=settings.fallback_model)]
        )

    pool = CredentialPool(store)
    approved_models = set(settings.reviewed_openrouter_models)
    configured_models = {
        model
        for model in (
            settings.primary_model,
            settings.fallback_model,
            settings.fast_model,
            settings.cloud_escalation_model,
        )
        if model
    }
    unreviewed_models = configured_models - approved_models
    if unreviewed_models:
        raise ValueError(
            "configured model is outside OPENROUTER_MODEL_ALLOWLIST: "
            + ", ".join(sorted(unreviewed_models))
        )
    broker = DisclosureBroker(
        policy=DisclosurePolicy(
            mode=ProtectionMode(settings.privacy_mode),
            receipt_path=settings.privacy_receipt_path,
            destinations={
                "openrouter": DestinationPolicy(
                    name="openrouter",
                    endpoint=settings.openrouter_base_url,
                    approved_models=frozenset(approved_models),
                    data_collection="deny",
                    zdr=True,
                    prompt_logging=False,
                    response_caching=False,
                )
            },
        )
    )
    engine = RoutingEngine(
        store=store,
        pool=pool,
        secret_resolver=resolver,
        adapters={
            "openrouter": DisclosureModelAdapter(
                adapter=OpenRouterAdapter(
                    base_url=settings.openrouter_base_url,
                    reviewed_providers=settings.reviewed_openrouter_providers,
                ),
                broker=broker,
            ),
        },
        max_targets=settings.llm_routing_max_targets,
        max_transient_retries=settings.llm_routing_max_transient_retries,
    )
    chat_model = RoutedChatModel(engine=engine, primary_model_resolver=_active_model)
    return RoutingRuntime(store, resolver, pool, broker, engine, chat_model)


@lru_cache(maxsize=1)
def get_routing_runtime() -> RoutingRuntime:
    return build_routing_runtime()


def get_routed_chat_model(model: str | None = None, reasoning_mode: Any = None) -> RoutedChatModel:
    routed = get_routing_runtime().chat_model
    updates: dict[str, Any] = {}
    if model is not None:
        updates["primary_model_resolver"] = lambda: model
    if reasoning_mode is not None:
        updates["reasoning_mode"] = reasoning_mode
    if not updates:
        return routed
    return routed.model_copy(update=updates, deep=False)


def reset_routing_runtime() -> None:
    get_routing_runtime.cache_clear()
