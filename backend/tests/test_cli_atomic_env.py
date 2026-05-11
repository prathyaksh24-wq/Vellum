from pathlib import Path

import pytest

from agent.tui.cli.atomic_env import load_env, write_env


def test_load_env_returns_dict(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
    assert load_env(env) == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# a comment\n\nFOO=bar\n  # indented\n", encoding="utf-8")
    assert load_env(env) == {"FOO": "bar"}


def test_load_env_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_env(tmp_path / "missing.env") == {}


def test_write_env_is_atomic_on_crash(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=original\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(RuntimeError):
        write_env(env, {"FOO": "changed"})

    assert env.read_text(encoding="utf-8") == "FOO=original\n"


def test_write_env_round_trip(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    write_env(env, {"FOO": "bar", "BAZ": "qux"})
    assert load_env(env) == {"FOO": "bar", "BAZ": "qux"}


def test_write_env_preserves_existing_keys_via_merge(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=keep\nBAR=old\n", encoding="utf-8")
    current = load_env(env)
    current["BAR"] = "new"
    current["EXTRA"] = "added"
    write_env(env, current)
    result = load_env(env)
    assert result == {"FOO": "keep", "BAR": "new", "EXTRA": "added"}
