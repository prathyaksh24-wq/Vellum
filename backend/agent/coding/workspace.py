from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import threading

from agent.coding.models import AccessMode, WorkspaceKind, utc_now


DEFAULT_MAX_ACTIVE_WORKTREES = 24
GIT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_CHECKPOINT_PATCH_BYTES = 256 * 1024
DEFAULT_MAX_CHECKPOINT_FILE_BYTES = 256 * 1024
DEFAULT_MAX_CHECKPOINT_FILES = 2_000
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_CHECKPOINT_DIFF_PATHS = (
    ".",
    ":(exclude).env",
    ":(exclude).env.*",
    ":(exclude).aws/**",
    ":(exclude).ssh/**",
    ":(exclude).netrc",
    ":(exclude).npmrc",
    ":(exclude).pypirc",
    ":(exclude)*.pem",
    ":(exclude)*.key",
    ":(exclude)*.p12",
    ":(exclude)*.pfx",
    ":(exclude)id_dsa",
    ":(exclude)id_ecdsa",
    ":(exclude)id_ed25519",
    ":(exclude)id_rsa",
    ":(exclude)**/.env",
    ":(exclude)**/.env.*",
    ":(exclude)**/.aws/**",
    ":(exclude)**/.ssh/**",
    ":(exclude)**/.netrc",
    ":(exclude)**/.npmrc",
    ":(exclude)**/.pypirc",
    ":(exclude)**/*.pem",
    ":(exclude)**/*.key",
    ":(exclude)**/*.p12",
    ":(exclude)**/*.pfx",
    ":(exclude)**/id_dsa",
    ":(exclude)**/id_ecdsa",
    ":(exclude)**/id_ed25519",
    ":(exclude)**/id_rsa",
)


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


@dataclass(frozen=True)
class WorkspaceSnapshot:
    captured_at: str
    git_head: str = ""
    changed_files: tuple[str, ...] = ()
    patch: str = ""
    files_truncated: bool = False
    patch_truncated: bool = False
    capture_error: str = ""

    def metadata(self) -> dict[str, object]:
        return {
            "captured_at": self.captured_at,
            "git_head": self.git_head,
            "changed_files": list(self.changed_files),
            "files_truncated": self.files_truncated,
            "patch_truncated": self.patch_truncated,
            "capture_error": self.capture_error,
        }


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

    def is_git_workspace(self, workspace_root: str) -> bool:
        root = Path(workspace_root).expanduser().resolve()
        try:
            return self._git(root, "rev-parse", "--is-inside-work-tree") == "true"
        except CodingWorkspaceError:
            return False

    def capture_snapshot(
        self,
        workspace_root: str,
        *,
        max_patch_bytes: int = DEFAULT_MAX_CHECKPOINT_PATCH_BYTES,
        max_file_bytes: int = DEFAULT_MAX_CHECKPOINT_FILE_BYTES,
        max_files: int = DEFAULT_MAX_CHECKPOINT_FILES,
    ) -> WorkspaceSnapshot:
        captured_at = utc_now()
        root = Path(workspace_root).expanduser().resolve()
        if max_patch_bytes < 1 or max_file_bytes < 1 or max_files < 1:
            raise ValueError("Workspace snapshot limits must be positive.")
        try:
            git_head = self._git(root, "rev-parse", "HEAD")
            tracked_bytes, tracked_truncated = self._git_bounded(
                root,
                "diff",
                "--name-only",
                "-z",
                "HEAD",
                "--",
                limit=max_file_bytes,
            )
            untracked_bytes, untracked_truncated = self._git_bounded(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                limit=max_file_bytes,
            )
            tracked_files = self._bounded_nul_values(tracked_bytes, truncated=tracked_truncated)
            untracked_files = self._bounded_nul_values(untracked_bytes, truncated=untracked_truncated)
            changed_files = sorted(
                {
                    value
                    for value in [*tracked_files, *untracked_files]
                    if value and not self._checkpoint_path_protected(value)
                }
            )
            files_truncated = tracked_truncated or untracked_truncated or len(changed_files) > max_files
            changed_files = changed_files[:max_files]
            patch_bytes, patch_truncated = self._git_bounded(
                root,
                "diff",
                "--binary",
                "--no-ext-diff",
                "HEAD",
                "--",
                *_CHECKPOINT_DIFF_PATHS,
                limit=max_patch_bytes,
            )
            return WorkspaceSnapshot(
                captured_at=captured_at,
                git_head=git_head,
                changed_files=tuple(changed_files),
                patch=patch_bytes.decode("utf-8", errors="replace"),
                files_truncated=files_truncated,
                patch_truncated=patch_truncated,
            )
        except CodingWorkspaceError as exc:
            return WorkspaceSnapshot(captured_at=captured_at, capture_error=str(exc))

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

    @staticmethod
    def _bounded_nul_values(output: bytes, *, truncated: bool) -> list[str]:
        values = output.split(b"\0")
        if truncated and output and not output.endswith(b"\0"):
            values = values[:-1]
        return [value.decode("utf-8", errors="replace") for value in values]

    @staticmethod
    def _checkpoint_path_protected(value: str) -> bool:
        protected_names = {
            ".aws",
            ".env",
            ".netrc",
            ".npmrc",
            ".pypirc",
            ".ssh",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
            "id_rsa",
        }
        for part in Path(value).parts:
            lowered = part.casefold()
            if (
                lowered in protected_names
                or lowered.startswith(".env.")
                or lowered.endswith((".pem", ".key", ".p12", ".pfx"))
            ):
                return True
        return False

    @staticmethod
    def _git_bounded(cwd: Path, *args: str, limit: int) -> tuple[bytes, bool]:
        timed_out = threading.Event()
        try:
            process = subprocess.Popen(
                ["git", "-C", str(cwd), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise CodingWorkspaceError("Git is not installed or is not available on PATH.") from exc

        def kill_on_timeout() -> None:
            if process.poll() is None:
                timed_out.set()
                process.kill()

        timer = threading.Timer(GIT_TIMEOUT_SECONDS, kill_on_timeout)
        timer.daemon = True
        timer.start()
        try:
            if process.stdout is None:
                raise CodingWorkspaceError("Git workspace output was unavailable.")
            output = process.stdout.read(limit + 1)
            truncated = len(output) > limit
            if truncated and process.poll() is None:
                process.kill()
            process.wait()
        finally:
            timer.cancel()
        if timed_out.is_set():
            raise CodingWorkspaceError("Git checkpoint operation timed out.")
        if not truncated and process.returncode != 0:
            detail = output.decode("utf-8", errors="replace").strip()
            raise CodingWorkspaceError(detail or "Git checkpoint operation failed.")
        return output[:limit], truncated
