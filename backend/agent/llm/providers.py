"""Curated local and cloud model catalog.

The registry is process-local state. Defaults come from the env-loaded settings
on first access; subsequent set_active / set_temperature calls only persist
in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import re
import threading
import time
from typing import Any, Literal

import httpx

from agent.config import get_settings

_REQUEST_MODEL: ContextVar[str | None] = ContextVar("vellum_request_model", default=None)

@contextmanager
def request_model_scope(model_id: str | None):
    """Let specialist/default factories inherit this turn's model without global mutation."""
    token = _REQUEST_MODEL.set(model_id)
    try:
        yield
    finally:
        _REQUEST_MODEL.reset(token)


@dataclass(frozen=True)
class ModelEntry:
    id: str
    label: str
    provider: str
    context: int
    tier: Literal["flagship", "fast"]
    open_weights: bool
    capabilities: tuple[str, ...] = ()
    tool_calling_compatibility: Literal["compatible", "unsupported", "unknown"] = "unknown"


@dataclass(frozen=True)
class ProviderGroup:
    key: str
    label: str
    default_id: str


@dataclass(frozen=True)
class LocalModelInventory:
    reachable: bool
    models: tuple[ModelEntry, ...]
    error: str | None = None


_CATALOG: tuple[ModelEntry, ...] = (
    # ---- Open-weights models routed through OpenRouter ----
    ModelEntry("google/gemma-4-26b-a4b-it", "Gemma 4 26B A4B", "google", 262_144, "fast", True),
    ModelEntry("google/gemma-4-31b-it", "Gemma 4 31B", "google", 262_144, "flagship", True),
    ModelEntry("qwen/qwen3.5-35b-a3b", "Qwen 3.5 35B A3B", "qwen", 262_144, "flagship", True),
    ModelEntry("minimax/minimax-m2.7", "MiniMax M2.7", "minimax", 204_800, "flagship", True),
    # ---- Cloud (closed-weights, OpenRouter-routed) ----
    ModelEntry("anthropic/claude-opus-5", "Claude Opus 5", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("anthropic/claude-opus-5-fast", "Claude Opus 5 (Fast)", "anthropic", 1_000_000, "fast", False),
    ModelEntry("anthropic/claude-opus-4.7", "Claude Opus 4.7", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("anthropic/claude-opus-4.6", "Claude Opus 4.6", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("openai/gpt-5.6-sol-pro", "GPT-5.6 Sol Pro", "openai", 1_050_000, "flagship", False),
    ModelEntry("openai/gpt-5.6-sol", "GPT-5.6 Sol", "openai", 1_050_000, "flagship", False),
    ModelEntry("openai/gpt-5.6-terra-pro", "GPT-5.6 Terra Pro", "openai", 1_050_000, "flagship", False),
    ModelEntry("openai/gpt-5.6-terra", "GPT-5.6 Terra", "openai", 1_050_000, "flagship", False),
    ModelEntry("openai/gpt-5.6-luna-pro", "GPT-5.6 Luna Pro", "openai", 1_050_000, "fast", False),
    ModelEntry("openai/gpt-5.6-luna", "GPT-5.6 Luna", "openai", 1_050_000, "fast", False),
    ModelEntry("openai/gpt-5.5", "GPT 5.5", "openai", 1_050_000, "flagship", False),
    ModelEntry("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "deepseek", 1_048_576, "flagship", False),
    ModelEntry("deepseek/deepseek-v4-flash-0731", "DeepSeek V4 Flash 0731", "deepseek", 1_048_576, "fast", False),
    ModelEntry("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek", 1_048_576, "fast", False),
    ModelEntry("google/gemini-3-flash-preview", "Gemini 3 Flash (preview)", "google", 1_048_576, "fast", False),
    ModelEntry("moonshotai/kimi-k3", "Kimi K3", "moonshot", 1_048_576, "flagship", False),
    ModelEntry("moonshotai/kimi-k2.6", "Kimi K2.6", "moonshot", 262_144, "flagship", False),
)

_GROUPS: tuple[ProviderGroup, ...] = (
    ProviderGroup("ollama", "Local (Ollama)", ""),
    ProviderGroup("google", "Google", "google/gemma-4-31b-it"),
    ProviderGroup("qwen", "Qwen", "qwen/qwen3.5-35b-a3b"),
    ProviderGroup("minimax", "MiniMax", "minimax/minimax-m2.7"),
    ProviderGroup("anthropic", "Anthropic", "anthropic/claude-opus-5"),
    ProviderGroup("openai", "OpenAI", "openai/gpt-5.6-sol"),
    ProviderGroup("deepseek", "DeepSeek", "deepseek/deepseek-v4-flash-0731"),
    ProviderGroup("moonshot", "MoonshotAI", "moonshotai/kimi-k3"),
)

_MODEL_ALIASES: dict[str, str] = {
    # Legacy picker IDs from older static uploads. Keep accepting them at the
    # backend boundary so stale clients do not break the active model switch.
    "deepseek/deepseek-chat": "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-chat-v3-0324": "deepseek/deepseek-v4-flash",
    "minimax/minimax-01": "minimax/minimax-m2.7",
    "google/gemma-3-27b-it": "google/gemma-4-31b-it",
    "google/gemma-2-27b-it": "google/gemma-4-26b-a4b-it",
}

DEFAULT_TEMPERATURE = 0.3
OLLAMA_DISCOVERY_TTL_SECONDS = 5.0
OLLAMA_DISCOVERY_TIMEOUT_SECONDS = 2.0


def _ollama_tags_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.casefold().endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/api/tags"


def _humanize_ollama_model(name: str, details: dict[str, Any]) -> str:
    base, _, tag = name.partition(":")
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", re.sub(r"[-_]+", " ", base)).strip()
    tokens: list[str] = []
    for token in spaced.split():
        lowered = token.casefold()
        if lowered in {"qwen", "gemma", "llama", "mistral", "phi", "deepseek"}:
            tokens.append(lowered.capitalize())
        elif lowered in {"gpt", "oss", "vl"}:
            tokens.append(lowered.upper())
        else:
            tokens.append(token)
    label = " ".join(tokens) or base
    variant = tag.strip()
    if not variant or variant.casefold() == "latest":
        variant = str(details.get("parameter_size") or "").strip()
    if variant:
        variant = re.sub(r"(?i)(\d+(?:\.\d+)?)b\b", lambda match: f"{match.group(1)}B", variant)
        label = f"{label} {variant}"
    return f"{label} (Local)"


def _show_ollama_model(base_url: str, name: str) -> tuple[int | None, tuple[str, ...], str]:
    """Read model capabilities without loading weights into memory."""
    normalized = base_url.rstrip("/")
    if normalized.casefold().endswith("/v1"):
        normalized = normalized[:-3]
    try:
        response = httpx.post(
            f"{normalized}/api/show",
            json={"model": name},
            headers={"Accept": "application/json"},
            timeout=OLLAMA_DISCOVERY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None, (), "unknown"
    if not isinstance(payload, dict):
        return None, (), "unknown"

    raw_capabilities = payload.get("capabilities")
    if isinstance(raw_capabilities, list):
        capabilities = tuple(sorted({str(item).strip().casefold() for item in raw_capabilities if str(item).strip()}))
        compatibility = "compatible" if "tools" in capabilities else "unsupported"
    else:
        capabilities = ()
        compatibility = "unknown"

    context_length = None
    model_info = payload.get("model_info")
    if isinstance(model_info, dict):
        values = [
            value
            for key, value in model_info.items()
            if str(key).casefold().endswith(".context_length")
        ]
        for value in values:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                context_length = parsed
                break
    if context_length is not None:
        context_length = min(context_length, get_settings().ollama_context_length)
    return context_length, capabilities, compatibility


def discover_ollama_models(base_url: str) -> LocalModelInventory:
    """Read Ollama's installed model inventory without loading any model."""
    try:
        response = httpx.get(
            _ollama_tags_url(base_url),
            headers={"Accept": "application/json"},
            timeout=OLLAMA_DISCOVERY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        raw_models = payload.get("models", []) if isinstance(payload, dict) else []
        if not isinstance(raw_models, list):
            raise ValueError("Ollama returned an invalid model inventory")
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return LocalModelInventory(
            reachable=False,
            models=(),
            error=type(exc).__name__,
        )

    valid_models: list[tuple[str, str, dict[str, Any], int]] = []
    seen: set[str] = set()
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("model") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
        raw_context = raw.get("context_length") or details.get("context_length")
        try:
            context = max(1, int(raw_context))
        except (TypeError, ValueError):
            context = 32_768
        valid_models.append((name, f"ollama/{name}", details, context))

    if valid_models:
        with ThreadPoolExecutor(max_workers=min(6, len(valid_models))) as pool:
            model_details = list(pool.map(lambda item: _show_ollama_model(base_url, item[0]), valid_models))
    else:
        model_details = []

    discovered: list[ModelEntry] = []
    for (name, model_id, details, fallback_context), (context_length, capabilities, compatibility) in zip(
        valid_models, model_details
    ):
        discovered.append(
            ModelEntry(
                id=model_id,
                label=_humanize_ollama_model(name, details),
                provider="ollama",
                context=context_length or fallback_context,
                tier="flagship",
                open_weights=True,
                capabilities=capabilities,
                tool_calling_compatibility=compatibility,
            )
        )
    return LocalModelInventory(reachable=True, models=tuple(discovered))


class ProviderRegistry:
    def __init__(self) -> None:
        settings = get_settings()
        self._local_models: tuple[ModelEntry, ...] = ()
        self._local_inventory = LocalModelInventory(
            reachable=False,
            models=(),
            error="not_checked",
        )
        self._local_checked_at = 0.0
        self._has_successful_local_refresh = False
        self._lock = threading.RLock()
        initial = self._find_by_id(settings.primary_model)
        if initial is None:
            initial = ModelEntry(
                id=settings.primary_model,
                label=settings.primary_model.split("/")[-1],
                provider=settings.primary_model.split("/")[0] if "/" in settings.primary_model else "custom",
                context=128_000,
                tier="flagship",
                open_weights=True,
            )
        self._active: ModelEntry = initial
        self._temperature: float = DEFAULT_TEMPERATURE

    def _catalog(self) -> tuple[ModelEntry, ...]:
        return (*self._local_models, *_CATALOG)

    def _find_by_id(self, model_id: str) -> ModelEntry | None:
        model_id = canonical_model_id(model_id)
        for entry in self._catalog():
            if entry.id == model_id:
                return entry
        return None

    def refresh_local_models(self, *, force: bool = False) -> LocalModelInventory:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._local_checked_at < OLLAMA_DISCOVERY_TTL_SECONDS:
                return self._local_inventory

        inventory = discover_ollama_models(get_settings().ollama_base_url)
        with self._lock:
            self._local_checked_at = time.monotonic()
            if inventory.reachable:
                self._local_models = inventory.models
                self._local_inventory = inventory
                self._has_successful_local_refresh = True
                self._reconcile_active_locked()
            else:
                # A transient Ollama outage must not look like the user deleted
                # every model. Retain the last successful snapshot until Ollama
                # answers again.
                self._local_inventory = LocalModelInventory(
                    reachable=False,
                    models=self._local_models,
                    error=inventory.error,
                )
                if not self._has_successful_local_refresh:
                    self._reconcile_active_locked()
            return self._local_inventory

    def local_inventory(self) -> LocalModelInventory:
        return self.refresh_local_models()

    def _reconcile_active_locked(self) -> None:
        visible = available_models(self._local_models)
        by_id = {entry.id: entry for entry in visible}
        current = by_id.get(self._active.id)
        if current is not None:
            self._active = current
            return

        settings = get_settings()
        local = [entry for entry in visible if entry.provider == "ollama"]
        preferred_cloud_ids = (
            settings.fallback_model,
            settings.fast_model,
            settings.cloud_escalation_model,
        )
        replacement = local[0] if local else None
        if replacement is None:
            for model_id in preferred_cloud_ids:
                replacement = by_id.get(canonical_model_id(model_id))
                if replacement is not None:
                    break
        if replacement is None and visible:
            replacement = visible[0]
        if replacement is not None:
            self._active = replacement

    def list_groups(self) -> list[ProviderGroup]:
        self.refresh_local_models()
        local_chat_models = [entry for entry in self._local_models if _is_chat_model(entry)]
        local_default = local_chat_models[0].id if local_chat_models else ""
        return [
            replace(group, default_id=local_default) if group.key == "ollama" else group
            for group in _GROUPS
        ]

    def list_models(self, group: str | None = None) -> list[ModelEntry]:
        self.refresh_local_models()
        models = available_models(self._local_models)
        if group is None:
            return models
        return [entry for entry in models if entry.provider == group]

    def find_group(self, key: str) -> ProviderGroup | None:
        normalized = key.strip().casefold()
        for group in self.list_groups():
            if group.key.casefold() == normalized:
                return group
        return None

    def resolve(self, query: str) -> ModelEntry | None:
        normalized = query.strip().casefold()
        if not normalized:
            return None
        self.refresh_local_models()
        alias = _MODEL_ALIASES.get(normalized)
        if alias is not None:
            return self._find_by_id(alias)
        # 1. Exact id match
        catalog = self._catalog()
        for entry in catalog:
            if entry.id.casefold() == normalized:
                return entry
        # 2. Exact label match
        for entry in catalog:
            if entry.label.casefold() == normalized:
                return entry
        # 3. Label prefix
        for entry in catalog:
            if entry.label.casefold().startswith(normalized):
                return entry
        # 4. Id substring
        for entry in catalog:
            if normalized in entry.id.casefold():
                return entry
        # 5. Label substring
        for entry in catalog:
            if normalized in entry.label.casefold():
                return entry
        return None

    def set_active(self, model_id: str) -> ModelEntry:
        if canonical_model_id(model_id).casefold().startswith("ollama/"):
            self.refresh_local_models(force=True)
        entry = self._find_by_id(canonical_model_id(model_id))
        if entry is None:
            resolved = self.resolve(model_id)
            if resolved is None:
                raise ValueError(f"Unknown model: {model_id}")
            entry = resolved
        available_ids = {model.id for model in available_models(self._local_models)}
        if entry.id not in available_ids:
            raise ValueError(f"Model is not available: {model_id}")
        self._active = entry
        return entry

    def set_temperature(self, value: float) -> None:
        if not 0.0 <= value <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        self._temperature = float(value)

    def current(self) -> tuple[ModelEntry, float]:
        return self._active, self._temperature

    def current_model(self) -> ModelEntry:
        requested = _REQUEST_MODEL.get()
        return (self.resolve(requested) if requested else None) or self._active

    def current_available_model(self) -> ModelEntry | None:
        self.refresh_local_models()
        available = {entry.id: entry for entry in available_models(self._local_models)}
        return available.get(self._active.id)

    def is_available(self, model_id: str) -> bool:
        self.refresh_local_models()
        canonical = canonical_model_id(model_id)
        return any(entry.id == canonical for entry in available_models(self._local_models))

    def current_temperature(self) -> float:
        return self._temperature

    def reset_temperature(self) -> None:
        self._temperature = DEFAULT_TEMPERATURE

    def replace_active(self, **changes) -> ModelEntry:
        """Test/util helper to swap fields on the active entry."""
        self._active = replace(self._active, **changes)
        return self._active


@lru_cache(maxsize=1)
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry()


def canonical_model_id(model_id: str) -> str:
    normalized = model_id.strip()
    return _MODEL_ALIASES.get(normalized.casefold(), normalized)


def configured_provider_keys() -> dict[str, bool]:
    settings = get_settings()
    return {
        "openrouter": bool(settings.openrouter_api_key),
        "openai": bool(settings.openai_api_key),
    }


def available_models(local_models: tuple[ModelEntry, ...] = ()) -> list[ModelEntry]:
    """Return models that have a usable, approved route for this installation.

    When OpenRouter is configured, the disclosure broker is the authority for
    every catalog model, so the picker must not expose an ID outside its model
    allowlist. The native OpenAI-key branch is retained for legacy settings
    screens; chat routing still requires an explicitly configured adapter.
    """
    settings = get_settings()
    has_openrouter = bool(settings.openrouter_api_key)
    has_openai = bool(settings.openai_api_key)
    approved = {
        value.strip()
        for value in getattr(settings, "reviewed_openrouter_models", ())
        if value and value.strip()
    }
    visible: list[ModelEntry] = [entry for entry in local_models if _is_chat_model(entry)]
    for entry in _CATALOG:
        if has_openrouter:
            if entry.id in approved:
                visible.append(entry)
        elif entry.provider == "openai" and has_openai:
            visible.append(entry)
    return visible


def _is_chat_model(entry: ModelEntry) -> bool:
    """Keep utility models such as embedders out of chat selection."""
    capabilities = {capability.casefold() for capability in entry.capabilities}
    return not capabilities or "completion" in capabilities
