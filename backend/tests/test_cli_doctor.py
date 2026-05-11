from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.tui.cli.app import app


def test_doctor_runs_and_exits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    # missing .env / vault → exit code 1, but should not crash
    assert result.exit_code in (0, 1)
    for label in ["vault exists", "zdr on", "checkpoints.db readable"]:
        assert label in result.stdout
