from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.tui.cli.app import app


@pytest.fixture
def runner_with_env(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-secret-12345\nPRIMARY_MODEL=google/gemma-4-31b-it\n",
        encoding="utf-8",
    )
    return CliRunner()


def test_config_print_redacts_keys(runner_with_env: CliRunner) -> None:
    result = runner_with_env.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "sk-or-secret-12345" not in result.stdout
    assert "sk-or" in result.stdout  # redacted prefix still shown
    assert "google/gemma-4-31b-it" in result.stdout


def test_config_missing_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["config"])
    assert r.exit_code == 0
    assert "Nothing on this in your library." in r.stdout
