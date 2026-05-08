from agent.config import get_settings


def test_settings_loads_paths_and_privacy_defaults():
    settings = get_settings()

    assert settings.obsidian_vault_path.exists()
    assert settings.filesystem_mcp_path.exists()
    assert settings.filesystem_mcp_path.is_relative_to(settings.obsidian_vault_path)
    assert settings.zdr_only is True
    assert settings.enable_pii_scrubbing is True
    assert 0 <= settings.min_retrieval_score <= 1
    assert settings.fast_model == "google/gemma-3-12b-it"
    assert settings.fast_model != "google/gemma-4-12b-it"
    assert settings.apify_mcp_url == "https://mcp.apify.com"
    assert settings.qdrant_local_path is not None
    assert settings.qdrant_local_path.name == "qdrant-local"
