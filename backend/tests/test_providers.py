from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.config import Settings
from agent.llm.providers import (
    DEFAULT_TEMPERATURE,
    ModelEntry,
    ProviderGroup,
    ProviderRegistry,
    _CATALOG,
)


def test_catalog_has_expected_provider_groups() -> None:
    registry = ProviderRegistry()
    groups = {group.key for group in registry.list_groups()}
    assert groups == {"ollama", "google", "qwen", "minimax", "anthropic", "openai", "deepseek", "moonshot"}


def test_default_openrouter_allowlist_covers_curated_catalog() -> None:
    default = Settings.model_fields["openrouter_model_allowlist"].default
    allowlist = {item.strip() for item in str(default).split(",") if item.strip()}

    cloud_ids = {entry.id for entry in _CATALOG if entry.provider != "ollama"}
    assert cloud_ids.issubset(allowlist)


def test_available_models_hides_unapproved_openrouter_models(monkeypatch) -> None:
    from agent.llm import providers

    monkeypatch.setattr(
        providers,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="or-key",
            openai_api_key="sk-openai",
            reviewed_openrouter_models=("openai/gpt-5.6-sol",),
            primary_model="openai/gpt-5.6-sol",
        ),
    )

    local_model = ModelEntry(
        "ollama/test-model:latest",
        "Test Model",
        "ollama",
        32_768,
        "flagship",
        True,
        capabilities=("completion", "tools"),
        tool_calling_compatibility="compatible",
    )
    models = providers.available_models((local_model,))

    assert [item.id for item in models] == [
        "ollama/test-model:latest",
        "openai/gpt-5.6-sol",
    ]


def test_available_models_excludes_embedding_only_ollama_models(monkeypatch) -> None:
    from agent.llm import providers

    monkeypatch.setattr(
        providers,
        "get_settings",
        lambda: SimpleNamespace(
            openrouter_api_key="",
            openai_api_key="",
            reviewed_openrouter_models=(),
        ),
    )
    embedding = ModelEntry(
        "ollama/nomic-embed-text:latest",
        "nomic embed text (Local)",
        "ollama",
        2048,
        "flagship",
        True,
        capabilities=("embedding",),
        tool_calling_compatibility="unsupported",
    )
    chat = ModelEntry(
        "ollama/gemma4:12b",
        "Gemma 4 12B (Local)",
        "ollama",
        262_144,
        "flagship",
        True,
        capabilities=("completion", "tools"),
        tool_calling_compatibility="compatible",
    )

    assert [item.id for item in providers.available_models((embedding, chat))] == ["ollama/gemma4:12b"]


def test_local_group_default_excludes_embedding_only_model(monkeypatch) -> None:
    registry = ProviderRegistry()
    registry._local_models = (
        ModelEntry(
            "ollama/nomic-embed-text:latest",
            "nomic embed text (Local)",
            "ollama",
            2048,
            "flagship",
            True,
            capabilities=("embedding",),
            tool_calling_compatibility="unsupported",
        ),
        ModelEntry(
            "ollama/gemma4:12b",
            "Gemma 4 12B (Local)",
            "ollama",
            262_144,
            "flagship",
            True,
            capabilities=("completion", "tools"),
            tool_calling_compatibility="compatible",
        ),
    )
    monkeypatch.setattr(registry, "refresh_local_models", lambda **kwargs: registry._local_inventory)

    local_group = next(group for group in registry.list_groups() if group.key == "ollama")

    assert local_group.default_id == "ollama/gemma4:12b"


@pytest.mark.parametrize("local_installed", [False, True])
def test_each_group_exposes_only_installed_local_models(monkeypatch, local_installed) -> None:
    registry = ProviderRegistry()
    registry._local_models = (
        ModelEntry("ollama/test:latest", "Test Local", "ollama", 32768, "flagship", True),
    ) if local_installed else ()
    monkeypatch.setattr(registry, "refresh_local_models", lambda **kwargs: registry._local_inventory)
    for group in registry.list_groups():
        models = registry.list_models(group=group.key)
        if group.key == "ollama":
            assert [entry.id for entry in models] == (["ollama/test:latest"] if local_installed else [])
        else:
            assert models, f"no models in group {group.key}"


@pytest.mark.parametrize("local_installed", [False, True])
def test_each_group_default_id_resolves_or_is_empty_without_local_models(monkeypatch, local_installed) -> None:
    registry = ProviderRegistry()
    registry._local_models = (
        ModelEntry("ollama/test:latest", "Test Local", "ollama", 32768, "flagship", True),
    ) if local_installed else ()
    monkeypatch.setattr(registry, "refresh_local_models", lambda **kwargs: registry._local_inventory)
    catalog_ids = {entry.id for entry in registry.list_models()}
    for group in registry.list_groups():
        if group.key == "ollama" and not local_installed:
            assert group.default_id == ""
        else:
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


def test_legacy_picker_ids_resolve_to_current_catalog() -> None:
    registry = ProviderRegistry()

    assert registry.set_active("deepseek/deepseek-chat").id == "deepseek/deepseek-v4-pro"
    assert registry.set_active("deepseek/deepseek-chat-v3-0324").id == "deepseek/deepseek-v4-flash"
    assert registry.set_active("minimax/minimax-01").id == "minimax/minimax-m2.7"
    assert registry.set_active("google/gemma-3-27b-it").id == "google/gemma-4-31b-it"
    assert registry.set_active("google/gemma-2-27b-it").id == "google/gemma-4-26b-a4b-it"


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


def test_ollama_inventory_reads_context_and_tool_compatibility(monkeypatch) -> None:
    from agent.llm import providers

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    monkeypatch.setattr(
        providers.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(
            {"models": [{"name": "gemma4:12b", "details": {"parameter_size": "11.9B"}}]}
        ),
    )
    monkeypatch.setattr(
        providers.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {
                "capabilities": ["completion", "tools", "thinking"],
                "model_info": {"gemma4.context_length": 262144},
            }
        ),
    )

    inventory = providers.discover_ollama_models("http://127.0.0.1:11434/v1")

    assert inventory.reachable is True
    assert inventory.models[0].id == "ollama/gemma4:12b"
    assert inventory.models[0].context == providers.get_settings().ollama_context_length
    assert inventory.models[0].capabilities == ("completion", "thinking", "tools")
    assert inventory.models[0].tool_calling_compatibility == "compatible"


def test_ollama_inventory_marks_explicitly_unsupported_tool_calls(monkeypatch) -> None:
    from agent.llm import providers

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"capabilities": ["completion"]}

    monkeypatch.setattr(
        providers.httpx,
        "get",
        lambda *args, **kwargs: type("Tags", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"models": [{"name": "plain:30b", "details": {}}]},
        })(),
    )
    monkeypatch.setattr(providers.httpx, "post", lambda *args, **kwargs: FakeResponse())

    inventory = providers.discover_ollama_models("http://127.0.0.1:11434")

    assert inventory.models[0].tool_calling_compatibility == "unsupported"


def test_provider_group_dataclass_is_frozen() -> None:
    group = ProviderGroup("x", "x", "x/y")
    with pytest.raises(Exception):
        group.key = "y"  # type: ignore[misc]
