from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess

from agent.coding.models import AccessMode, WorkspaceKind


DEFAULT_MAX_ACTIVE_WORKTREES = 24
GIT_TIMEOUT_SECONDS = 30
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


class CodingWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceProvision:
    source_cwd: str
    cwd: str
    kind: WorkspaceKind
    workspace_root: str
    repository_root: str = ""
    branch: str = ""
    base_commit: str = ""


def default_coding_worktree_root() -> Path:
    configured = os.environ.get("VELLUM_CODING_WORKTREE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        return (Path(local_appdata) / "Vellum" / "coding-worktrees").resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return (Path(xdg_data_home) / "vellum" / "coding-worktrees").resolve()
    return (Path.home() / ".local" / "share" / "vellum" / "coding-worktrees").resolve()


class CodingWorkspaceManager:
    def __init__(
        self,
        root: Path | None = None,
        *,
        max_active_worktrees: int = DEFAULT_MAX_ACTIVE_WORKTREES,
    ) -> None:
        if max_active_worktrees < 1:
            raise ValueError("max_active_worktrees must be positive")
        self.root = (root or default_coding_worktree_root()).expanduser().resolve()
        self.max_active_worktrees = max_active_worktrees

    def provision(
        self,
        *,
        session_id: str,
        source_cwd: str,
        access_mode: AccessMode,
    ) -> WorkspaceProvision:
        source = Path(source_cwd).expanduser().resolve()
        if not source.exists() or not source.is_dir():
            raise CodingWorkspaceError("Project not found.")
        if access_mode == AccessMode.read_only:
            return WorkspaceProvision(
                source_cwd=str(source),
                cwd=str(source),
                kind=WorkspaceKind.direct,
                workspace_root=str(source),
            )
        if _SESSION_ID.fullmatch(session_id) is None:
            raise CodingWorkspaceError("Coding session identifier is not safe for workspace creation.")

        repository_root = self._repository_root(source)
        try:
            relative_cwd = source.relative_to(repository_root)
        except ValueError as exc:
            raise CodingWorkspaceError("Project path is outside its Git repository.") from exc
        base_commit = self._git(repository_root, "rev-parse", "HEAD")

        self.root.mkdir(parents=True, exist_ok=True)
        if self.root == repository_root or self.root.is_relative_to(repository_root):
            raise CodingWorkspaceError("Coding worktree storage must be outside the source repository.")
        active_count = sum(1 for child in self.root.iterdir() if child.is_dir())
        if active_count >= self.max_active_worktrees:
            raise CodingWorkspaceError(
                f"Coding worktree limit reached ({self.max_active_worktrees}). Close an older session first."
            )

        workspace_root = (self.root / session_id).resolve()
        if workspace_root.parent != self.root:
            raise CodingWorkspaceError("Coding workspace target is outside the managed worktree root.")
        if workspace_root.exists():
            raise CodingWorkspaceError("Coding workspace already exists for this session.")
        branch = f"vellum/session/{session_id}"
        self._git(repository_root, "worktree", "add", "-b", branch, str(workspace_root), base_commit)
        effective_cwd = (workspace_root / relative_cwd).resolve()
        if not effective_cwd.is_relative_to(workspace_root) or not effective_cwd.is_dir():
            self._release_created_worktree(repository_root, workspace_root, branch)
            raise CodingWorkspaceError("Coding workspace could not preserve the selected project directory.")
        return WorkspaceProvision(
            source_cwd=str(source),
            cwd=str(effective_cwd),
            kind=WorkspaceKind.git_worktree,
            workspace_root=str(workspace_root),
            repository_root=str(repository_root),
            branch=branch,
            base_commit=base_commit,
        )

    def release(
        self,
        provision: WorkspaceProvision,
        *,
        force: bool = False,
        delete_branch: bool = False,
    ) -> None:
        if provision.kind != WorkspaceKind.git_worktree:
            return
        repository_root = Path(provision.repository_root).expanduser().resolve()
        workspace_root = Path(provision.workspace_root).expanduser().resolve()
        if workspace_root.parent != self.root:
            raise CodingWorkspaceError("Refusing to release a workspace outside the managed worktree root.")
        arguments = ["worktree", "remove"]
        if force:
            arguments.append("--force")
        arguments.append(str(workspace_root))
        if workspace_root.exists():
            self._git(repository_root, *arguments)
        if delete_branch and provision.branch:
            self._git(repository_root, "branch", "-D", provision.branch, check=False)

    def _repository_root(self, source: Path) -> Path:
        try:
            value = self._git(source, "rev-parse", "--show-toplevel")
        except CodingWorkspaceError as exc:
            raise CodingWorkspaceError(
                "Writable coding sessions require a Git repository. Use read-only access or initialize Git."
            ) from exc
        repository_root = Path(value).expanduser().resolve()
        if not repository_root.exists() or not repository_root.is_dir():
            raise CodingWorkspaceError("Git repository root could not be resolved.")
        return repository_root

    def _release_created_worktree(self, repository_root: Path, workspace_root: Path, branch: str) -> None:
        if workspace_root.exists():
            self._git(repository_root, "worktree", "remove", "--force", str(workspace_root))
        if branch:
            self._git(repository_root, "branch", "-D", branch, check=False)

    @staticmethod
    def _git(cwd: Path, *args: str, check: bool = True) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise CodingWorkspaceError("Git is not installed or is not available on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodingWorkspaceError("Git workspace operation timed out.") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise CodingWorkspaceError(detail or "Git workspace operation failed.")
        return result.stdout.strip()
