from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.telemetry.usage_ledger import UsageLedger
from agent.tui.cli.app import app


@pytest.fixture
def runner_empty(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    return CliRunner()


@pytest.fixture
def runner_seeded(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memory").mkdir(parents=True)
    ledger = UsageLedger(tmp_path / "data" / "memory" / "usage.db")
    ledger.record(thread_id="t1", model="google/gemma-4-31b-it",
                  in_tokens=1000, out_tokens=500, source="tui")
    return CliRunner()


def test_usage_empty_state(runner_empty: CliRunner) -> None:
    result = runner_empty.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "Nothing on this in your library." in result.stdout


def test_usage_shows_per_model_summary(runner_seeded: CliRunner) -> None:
    result = runner_seeded.invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "google/gemma-4-31b-it" in result.stdout
    assert "1,000" in result.stdout or "1000" in result.stdout
