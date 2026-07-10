"""Curated multi-provider catalog routed through OpenRouter.

The registry is process-local state. Defaults come from the env-loaded settings
on first access; subsequent set_active / set_temperature calls only persist
in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

from agent.config import get_settings


@dataclass(frozen=True)
class ModelEntry:
    id: str
    label: str
    provider: str
    context: int
    tier: Literal["flagship", "fast"]
    open_weights: bool


@dataclass(frozen=True)
class ProviderGroup:
    key: str
    label: str
    default_id: str


# All IDs below verified against https://openrouter.ai/api/v1/models on 16/05/2026.
# Curated to the models the user listed; remove entries here to hide them from
# the picker, add entries (with valid OpenRouter IDs) to expose new ones.
_CATALOG: tuple[ModelEntry, ...] = (
    # ---- Local (open-weights, routed via OpenRouter for ZDR privacy) ----
    ModelEntry("google/gemma-4-26b-a4b-it", "Gemma 4 26B A4B", "google", 262_144, "fast", True),
    ModelEntry("google/gemma-4-31b-it", "Gemma 4 31B", "google", 262_144, "flagship", True),
    ModelEntry("qwen/qwen3.5-35b-a3b", "Qwen 3.5 35B A3B", "qwen", 262_144, "flagship", True),
    ModelEntry("minimax/minimax-m2.7", "MiniMax M2.7", "minimax", 204_800, "flagship", True),
    # ---- Cloud (closed-weights, OpenRouter-routed) ----
    ModelEntry("anthropic/claude-opus-4.7", "Claude Opus 4.7", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("anthropic/claude-opus-4.6", "Claude Opus 4.6", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "anthropic", 1_000_000, "flagship", False),
    ModelEntry("openai/gpt-5.5", "GPT 5.5", "openai", 1_050_000, "flagship", False),
    ModelEntry("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "deepseek", 1_048_576, "flagship", False),
    ModelEntry("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek", 1_048_576, "fast", False),
    ModelEntry("google/gemini-3-flash-preview", "Gemini 3 Flash (preview)", "google", 1_048_576, "fast", False),
    ModelEntry("moonshotai/kimi-k2.6", "Kimi K2.6", "moonshot", 262_144, "flagship", False),
)

_GROUPS: tuple[ProviderGroup, ...] = (
    ProviderGroup("google", "Google", "google/gemma-4-31b-it"),
    ProviderGroup("qwen", "Qwen", "qwen/qwen3.5-35b-a3b"),
    ProviderGroup("minimax", "MiniMax", "minimax/minimax-m2.7"),
    ProviderGroup("anthropic", "Anthropic", "anthropic/claude-opus-4.7"),
    ProviderGroup("openai", "OpenAI", "openai/gpt-5.5"),
    ProviderGroup("deepseek", "DeepSeek", "deepseek/deepseek-v4-pro"),
    ProviderGroup("moonshot", "MoonshotAI", "moonshotai/kimi-k2.6"),
)

DEFAULT_TEMPERATURE = 0.3


class ProviderRegistry:
    def __init__(self) -> None:
        settings = get_settings()
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

    @staticmethod
    def _find_by_id(model_id: str) -> ModelEntry | None:
        for entry in _CATALOG:
            if entry.id == model_id:
                return entry
        return None

    def list_groups(self) -> list[ProviderGroup]:
        return list(_GROUPS)

    def list_models(self, group: str | None = None) -> list[ModelEntry]:
        models = available_models()
        if group is None:
            return models
        return [entry for entry in models if entry.provider == group]

    def find_group(self, key: str) -> ProviderGroup | None:
        normalized = key.strip().casefold()
        for group in _GROUPS:
            if group.key.casefold() == normalized:
                return group
        return None

    def resolve(self, query: str) -> ModelEntry | None:
        normalized = query.strip().casefold()
        if not normalized:
            return None
        # 1. Exact id match
        for entry in _CATALOG:
            if entry.id.casefold() == normalized:
                return entry
        # 2. Exact label match
        for entry in _CATALOG:
            if entry.label.casefold() == normalized:
                return entry
        # 3. Label prefix
        for entry in _CATALOG:
            if entry.label.casefold().startswith(normalized):
                return entry
        # 4. Id substring
        for entry in _CATALOG:
            if normalized in entry.id.casefold():
                return entry
        # 5. Label substring
        for entry in _CATALOG:
            if normalized in entry.label.casefold():
                return entry
        return None

    def set_active(self, model_id: str) -> ModelEntry:
        entry = self._find_by_id(model_id)
        if entry is None:
            resolved = self.resolve(model_id)
            if resolved is None:
                raise ValueError(f"Unknown model: {model_id}")
            entry = resolved
        self._active = entry
        return entry

    def set_temperature(self, value: float) -> None:
        if not 0.0 <= value <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")
        self._temperature = float(value)

    def current(self) -> tuple[ModelEntry, float]:
        return self._active, self._temperature

    def current_model(self) -> ModelEntry:
        return self._active

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


def configured_provider_keys() -> dict[str, bool]:
    settings = get_settings()
    return {
        "openrouter": bool(settings.openrouter_api_key),
        "openai": bool(settings.openai_api_key),
    }


def available_models() -> list[ModelEntry]:
    settings = get_settings()
    has_openrouter = bool(settings.openrouter_api_key)
    has_openai = bool(settings.openai_api_key)
    visible: list[ModelEntry] = []
    for entry in _CATALOG:
        if entry.open_weights:
            visible.append(entry)
        elif has_openrouter:
            visible.append(entry)
        elif entry.provider == "openai" and has_openai:
            visible.append(entry)
    return visible
