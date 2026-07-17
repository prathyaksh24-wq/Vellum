from pathlib import Path
import shutil
import subprocess

import pytest

from agent.coding.models import AccessMode, WorkspaceKind
from agent.coding.workspace import CodingWorkspaceError, CodingWorkspaceManager


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.name", "Vellum Tests")
    _git(path, "config", "user.email", "vellum-tests@example.invalid")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("print('ready')\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


def test_read_only_workspace_uses_selected_directory_directly(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()
    manager = CodingWorkspaceManager(tmp_path / "worktrees")

    provision = manager.provision(
        session_id="code_read_only",
        source_cwd=str(source),
        access_mode=AccessMode.read_only,
    )

    assert provision.kind == WorkspaceKind.direct
    assert provision.cwd == str(source.resolve())
    assert provision.workspace_root == str(source.resolve())
    assert not (tmp_path / "worktrees").exists()


def test_writable_workspace_creates_isolated_branch_and_preserves_subdirectory(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "project")
    manager = CodingWorkspaceManager(tmp_path / "worktrees")

    provision = manager.provision(
        session_id="code_isolated",
        source_cwd=str(repository / "src"),
        access_mode=AccessMode.workspace_write,
    )

    workspace_root = Path(provision.workspace_root)
    assert provision.kind == WorkspaceKind.git_worktree
    assert provision.cwd == str((workspace_root / "src").resolve())
    assert provision.branch == "vellum/session/code_isolated"
    assert provision.base_commit == _git(repository, "rev-parse", "HEAD")
    assert _git(workspace_root, "branch", "--show-current") == provision.branch
    assert (Path(provision.cwd) / "app.py").read_text(encoding="utf-8") == "print('ready')\n"

    manager.release(provision, force=True, delete_branch=True)

    assert not workspace_root.exists()
    assert provision.branch not in _git(repository, "branch", "--list", provision.branch)


def test_writable_workspace_requires_git_repository(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()
    manager = CodingWorkspaceManager(tmp_path / "worktrees")

    with pytest.raises(CodingWorkspaceError, match="require a Git repository"):
        manager.provision(
            session_id="code_no_git",
            source_cwd=str(source),
            access_mode=AccessMode.workspace_write,
        )


def test_workspace_manager_enforces_active_worktree_limit(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "project")
    manager = CodingWorkspaceManager(tmp_path / "worktrees", max_active_worktrees=1)
    first = manager.provision(
        session_id="code_first",
        source_cwd=str(repository),
        access_mode=AccessMode.workspace_write,
    )

    try:
        with pytest.raises(CodingWorkspaceError, match="worktree limit reached"):
            manager.provision(
                session_id="code_second",
                source_cwd=str(repository),
                access_mode=AccessMode.workspace_write,
            )
    finally:
        manager.release(first, force=True, delete_branch=True)
