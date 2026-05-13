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


_CATALOG: tuple[ModelEntry, ...] = (
    # anthropic
    ModelEntry("anthropic/claude-opus-4.7", "claude opus 4.7", "anthropic", 200_000, "flagship", False),
    ModelEntry("anthropic/claude-haiku-4.5", "claude haiku 4.5", "anthropic", 200_000, "fast", False),
    # openai
    ModelEntry("openai/gpt-4o", "gpt-4o", "openai", 128_000, "flagship", False),
    ModelEntry("openai/gpt-4o-mini", "gpt-4o-mini", "openai", 128_000, "fast", False),
    # google
    ModelEntry("google/gemini-2.5-pro", "gemini 2.5 pro", "google", 2_000_000, "flagship", False),
    ModelEntry("google/gemma-4-31b-it", "gemma 4 31b", "google", 128_000, "fast", True),
    # xai
    ModelEntry("x-ai/grok-4", "grok 4", "xai", 256_000, "flagship", False),
    ModelEntry("x-ai/grok-4-fast", "grok 4 fast", "xai", 256_000, "fast", False),
    # deepseek
    ModelEntry("deepseek/deepseek-v4", "deepseek v4", "deepseek", 128_000, "flagship", True),
    ModelEntry("deepseek/deepseek-r1", "deepseek r1", "deepseek", 128_000, "fast", True),
    # meta
    ModelEntry("meta-llama/llama-3.3-70b-instruct", "llama 3.3 70b", "meta", 128_000, "flagship", True),
    ModelEntry("meta-llama/llama-3.2-3b-instruct", "llama 3.2 3b", "meta", 128_000, "fast", True),
)

_GROUPS: tuple[ProviderGroup, ...] = (
    ProviderGroup("anthropic", "anthropic", "anthropic/claude-opus-4.7"),
    ProviderGroup("openai", "openai", "openai/gpt-4o"),
    ProviderGroup("google", "google", "google/gemini-2.5-pro"),
    ProviderGroup("xai", "xai", "x-ai/grok-4"),
    ProviderGroup("deepseek", "deepseek", "deepseek/deepseek-v4"),
    ProviderGroup("meta", "meta", "meta-llama/llama-3.3-70b-instruct"),
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
        if group is None:
            return list(_CATALOG)
        return [entry for entry in _CATALOG if entry.provider == group]

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
