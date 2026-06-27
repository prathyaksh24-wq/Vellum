from __future__ import annotations

import pytest

from agent.llm.providers import (
    DEFAULT_TEMPERATURE,
    ModelEntry,
    ProviderGroup,
    ProviderRegistry,
)


def test_catalog_has_expected_provider_groups() -> None:
    registry = ProviderRegistry()
    groups = {group.key for group in registry.list_groups()}
    assert groups == {"google", "qwen", "minimax", "anthropic", "openai", "deepseek", "moonshot"}


def test_each_group_has_at_least_one_model() -> None:
    registry = ProviderRegistry()
    for group in registry.list_groups():
        assert registry.list_models(group=group.key), f"no models in group {group.key}"


def test_each_group_default_id_resolves_to_a_real_model() -> None:
    registry = ProviderRegistry()
    catalog_ids = {entry.id for entry in registry.list_models()}
    for group in registry.list_groups():
        assert group.default_id in catalog_ids


def test_resolve_exact_id_wins() -> None:
    registry = ProviderRegistry()
    entry = registry.resolve("anthropic/claude-opus-4.7")
    assert entry is not None
    assert entry.id == "anthropic/claude-opus-4.7"


def test_resolve_label_prefix_over_substring() -> None:
    registry = ProviderRegistry()
    # "Claude" is a prefix of "Claude Opus 4.7" / "Claude Sonnet 4.5" labels
    # and a substring of the "anthropic/claude-*" ids — prefix should win.
    entry = registry.resolve("Claude")
    assert entry is not None
    assert entry.label.startswith("Claude")


def test_resolve_returns_none_for_unknown() -> None:
    registry = ProviderRegistry()
    assert registry.resolve("nonexistent-model-xyz") is None


def test_set_active_by_known_id() -> None:
    registry = ProviderRegistry()
    entry = registry.set_active("openai/gpt-5.5")
    assert entry.id == "openai/gpt-5.5"
    assert registry.current_model().id == "openai/gpt-5.5"


def test_set_active_by_label_via_resolve() -> None:
    registry = ProviderRegistry()
    entry = registry.set_active("DeepSeek V4 Flash")
    assert entry.id == "deepseek/deepseek-v4-flash"


def test_set_active_unknown_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ValueError):
        registry.set_active("nope/nothing")


def test_set_temperature_within_bounds() -> None:
    registry = ProviderRegistry()
    registry.set_temperature(0.0)
    assert registry.current_temperature() == 0.0
    registry.set_temperature(2.0)
    assert registry.current_temperature() == 2.0
    registry.set_temperature(0.7)
    assert registry.current_temperature() == 0.7


def test_set_temperature_out_of_bounds_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ValueError):
        registry.set_temperature(-0.1)
    with pytest.raises(ValueError):
        registry.set_temperature(2.5)


def test_initial_state_matches_settings_default() -> None:
    registry = ProviderRegistry()
    model, temp = registry.current()
    assert temp == DEFAULT_TEMPERATURE
    assert isinstance(model, ModelEntry)
    # The default settings.primary_model gets mirrored as a synthetic entry if not in catalog.
    assert model.id  # non-empty


def test_find_group_case_insensitive() -> None:
    registry = ProviderRegistry()
    group = registry.find_group("ANTHROPIC")
    assert group is not None
    assert group.key == "anthropic"


def test_find_group_returns_none_for_unknown() -> None:
    registry = ProviderRegistry()
    assert registry.find_group("nintendo") is None


def test_open_weights_flag_is_set_per_entry() -> None:
    registry = ProviderRegistry()
    by_id = {entry.id: entry for entry in registry.list_models()}
    # Closed-weights: anthropic, openai, deepseek-via-cloud, gemini, kimi
    assert by_id["anthropic/claude-opus-4.7"].open_weights is False
    assert by_id["openai/gpt-5.5"].open_weights is False
    assert by_id["deepseek/deepseek-v4-pro"].open_weights is False
    # Open-weights: gemma, qwen, minimax
    assert by_id["google/gemma-4-31b-it"].open_weights is True
    assert by_id["qwen/qwen3.5-35b-a3b"].open_weights is True
    assert by_id["minimax/minimax-m2.7"].open_weights is True


def test_provider_group_dataclass_is_frozen() -> None:
    group = ProviderGroup("x", "x", "x/y")
    with pytest.raises(Exception):
        group.key = "y"  # type: ignore[misc]
