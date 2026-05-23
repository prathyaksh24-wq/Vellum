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
    assert settings.playwright_mcp_command == "npx"
    assert "@playwright/mcp@latest" in settings.playwright_mcp_args
    assert isinstance(settings.playwright_mcp_allow_mutations, bool)
    assert isinstance(settings.computer_use_allow_desktop, bool)
    assert settings.computer_use_screenshot_dir.name == "screenshots"
    assert settings.computer_use_activity_overlay is True
    assert settings.github_mcp_url == "https://api.githubcopilot.com/mcp/"
    assert isinstance(settings.github_pat, str)
    assert isinstance(settings.obsidian_api_key, str)
    assert settings.obsidian_mcp_url == "https://127.0.0.1:27124/mcp/"
    assert settings.obsidian_mcp_use_stream is False
    assert settings.obsidian_mcp_verify_ssl is False
    assert settings.cloud_escalation_model == "google/gemini-2.5-pro"
    assert settings.cloud_escalation_enabled is True
    assert settings.qdrant_local_path is not None
    assert settings.qdrant_local_path.name == "qdrant-local"
