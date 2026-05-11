import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent.tui.cli.app import app


@pytest.fixture
def runner(tmp_path: Path, monkeypatch) -> CliRunner:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "memory").mkdir(parents=True)
    # Seed a checkpoints db with one thread, matching the real langgraph schema.
    cp = tmp_path / "data" / "memory" / "checkpoints.db"
    conn = sqlite3.connect(str(cp))
    conn.execute(
        """
        CREATE TABLE checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint BLOB,
            metadata BLOB,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        )
        """
    )
    conn.execute("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES ('t1', '', '01J000')")
    conn.execute("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES ('t1', '', '01J001')")
    conn.commit()
    conn.close()
    return CliRunner()


def test_sessions_list_shows_thread(runner: CliRunner) -> None:
    result = runner.invoke(app, ["sessions"])
    assert result.exit_code == 0
    assert "t1" in result.stdout
    assert "2" in result.stdout  # msg count


def test_sessions_list_empty_when_no_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["sessions"])
    assert r.exit_code == 0
    assert "Nothing on this in your library." in r.stdout


def test_sessions_rename_writes_title(runner: CliRunner) -> None:
    result = runner.invoke(app, ["sessions", "rename", "t1", "my research"])
    assert result.exit_code == 0
    assert "Filed." in result.stdout
    # Subsequent list shows new title
    list_result = runner.invoke(app, ["sessions"])
    assert "my research" in list_result.stdout


def test_sessions_delete_removes_thread(runner: CliRunner) -> None:
    # --yes flag skips confirmation
    result = runner.invoke(app, ["sessions", "delete", "t1", "--yes"])
    assert result.exit_code == 0
    assert "Out." in result.stdout
    list_result = runner.invoke(app, ["sessions"])
    assert "t1" not in list_result.stdout
