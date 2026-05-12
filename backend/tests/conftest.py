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


@pytest.fixture(autouse=True, scope="session")
def test_environment() -> None:
    return None
