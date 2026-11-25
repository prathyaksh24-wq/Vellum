"""OpenRouter's live model list replaces the hand-maintained catalog."""
from __future__ import annotations

from agent.llm import openrouter_catalog, providers


def _model(model_id: str, *, tools: bool = True, outputs=("text",), inputs=("text",), name: str | None = None) -> dict:
    return {
        "id": model_id,
        "name": name or model_id,
        "architecture": {"input_modalities": list(inputs), "output_modalities": list(outputs)},
        "supported_parameters": ["tools", "temperature"] if tools else ["temperature"],
        "top_provider": {"context_length": 200_000},
        "hugging_face_id": "",
    }


def test_only_tool_capable_zero_retention_text_models_are_listed() -> None:
    models = [
        _model("anthropic/claude-fable-5", name="Anthropic: Claude Fable 5", inputs=("text", "image")),
        _model("acme/no-tools", tools=False),
        _model("acme/no-zdr"),
        _model("acme/image-maker", outputs=("image",)),
        _model("anthropic/claude-fable-5:batch"),
    ]
    zdr = [{"model_id": "anthropic/claude-fable-5"}, {"model_id": "acme/no-tools"}, {"model_id": "acme/image-maker"}]

    entries = openrouter_catalog.build_entries(models, zdr, providers.ModelEntry)

    assert [entry.id for entry in entries] == ["anthropic/claude-fable-5"]
    assert entries[0].label == "Claude Fable 5"
    assert entries[0].provider == "anthropic"
    assert entries[0].context == 200_000
    assert "vision" in entries[0].capabilities


def test_picker_shows_the_live_list_and_the_privacy_broker_accepts_it(monkeypatch) -> None:
    live = openrouter_catalog.build_entries(
        [_model("newvendor/brand-new-model"), _model("anthropic/claude-fable-5")],
        [{"model_id": "newvendor/brand-new-model"}, {"model_id": "anthropic/claude-fable-5"}],
        providers.ModelEntry,
    )
    monkeypatch.setattr(openrouter_catalog, "fetch_live_catalog", lambda *_a, **_k: live)
    providers.get_provider_registry.cache_clear()
    try:
        visible = {entry.id for entry in providers.available_models()}
        assert {"newvendor/brand-new-model", "anthropic/claude-fable-5"} <= visible
        # The stale static catalog no longer pads the list once the live one is in.
        assert "minimax/minimax-m2.7" not in visible

        from agent.privacy.disclosure import DestinationPolicy, _live_approved

        policy = DestinationPolicy(
            name="openrouter", endpoint="https://openrouter.ai/api/v1",
            approved_models=frozenset({"google/test"}), data_collection="deny",
            zdr=True, prompt_logging=False, response_caching=False,
        )
        assert _live_approved(policy, "newvendor/brand-new-model")
        assert not _live_approved(policy, "acme/not-listed")
    finally:
        providers.get_provider_registry.cache_clear()


def test_static_catalog_is_kept_when_openrouter_is_unreachable(monkeypatch) -> None:
    import httpx

    def unreachable(*_a, **_k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(openrouter_catalog, "fetch_live_catalog", unreachable)
    visible = {entry.id for entry in providers.available_models()}
    assert "anthropic/claude-opus-4.7" in visible
