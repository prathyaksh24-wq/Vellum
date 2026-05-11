from agent.tui.cli.commands.models import KNOWN_MODELS
from agent.telemetry.prices import MODEL_PRICES


def test_known_models_shadows_prices():
    """Every model in the picker must have a price entry."""
    for entry in KNOWN_MODELS:
        assert entry["id"] in MODEL_PRICES, f"{entry['id']} missing from MODEL_PRICES"


def test_known_models_have_required_fields():
    for entry in KNOWN_MODELS:
        assert "id" in entry
        assert "hint" in entry
        assert "/" in entry["id"]


def test_known_models_includes_user_default():
    ids = {e["id"] for e in KNOWN_MODELS}
    assert "google/gemma-4-31b-it" in ids
