from pathlib import Path

import pytest

from agent.cli.project_commands import (
    CommandResult,
    InvalidCommand,
    handle_project_command,
)
from agent.memory.project_context import ProjectContext


def _ctx(tmp_path: Path) -> ProjectContext:
    return ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db")


def test_no_args_lists_projects(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")

    result = handle_project_command(ctx, "t1", args=[])
    assert isinstance(result, CommandResult)
    assert "fitness" in result.message
    assert "(none)" in result.message or "active:" in result.message.lower()


def test_set_active_project(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")

    result = handle_project_command(ctx, "t1", args=["fitness"])
    assert ctx._state.get_active_project("t1") == "fitness"
    assert "fitness" in result.message


def test_set_active_missing_project_fails(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with pytest.raises(InvalidCommand):
        handle_project_command(ctx, "t1", args=["ghost"])


def test_clear_active(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    proj = tmp_path / "Projects" / "fitness"
    proj.mkdir(parents=True)
    (proj / "vellum.md").write_text("CHARTER")
    ctx._state.set_active_project("t1", "fitness")

    handle_project_command(ctx, "t1", args=["--clear"])
    assert ctx._state.get_active_project("t1") is None


def test_create_project(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    handle_project_command(ctx, "t1", args=["create", "fitness"])
    proj = tmp_path / "Projects" / "fitness"
    assert (proj / "vellum.md").exists()
    assert (proj / "hot.md").exists()
    assert (proj / "log.md").exists()
    assert (proj / "notes").is_dir()
    assert ctx._state.get_active_project("t1") == "fitness"


def test_create_invalid_slug_rejected(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with pytest.raises(InvalidCommand):
        handle_project_command(ctx, "t1", args=["create", "Bad Name"])


def test_create_duplicate_rejected(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    handle_project_command(ctx, "t1", args=["create", "fitness"])
    with pytest.raises(InvalidCommand):
        handle_project_command(ctx, "t1", args=["create", "fitness"])
