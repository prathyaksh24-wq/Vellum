"""Which LLM the memory engines use, derived from the user's own setup.

Every Vellum user picks a model source at onboarding: a local model through
Ollama, OpenRouter, free Groq, or their own Claude/OpenAI/Gemini key. The
memory engines (Hindsight, Honcho) need an LLM to extract facts, so they use
the same source:

- Local users reuse their chat model. A second local model would not fit
  next to it on an 8 GB machine.
- Cloud users get a cheap, fast model on the same provider; engine extraction
  runs on every saved turn, so a flagship model would be costly.
- OpenRouter requests carry ``data_collection: deny``, matching Vellum's chat.

``MEMORY_ENGINE_PROVIDER`` / ``MEMORY_ENGINE_MODEL`` override the choice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

OLLAMA_OPENAI_BASE = "http://127.0.0.1:11434/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
GROQ_OPENAI_BASE = "https://api.groq.com/openai/v1"
OPENROUTER_PRIVACY = {"provider": {"data_collection": "deny"}}

# Cheap, fast extraction models per cloud provider (all support JSON / tools).
DEFAULT_CLOUD_MODELS = {
    "openrouter": "google/gemma-3-12b-it",
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-5.4-mini",
    "anthropic": "claude-haiku-4-5",
    "google": "gemini-2.5-flash",
}
SUPPORTED_PROVIDERS = ("ollama", *DEFAULT_CLOUD_MODELS)


@dataclass(frozen=True)
class EngineLLM:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.model) and (self.provider == "ollama" or bool(self.api_key))


def memory_engine_llm(settings: Any = None, registry: Any = None) -> EngineLLM:
    """Resolve the memory engines' LLM from settings and the active model."""
    if settings is None:
        from agent.config import get_settings

        settings = get_settings()
    if registry is None:
        from agent.llm.providers import get_provider_registry

        registry = get_provider_registry()

    override = str(getattr(settings, "memory_engine_provider", "") or "").strip().casefold()
    model_override = str(getattr(settings, "memory_engine_model", "") or "").strip()
    provider = override or _provider_from_registry(registry, settings)
    if provider not in SUPPORTED_PROVIDERS:
        return EngineLLM(provider=provider, model="", reason=f"{provider} is not supported for memory engines")

    if provider == "ollama":
        active = str(getattr(registry.current_model(), "id", "") or "")
        model = model_override or (active.split("/", 1)[1] if active.startswith("ollama/") else "")
        model = model or str(getattr(settings, "memory_llm_model", "") or "")
        base = str(getattr(settings, "ollama_base_url", "") or "http://127.0.0.1:11434").rstrip("/") + "/v1"
        return EngineLLM(provider="ollama", model=model, base_url=base,
                         reason="" if model else "No local model is installed yet")

    key = _secret(getattr(settings, f"{provider}_api_key", None))
    model = model_override or DEFAULT_CLOUD_MODELS[provider]
    base = {"openrouter": OPENROUTER_BASE, "groq": GROQ_OPENAI_BASE}.get(provider, "")
    extra = dict(OPENROUTER_PRIVACY) if provider == "openrouter" else {}
    return EngineLLM(provider=provider, model=model, api_key=key, base_url=base, extra_body=extra,
                     reason="" if key else f"Add a {provider} API key to turn on memory engines")


def _provider_from_registry(registry: Any, settings: Any) -> str:
    try:
        picked = str(registry.picker_provider() or "")
    except Exception:  # noqa: BLE001 - a registry without picker support
        picked = ""
    if picked:
        return picked
    active = str(getattr(registry.current_model(), "id", "") or "")
    if active.startswith("ollama/"):
        return "ollama"
    for provider in ("openrouter", "groq", "anthropic", "openai", "google"):
        if _secret(getattr(settings, f"{provider}_api_key", None)):
            return provider
    return "ollama"


def _secret(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return str(getter() if callable(getter) else value).strip()


# -- per-engine environment ----------------------------------------------------

_HINDSIGHT_PROVIDER = {"ollama": "ollama", "openrouter": "openrouter", "groq": "groq",
                       "openai": "openai", "anthropic": "anthropic", "google": "gemini"}


def hindsight_llm_env(llm: EngineLLM) -> dict[str, str]:
    env = {
        "HINDSIGHT_API_LLM_PROVIDER": _HINDSIGHT_PROVIDER[llm.provider],
        "HINDSIGHT_API_LLM_MODEL": llm.model,
    }
    if llm.api_key:
        env["HINDSIGHT_API_LLM_API_KEY"] = llm.api_key
    if llm.base_url:
        env["HINDSIGHT_API_LLM_BASE_URL"] = llm.base_url
    if llm.extra_body:
        env["HINDSIGHT_API_LLM_EXTRA_BODY"] = json.dumps(llm.extra_body)
    if llm.provider == "groq":
        # Hindsight defaults to service_tier=auto, which Groq's free plan rejects.
        env["HINDSIGHT_API_LLM_GROQ_SERVICE_TIER"] = "on_demand"
    if llm.provider == "ollama":
        # Local models cannot produce Hindsight's default 65k-token extraction.
        env["HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS"] = "16000"
    return env


# Same feature keys as the Docker setup in docker-compose.yml (x-honcho-environment).
# Note the double underscore before MODEL_CONFIG for dialectic levels.
_HONCHO_PREFIXES = (
    "DERIVER_MODEL_CONFIG__",
    "SUMMARY_MODEL_CONFIG__",
    # Unconfigured modules fall back to OpenAI with no key, so set them all.
    "PEER_CARD_MODEL_CONFIG__",
    "DREAM_DEDUCTION_MODEL_CONFIG__",
    "DREAM_INDUCTION_MODEL_CONFIG__",
    *(f"DIALECTIC_LEVELS__{level}__MODEL_CONFIG__" for level in ("minimal", "low", "medium", "high", "max")),
)


def honcho_llm_env(llm: EngineLLM) -> dict[str, str]:
    """Honcho transports: openai (also any OpenAI-compatible URL), anthropic, gemini."""
    transport = {"anthropic": "anthropic", "google": "gemini"}.get(llm.provider, "openai")
    env: dict[str, str] = {}
    if transport == "anthropic":
        env["LLM_ANTHROPIC_API_KEY"] = llm.api_key
    elif transport == "gemini":
        env["LLM_GEMINI_API_KEY"] = llm.api_key
    else:
        env["LLM_OPENAI_API_KEY"] = llm.api_key or "ollama-local"
    extra = dict(llm.extra_body)
    if llm.provider == "ollama":
        extra["reasoning_effort"] = "none"  # as in the Docker setup; thinking stalls small models
    for prefix in _HONCHO_PREFIXES:
        env[prefix + "TRANSPORT"] = transport
        env[prefix + "MODEL"] = llm.model
        if transport == "openai" and llm.base_url:
            env[prefix + "OVERRIDES__BASE_URL"] = llm.base_url
        if extra:
            env[prefix + "OVERRIDES__PROVIDER_PARAMS"] = json.dumps({"extra_body": extra})
    return env
