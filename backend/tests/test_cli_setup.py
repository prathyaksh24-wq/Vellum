from pathlib import Path

import pytest

from agent.tui.cli.commands.setup import _merge_into_env


def test_merge_into_env_overwrites_keys(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=old\nBAR=keep\n", encoding="utf-8")
    monkeypatch.setattr("agent.tui.cli.commands.setup._Path_env", lambda: env)
    _merge_into_env({"FOO": "new", "BAZ": "added"})
    text = env.read_text(encoding="utf-8")
    assert "FOO=new" in text
    assert "BAR=keep" in text
    assert "BAZ=added" in text


def test_merge_into_env_creates_file_if_missing(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    monkeypatch.setattr("agent.tui.cli.commands.setup._Path_env", lambda: env)
    _merge_into_env({"FOO": "bar"})
    assert env.read_text(encoding="utf-8") == "FOO=bar\n"
