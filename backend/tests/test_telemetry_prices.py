import pytest

from agent.telemetry.prices import MODEL_PRICES, compute_cost_usd


def test_prices_dict_has_user_env_models():
    # Models referenced in the current .env
    for model in [
        "google/gemma-4-31b-it",
        "google/gemma-3-12b-it",
        "qwen/qwen3.5-35b-a3b",
    ]:
        assert model in MODEL_PRICES, f"missing price entry: {model}"


def test_prices_has_input_and_output_per_million():
    for model, price in MODEL_PRICES.items():
        assert "input" in price, f"{model} missing input price"
        assert "output" in price, f"{model} missing output price"
        assert price["input"] >= 0
        assert price["output"] >= 0


def test_compute_cost_zero_tokens():
    assert compute_cost_usd("google/gemma-4-31b-it", 0, 0) == 0.0


def test_compute_cost_known_model():
    cost = compute_cost_usd("google/gemma-4-31b-it", 1_000_000, 1_000_000)
    price = MODEL_PRICES["google/gemma-4-31b-it"]
    assert cost == pytest.approx(price["input"] + price["output"])


def test_compute_cost_unknown_model_returns_zero():
    assert compute_cost_usd("nonexistent/model", 1_000, 1_000) == 0.0
