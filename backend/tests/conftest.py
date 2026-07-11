import os
from pathlib import Path
import tempfile

import pytest

_ROOT = Path(tempfile.mkdtemp(prefix="vellum-test-"))
_VAULT = _ROOT / "vault"
_VAULT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", str(_VAULT.resolve()))
os.environ.setdefault("FILESYSTEM_MCP_PATH", str(_VAULT.resolve()))
os.environ.setdefault("COMPUTER_USE_SCREENSHOT_DIR", str((_ROOT / "computer-use" / "screenshots").resolve()))
os.environ.setdefault("COMPUTER_USE_EXCLUSIVE_CONTROL", "false")


@pytest.fixture(autouse=True, scope="session")
def test_environment() -> None:
    return None


@pytest.fixture(autouse=True)
def reset_process_configuration_caches():
    """Prevent provider-key tests from leaking cached settings into later tests."""

    yield
    from agent.config import get_settings
    from agent.llm.providers import get_provider_registry

    get_settings.cache_clear()
    get_provider_registry.cache_clear()
