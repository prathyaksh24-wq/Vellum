"""App Action adapter over coding-session and GitHub publication owners."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import quote

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.coding.models import CodingSession, WorkspaceKind
from agent.config import get_settings
from agent.tools.registry import CapabilityAccess

if TYPE_CHECKING:
    from agent.coding.service import CodingSessionService


CODING_WORKSPACE_OPEN_ACTION_ID = "coding.workspace.open"
GITHUB_PULL_REQUEST_OPEN_ACTION_ID = "github.pull_request.open"
GITHUB_PULL_REQUEST_CREATE_ACTION_ID = "github.pull_request.create"

CODING_GITHUB_ACTION_IDS = frozenset({
    CODING_WORKSPACE_OPEN_ACTION_ID,
    GITHUB_PULL_REQUEST_OPEN_ACTION_ID,
    GITHUB_PULL_REQUEST_CREATE_ACTION_ID,
})

_GITHUB_REMOTE = re.compile(
    r"^(?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:)(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)
_PULL_URL = re.compile(r"https://github\.com/[^\s/]+/[^\s/]+/pull/\d+", re.IGNORECASE)


class CodingGitHubActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


@dataclass(frozen=True)
class PullRequestState:
    session_id: str
    repository: str
    branch: str
    base: str
    head_sha: str
    commit_count: int
    changed_files: int

    @property
    def fingerprint(self) -> str:
        content = "\n".join((self.session_id, self.repository, self.branch, self.base, self.head_sha))
        return sha256(content.encode("utf-8")).hexdigest()

    def public_summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "repository": self.repository,
            "branch": self.branch,
            "base": self.base,
            "head_sha": self.head_sha,
            "commit_count": self.commit_count,
            "changed_files": self.changed_files,
        }


RepositoryStateProvider = Callable[[CodingSession], PullRequestState]
RepositoryProvider = Callable[[CodingSession], str]
GitHubRunner = Callable[[dict[str, Any]], str]
GitWriter = Callable[..., str]


def _default_github_runner(payload: dict[str, Any]) -> str:
    from agent.mcp.github_tools import run_tool

    return run_tool(payload)


def _default_git_writer(**payload: Any) -> str:
    from agent.tools.git_local import git_action

    return git_action.func(**payload)


class CodingGitHubActionService:
    """Resolve App Actions against authoritative coding-session and connector state."""

    def __init__(
        self,
        *,
        coding_service: "CodingSessionService",
        github_runner: GitHubRunner | None = None,
        git_writer: GitWriter | None = None,
        settings_provider: Callable[[], Any] | None = None,
        repository_state_provider: RepositoryStateProvider | None = None,
        repository_provider: RepositoryProvider | None = None,
    ) -> None:
        self._coding = coding_service
        self._github_runner = github_runner or _default_github_runner
        self._git_writer = git_writer or _default_git_writer
        self._settings_provider = settings_provider or get_settings
        self._repository_state_provider = repository_state_provider or self._repository_state
        self._repository_provider = repository_provider or self._repository_for_session

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
        *,
        confirmed: bool = False,
        confirmation_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action_id == CODING_WORKSPACE_OPEN_ACTION_ID:
            return self._open_workspace(arguments)
        if action_id == GITHUB_PULL_REQUEST_OPEN_ACTION_ID:
            return self._open_pull_request(arguments)
        if action_id == GITHUB_PULL_REQUEST_CREATE_ACTION_ID:
            return self._create_pull_request(
                arguments,
                confirmed=confirmed,
                confirmation_binding=confirmation_binding,
            )
        raise CodingGitHubActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    def _open_workspace(self, arguments: dict[str, Any]) -> dict[str, Any]:
        reference = str(arguments.get("session") or arguments.get("session_id") or "").strip()
        session = self._resolve_session(reference, required=False)
        url = "vellum-workspace.html"
        result: dict[str, Any] = {
            "changed": True,
            "navigation": {"url": url, "kind": "coding_workspace"},
            "_target_kind": "ui_surface",
            "_target_id": "coding-workspace",
            "_message": "Coding workspace opened.",
        }
        if session is not None:
            result["coding_session"] = self._session_summary(session)
            result["navigation"]["url"] = f"{url}?session={quote(session.id, safe='')}"
            result["navigation"]["session_id"] = session.id
            result["_target_id"] = session.id
            result["_message"] = f"Opened coding session {session.title or session.id}."
        return result

    def _open_pull_request(self, arguments: dict[str, Any]) -> dict[str, Any]:
        settings = self._settings_provider()
        if not self._github_token(settings):
            raise CodingGitHubActionError(
                "GITHUB_AUTH_UNAVAILABLE",
                "GitHub authentication is unavailable.",
                unavailable=True,
            )
        pull_number = self._pull_number(arguments)
        repository = self._resolve_repository(arguments)
        owner, repo = repository.split("/", 1)
        try:
            text = self._github_runner({
                "action": "get_pull_request",
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
            })
        except Exception as exc:
            raise CodingGitHubActionError(
                "GITHUB_READ_FAILED",
                "GitHub could not read the pull request.",
                unavailable=True,
            ) from exc
        self._require_connector_success(text, operation="read")
        url = self._pull_url(text) or f"https://github.com/{repository}/pull/{pull_number}"
        open_url = bool(arguments.get("open", True))
        connector_summary = " ".join(str(text).split())[:600]
        message = (
            f"Opened pull request #{pull_number} in {repository}: {url}"
            if open_url
            else f"Pull request #{pull_number} in {repository}: {connector_summary}"
        )
        return {
            "changed": open_url,
            "pull_request": {
                "repository": repository,
                "number": pull_number,
                "url": url,
                "summary": str(text)[:8000],
            },
            **({"navigation": {"url": url, "kind": "external"}} if open_url else {}),
            "_target_kind": "github_pull_request",
            "_target_id": f"{repository}#{pull_number}",
            "_message": message,
        }

    def _create_pull_request(
        self,
        arguments: dict[str, Any],
        *,
        confirmed: bool,
        confirmation_binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        settings = self._settings_provider()
        if not self._github_token(settings):
            raise CodingGitHubActionError(
                "GITHUB_AUTH_UNAVAILABLE",
                "GitHub authentication is unavailable.",
                unavailable=True,
            )
        if not bool(getattr(settings, "github_mcp_allow_writes", False)):
            raise CodingGitHubActionError(
                "GITHUB_WRITE_UNAVAILABLE",
                "GitHub pull-request creation is disabled.",
                unavailable=True,
            )
        if not bool(getattr(settings, "git_tool_allow_writes", False)):
            raise CodingGitHubActionError(
                "GIT_PUBLISH_UNAVAILABLE",
                "Git branch publication is disabled.",
                unavailable=True,
            )

        session = self._resolve_session(str(arguments.get("session_id") or "").strip(), required=True)
        if session.status == "running":
            raise CodingGitHubActionError(
                "CODING_SESSION_BUSY",
                "Wait for the coding session to finish before creating a pull request.",
                unavailable=True,
            )
        state = self._repository_state_provider(session)
        self._validate_requested_target(arguments, state)
        if state.commit_count < 1:
            raise CodingGitHubActionError(
                "NO_PUBLISHABLE_CHANGES",
                "The coding branch has no committed changes to publish.",
                unavailable=True,
            )

        binding = {
            "fingerprint": state.fingerprint,
            "session_id": state.session_id,
            "repository": state.repository,
            "branch": state.branch,
            "base": state.base,
            "head_sha": state.head_sha,
        }
        title = str(arguments.get("title") or "").strip() or self._default_title(state.branch)
        review = {
            **state.public_summary(),
            "title": title,
            "draft": bool(arguments.get("draft", False)),
        }
        if not confirmed:
            return {
                "changed": False,
                "pull_request_review": review,
                "_confirmation_binding": binding,
                "_target_kind": "github_repository",
                "_target_id": state.repository,
                "_message": (
                    f"Confirm publishing {state.branch} to {state.repository} and creating the pull request."
                ),
            }

        if not confirmation_binding or confirmation_binding != binding:
            raise CodingGitHubActionError(
                "STALE_ACTION_TARGET",
                "The coding branch changed before pull-request creation was confirmed.",
            )

        try:
            publish_result = self._git_writer(
                action="push",
                repo_path=session.cwd,
                remote="origin",
                branch=state.branch,
            )
        except Exception as exc:
            raise CodingGitHubActionError(
                "PR_PUBLICATION_FAILED",
                "The coding branch could not be published.",
            ) from exc
        if self._failed_result(publish_result):
            raise CodingGitHubActionError(
                "PR_PUBLICATION_FAILED",
                "The coding branch could not be published.",
            )

        owner, repo = state.repository.split("/", 1)
        try:
            response = self._github_runner({
                "action": "create_pull_request",
                "owner": owner,
                "repo": repo,
                "title": title,
                "body": str(arguments.get("body") or "").strip(),
                "head": state.branch,
                "base": state.base,
                "draft": bool(arguments.get("draft", False)),
            })
        except Exception as exc:
            raise CodingGitHubActionError(
                "PR_CREATION_FAILED",
                "GitHub could not create the pull request.",
            ) from exc
        self._require_connector_success(response, operation="create")
        url = self._pull_url(response)
        if not url:
            raise CodingGitHubActionError(
                "PR_CREATION_FAILED",
                "GitHub did not return a pull-request URL.",
            )
        return {
            "changed": True,
            "pull_request": {**review, "url": url},
            "navigation": {"url": url, "kind": "external"},
            "_target_kind": "github_pull_request",
            "_target_id": url,
            "_message": f"Pull request created: {url}",
        }

    def _resolve_repository(self, arguments: dict[str, Any]) -> str:
        requested = self._normalize_repository(arguments.get("repository"))
        session_reference = str(arguments.get("session_id") or "").strip()
        if requested and not session_reference:
            return requested
        session = self._resolve_session(session_reference, required=True)
        if session is None:
            return requested
        repository = self._repository_provider(session)
        if requested and requested.casefold() != repository.casefold():
            raise CodingGitHubActionError(
                "WRONG_REPOSITORY",
                f"The requested repository does not match coding session {session.id}.",
            )
        return repository

    def _resolve_session(self, reference: str, *, required: bool) -> CodingSession | None:
        sessions = [session for session in self._coding.list_sessions() if session.status != "closed"]
        if reference:
            matches = [
                session
                for session in sessions
                if session.id == reference or session.title.casefold() == reference.casefold()
            ]
            if len(matches) != 1:
                raise CodingGitHubActionError(
                    "CODING_SESSION_UNAVAILABLE",
                    f"Coding session {reference} is unavailable.",
                    unavailable=True,
                )
            return matches[0]
        if not sessions:
            if required:
                raise CodingGitHubActionError(
                    "CODING_SESSION_REQUIRED",
                    "Start a coding session before creating a pull request.",
                    unavailable=True,
                )
            return None
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return sessions[0]

    def _repository_state(self, session: CodingSession) -> PullRequestState:
        if session.workspace_kind != WorkspaceKind.git_worktree:
            raise CodingGitHubActionError(
                "ISOLATED_CODING_WORKSPACE_REQUIRED",
                "Pull-request creation requires an isolated Git coding workspace.",
                unavailable=True,
            )
        workspace = Path(session.cwd).expanduser().resolve()
        repository_root = Path(session.workspace_repository_root).expanduser().resolve()
        if not workspace.is_dir() or not repository_root.is_dir():
            raise CodingGitHubActionError(
                "CODING_REPOSITORY_UNAVAILABLE",
                "The coding repository is unavailable.",
                unavailable=True,
            )
        workspace_root = Path(self._git_read(workspace, "rev-parse", "--show-toplevel")).resolve()
        source_root = Path(self._git_read(repository_root, "rev-parse", "--show-toplevel")).resolve()
        if workspace_root != workspace or source_root != repository_root:
            raise CodingGitHubActionError(
                "WRONG_REPOSITORY",
                "The coding session no longer points at its canonical repository.",
            )
        branch = self._git_read(workspace, "branch", "--show-current")
        if not branch or branch != session.workspace_branch:
            raise CodingGitHubActionError(
                "WRONG_BRANCH",
                "The coding workspace branch does not match its session record.",
            )
        repository = self._repository_for_session(session)
        base = self._default_base(repository_root)
        head_sha = self._git_read(workspace, "rev-parse", "HEAD")
        if self._git_read(workspace, "status", "--porcelain"):
            raise CodingGitHubActionError(
                "UNCOMMITTED_CHANGES",
                "Commit the coding workspace changes before creating a pull request.",
                unavailable=True,
            )
        base_commit = str(session.workspace_base_commit or "").strip()
        if not base_commit:
            raise CodingGitHubActionError(
                "CODING_BASE_UNAVAILABLE",
                "The coding session base commit is unavailable.",
                unavailable=True,
            )
        commit_count = int(self._git_read(workspace, "rev-list", "--count", f"{base_commit}..HEAD"))
        changed_files = len(self._git_read(workspace, "diff", "--name-only", f"{base_commit}..HEAD", "--").splitlines()) if commit_count else 0
        return PullRequestState(
            session_id=session.id,
            repository=repository,
            branch=branch,
            base=base,
            head_sha=head_sha,
            commit_count=commit_count,
            changed_files=changed_files,
        )

    def _repository_for_session(self, session: CodingSession) -> str:
        repository_root = Path(session.workspace_repository_root).expanduser().resolve()
        if not repository_root.is_dir():
            raise CodingGitHubActionError(
                "CODING_REPOSITORY_UNAVAILABLE",
                "The coding repository is unavailable.",
                unavailable=True,
            )
        source_root = Path(self._git_read(repository_root, "rev-parse", "--show-toplevel")).resolve()
        if source_root != repository_root:
            raise CodingGitHubActionError(
                "WRONG_REPOSITORY",
                "The coding session no longer points at its canonical repository.",
            )
        remote = self._git_read(repository_root, "remote", "get-url", "origin")
        return self._repository_from_remote(remote)

    def _git_read(self, cwd: Path, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *args],
                capture_output=True,
                text=True,
                timeout=self._settings_provider().mcp_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CodingGitHubActionError(
                "CODING_REPOSITORY_UNAVAILABLE",
                "The coding repository could not be inspected.",
                unavailable=True,
            ) from exc
        if result.returncode != 0:
            raise CodingGitHubActionError(
                "CODING_REPOSITORY_UNAVAILABLE",
                "The coding repository could not be inspected.",
                unavailable=True,
            )
        return (result.stdout or "").strip()

    def _default_base(self, repository_root: Path) -> str:
        try:
            remote_head = self._git_read(repository_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        except CodingGitHubActionError:
            remote_head = ""
        if remote_head.startswith("origin/"):
            return remote_head.removeprefix("origin/")
        for candidate in ("main", "master"):
            try:
                self._git_read(repository_root, "rev-parse", "--verify", f"refs/remotes/origin/{candidate}")
                return candidate
            except CodingGitHubActionError:
                continue
        raise CodingGitHubActionError(
            "CODING_BASE_UNAVAILABLE",
            "The repository default branch is unavailable.",
            unavailable=True,
        )

    @staticmethod
    def _github_token(settings: Any) -> str:
        return str(
            getattr(settings, "github_mcp_token", "")
            or getattr(settings, "github_pat", "")
            or os.environ.get("GITHUB_PAT", "")
            or os.environ.get("GITHUB_TOKEN", "")
        ).strip()

    @staticmethod
    def _pull_number(arguments: dict[str, Any]) -> int:
        try:
            value = int(arguments.get("pull_number"))
        except (TypeError, ValueError) as exc:
            raise CodingGitHubActionError("INVALID_ACTION_ARGUMENTS", "A pull-request number is required.") from exc
        if value < 1:
            raise CodingGitHubActionError("INVALID_ACTION_ARGUMENTS", "A pull-request number is required.")
        return value

    @staticmethod
    def _normalize_repository(value: Any) -> str:
        repository = str(value or "").strip().removesuffix(".git").strip("/")
        if not repository:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise CodingGitHubActionError("INVALID_ACTION_ARGUMENTS", "Repository must use owner/name format.")
        return repository

    @classmethod
    def _repository_from_remote(cls, remote: str) -> str:
        match = _GITHUB_REMOTE.fullmatch(str(remote or "").strip())
        if not match:
            raise CodingGitHubActionError(
                "GITHUB_REPOSITORY_UNAVAILABLE",
                "The coding session origin is not a GitHub repository.",
                unavailable=True,
            )
        return match.group("repo").removesuffix(".git")

    @staticmethod
    def _validate_requested_target(arguments: dict[str, Any], state: PullRequestState) -> None:
        requested_repository = CodingGitHubActionService._normalize_repository(arguments.get("repository"))
        if requested_repository and requested_repository.casefold() != state.repository.casefold():
            raise CodingGitHubActionError(
                "WRONG_REPOSITORY",
                "The requested repository does not match the coding session.",
            )
        requested_branch = str(arguments.get("branch") or "").strip()
        if requested_branch and requested_branch != state.branch:
            raise CodingGitHubActionError(
                "WRONG_BRANCH",
                "The requested branch does not match the coding session.",
            )
        requested_base = str(arguments.get("base") or "").strip()
        if requested_base and requested_base != state.base:
            raise CodingGitHubActionError(
                "WRONG_BASE_BRANCH",
                "The requested base does not match the repository default branch.",
            )

    @staticmethod
    def _require_connector_success(text: str, *, operation: str) -> None:
        normalized = str(text or "").casefold()
        failure_markers = (" skipped:", " requires ", " failed:", " timed out", " is not allowed", "does not expose")
        if not normalized or any(marker in normalized for marker in failure_markers):
            raise CodingGitHubActionError(
                "GITHUB_READ_FAILED" if operation == "read" else "PR_CREATION_FAILED",
                "GitHub could not read the pull request." if operation == "read" else "GitHub could not create the pull request.",
                unavailable=operation == "read",
            )

    @staticmethod
    def _failed_result(value: Any) -> bool:
        normalized = str(value or "").casefold()
        return not normalized or "failed" in normalized or "requires git_tool_allow_writes" in normalized

    @staticmethod
    def _pull_url(value: Any) -> str:
        match = _PULL_URL.search(str(value or ""))
        return match.group(0).rstrip(".,)") if match else ""

    @staticmethod
    def _default_title(branch: str) -> str:
        value = branch.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
        return value[:1].upper() + value[1:] if value else "Coding workspace changes"

    @staticmethod
    def _session_summary(session: CodingSession) -> dict[str, Any]:
        return {
            "id": session.id,
            "title": session.title,
            "provider": session.provider.value,
            "status": session.status,
            "workspace_kind": session.workspace_kind.value,
            "branch": session.workspace_branch,
        }


def coding_github_action_definitions() -> list[AppActionDefinition]:
    result_schema = {"type": "object", "required": ["changed"]}
    return [
        AppActionDefinition(
            id=CODING_WORKSPACE_OPEN_ACTION_ID,
            version="1",
            owner="coding",
            title="Open coding workspace",
            description="Open the coding workspace or a saved coding conversation.",
            scope="application",
            access_class=CapabilityAccess.READ.value,
            confirmation_rule="none",
            executor_location="client",
            supports_undo=False,
            idempotent=True,
            argument_schema={
                "type": "object",
                "properties": {"session": {"type": "string"}, "session_id": {"type": "string"}},
                "additionalProperties": False,
            },
            result_schema=result_schema,
            ui_reference="coding-workspace",
            audit_label="coding.workspace.open",
        ),
        AppActionDefinition(
            id=GITHUB_PULL_REQUEST_OPEN_ACTION_ID,
            version="1",
            owner="github",
            title="Open pull request",
            description="Read an existing GitHub pull request and optionally open its URL.",
            scope="project",
            access_class=CapabilityAccess.READ.value,
            confirmation_rule="none",
            executor_location="server",
            supports_undo=False,
            idempotent=True,
            argument_schema={
                "type": "object",
                "properties": {
                    "pull_number": {"type": "integer", "minimum": 1},
                    "repository": {"type": "string"},
                    "session_id": {"type": "string"},
                    "open": {"type": "boolean"},
                },
                "required": ["pull_number"],
                "additionalProperties": False,
            },
            result_schema=result_schema,
            ui_reference="github-pull-request",
            audit_label="github.pull_request.open",
        ),
        AppActionDefinition(
            id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID,
            version="1",
            owner="github",
            title="Create pull request",
            description="Publish the current coding-session branch and create a GitHub pull request.",
            scope="project",
            access_class=CapabilityAccess.EXTERNAL_WRITE.value,
            confirmation_rule="operation_bound",
            executor_location="server",
            supports_undo=False,
            idempotent=False,
            argument_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "repository": {"type": "string"},
                    "branch": {"type": "string"},
                    "base": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "draft": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            result_schema=result_schema,
            ui_reference="github-pull-request",
            audit_label="github.pull_request.create",
        ),
    ]
