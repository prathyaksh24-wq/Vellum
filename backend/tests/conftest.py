import os
from pathlib import Path
import tempfile

import pytest

_ROOT = Path(tempfile.mkdtemp(prefix="vellum-test-"))
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ["KNOWLEDGE_CORE_DB_PATH"] = str((_ROOT / "knowledge" / "core.db").resolve())
os.environ["KNOWLEDGE_BLOB_PATH"] = str((_ROOT / "knowledge" / "blobs").resolve())
os.environ.setdefault("COMPUTER_USE_SCREENSHOT_DIR", str((_ROOT / "computer-use" / "screenshots").resolve()))
os.environ.setdefault("COMPUTER_USE_EXCLUSIVE_CONTROL", "false")
# A developer .env may point Playwright at a local Node runtime; tests expect the default launcher.
os.environ["PLAYWRIGHT_MCP_COMMAND"] = "npx"
os.environ["PLAYWRIGHT_MCP_ARGS"] = "-y @playwright/mcp@latest --isolated"


@pytest.fixture(autouse=True, scope="session")
def test_environment() -> None:
    return None


@pytest.fixture(autouse=True)
def no_local_memory_model():
    """Memory features call local Ollama; tests must not depend on it running.

    Tests that exercise the model path pass their own selector or patch
    ``agent.memory.local_llm`` explicitly.

    Uses a private MonkeyPatch: requesting the shared ``monkeypatch`` fixture
    here would set it up before the cache-reset fixture below, so a test's own
    patches (e.g. of ``get_provider_registry``) would still be active when the
    caches are cleared at teardown.
    """
    from agent.memory import local_llm, recall

    def unavailable(*args, **kwargs):
        raise local_llm.LocalLLMError("local model disabled in tests")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(local_llm, "complete", unavailable)
        patch.setattr(local_llm, "complete_json", unavailable)
        patch.setattr(local_llm, "stream", unavailable)
        recall.clear_cache()
        yield


@pytest.fixture(scope="module")
def repo_root_cwd() -> Path:
    """Run tests with cwd at the repository root (plugins/, design/ are root-relative)."""

    repo_root = Path(__file__).resolve().parents[2]
    previous = Path.cwd()
    os.chdir(repo_root)
    yield repo_root
    os.chdir(previous)


@pytest.fixture(autouse=True)
def reset_process_configuration_caches():
    """Prevent provider-key tests from leaking cached settings into later tests."""

    yield
    from agent.config import get_settings
    from agent.llm.providers import get_provider_registry

    get_settings.cache_clear()
    get_provider_registry.cache_clear()
