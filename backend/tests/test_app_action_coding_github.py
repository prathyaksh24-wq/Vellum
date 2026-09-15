from types import SimpleNamespace

from agent.app_actions.coding_github import (
    CODING_WORKSPACE_OPEN_ACTION_ID,
    GITHUB_PULL_REQUEST_CREATE_ACTION_ID,
    GITHUB_PULL_REQUEST_OPEN_ACTION_ID,
    CodingGitHubActionService,
    PullRequestState,
)
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.coding.models import AccessMode, CodingSession, ProviderName, WorkspaceKind


def _session(**updates) -> CodingSession:
    values = {
        "id": "session-1",
        "provider": ProviderName.codex,
        "cwd": "D:/worktrees/vellum/session-1",
        "access_mode": AccessMode.workspace_write,
        "title": "Fix issue 171",
        "status": "idle",
        "source_cwd": "D:/vellum",
        "workspace_kind": WorkspaceKind.git_worktree,
        "workspace_root": "D:/worktrees/vellum/session-1",
        "workspace_repository_root": "D:/vellum",
        "workspace_branch": "vellum/session/session-1",
        "workspace_base_commit": "abc123",
        "updated_at": "2026-09-15T12:00:00+00:00",
    }
    values.update(updates)
    return CodingSession(**values)


def _state(**updates) -> PullRequestState:
    values = {
        "session_id": "session-1",
        "repository": "prathyaksh24-wq/Vellum",
        "branch": "vellum/session/session-1",
        "base": "main",
        "head_sha": "def456",
        "commit_count": 2,
        "changed_files": 4,
    }
    values.update(updates)
    return PullRequestState(**values)


class FakeCodingService:
    def __init__(self, sessions=None):
        self._sessions = sessions if sessions is not None else [_session()]

    def list_sessions(self):
        return list(self._sessions)


def _settings(**updates):
    values = {
        "github_mcp_token": "token",
        "github_pat": "",
        "github_mcp_allow_writes": True,
        "git_tool_allow_writes": True,
        "mcp_timeout_seconds": 30,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _runtime(*, github_runner=None, git_writer=None, settings=None, states=None):
    state_values = iter(states) if states is not None else None

    def state_provider(_session):
        return next(state_values) if state_values is not None else _state()

    service = CodingGitHubActionService(
        coding_service=FakeCodingService(),
        github_runner=github_runner or (lambda _payload: "https://github.com/prathyaksh24-wq/Vellum/pull/201"),
        git_writer=git_writer or (lambda **_payload: "published"),
        settings_provider=lambda: settings or _settings(),
        repository_state_provider=state_provider,
        repository_provider=lambda _session: _state().repository,
    )
    return AppActionRuntime(coding_github_handler=service.execute)


def _context(source="nlp"):
    return AppActionContext(source=source, invocation_conversation_id="chat-1")


def test_catalog_exposes_coding_and_github_actions_only_when_owner_is_wired():
    wired = {definition.id: definition for definition in _runtime().catalog().actions}
    unwired = {definition.id for definition in AppActionRuntime().catalog().actions}

    assert wired[CODING_WORKSPACE_OPEN_ACTION_ID].access_class == "read"
    assert wired[GITHUB_PULL_REQUEST_OPEN_ACTION_ID].access_class == "read"
    assert wired[GITHUB_PULL_REQUEST_CREATE_ACTION_ID].access_class == "external_write"
    assert wired[GITHUB_PULL_REQUEST_CREATE_ACTION_ID].confirmation_rule == "operation_bound"
    assert CODING_WORKSPACE_OPEN_ACTION_ID not in unwired
    assert GITHUB_PULL_REQUEST_OPEN_ACTION_ID not in unwired
    assert GITHUB_PULL_REQUEST_CREATE_ACTION_ID not in unwired


def test_nlp_matches_workspace_read_and_pull_request_creation_without_catching_conversation():
    runtime = _runtime()

    assert runtime.match_submission("open coding workspace").action_id == CODING_WORKSPACE_OPEN_ACTION_ID
    coding_session = runtime.match_submission("open coding session Fix issue 171")
    assert coding_session.arguments == {"session": "Fix issue 171"}
    inspect = runtime.match_submission("inspect PR #192 in prathyaksh24-wq/Vellum")
    assert inspect.action_id == GITHUB_PULL_REQUEST_OPEN_ACTION_ID
    assert inspect.arguments == {
        "pull_number": 192,
        "open": False,
        "repository": "prathyaksh24-wq/vellum",
    }
    create = runtime.match_submission('create a draft PR titled "Expose coding actions"')
    assert create.action_id == GITHUB_PULL_REQUEST_CREATE_ACTION_ID
    assert create.arguments == {"draft": True, "title": "Expose coding actions"}
    assert runtime.match_submission("draft a PR").arguments == {"draft": True}
    assert runtime.match_submission("open a pull request") is None
    assert runtime.match_submission("What is a pull request?") is None


def test_open_coding_workspace_and_existing_pull_request_are_read_actions():
    seen = []

    def github(payload):
        seen.append(payload)
        return "PR data https://github.com/prathyaksh24-wq/Vellum/pull/192"

    runtime = _runtime(github_runner=github)
    workspace = runtime.dispatch(AppActionRequest(action_id=CODING_WORKSPACE_OPEN_ACTION_ID), _context())
    pull = runtime.dispatch(
        AppActionRequest(
            action_id=GITHUB_PULL_REQUEST_OPEN_ACTION_ID,
            arguments={"pull_number": 192, "repository": "prathyaksh24-wq/Vellum", "open": False},
        ),
        _context(),
    )

    assert workspace.status == "applied"
    assert workspace.result["navigation"]["url"] == "vellum-workspace.html?session=session-1"
    assert pull.status == "applied"
    assert pull.authorization.access_class == "read"
    assert pull.result["pull_request"]["url"].endswith("/pull/192")
    assert "navigation" not in pull.result
    assert seen == [{
        "action": "get_pull_request",
        "owner": "prathyaksh24-wq",
        "repo": "Vellum",
        "pull_number": 192,
    }]


def test_create_pull_request_requires_bound_confirmation_before_any_write():
    github_calls = []
    git_calls = []
    runtime = _runtime(
        github_runner=lambda payload: github_calls.append(payload) or "https://github.com/prathyaksh24-wq/Vellum/pull/201",
        git_writer=lambda **payload: git_calls.append(payload) or "published",
        states=[_state(), _state()],
    )
    request = AppActionRequest(
        action_id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID,
        arguments={"title": "Expose coding actions", "draft": True},
    )

    review = runtime.dispatch(request, _context())

    assert review.status == "confirmation_required"
    assert review.authorization.confirmation_required is True
    assert review.result["pull_request_review"]["repository"] == "prathyaksh24-wq/Vellum"
    assert github_calls == []
    assert git_calls == []

    created = runtime.confirm(review.confirmation.token, request, _context())

    assert created.status == "applied"
    assert created.authorization.access_class == "external_write"
    assert created.result["pull_request"]["url"].endswith("/pull/201")
    assert git_calls[0]["repo_path"] == "D:/worktrees/vellum/session-1"
    assert github_calls[0] == {
        "action": "create_pull_request",
        "owner": "prathyaksh24-wq",
        "repo": "Vellum",
        "title": "Expose coding actions",
        "body": "",
        "head": "vellum/session/session-1",
        "base": "main",
        "draft": True,
    }


def test_create_pull_request_rejects_wrong_repository_before_confirmation():
    runtime = _runtime()
    receipt = runtime.dispatch(
        AppActionRequest(
            action_id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID,
            arguments={"repository": "someone/other"},
        ),
        _context(),
    )

    assert receipt.status == "failed"
    assert receipt.error_code == "WRONG_REPOSITORY"
    assert receipt.confirmation is None


def test_create_pull_request_reports_missing_auth_and_disabled_writes_truthfully():
    missing_auth = _runtime(settings=_settings(github_mcp_token="", github_pat=""))
    github_disabled = _runtime(settings=_settings(github_mcp_allow_writes=False))
    git_disabled = _runtime(settings=_settings(git_tool_allow_writes=False))
    request = AppActionRequest(action_id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID)

    assert missing_auth.dispatch(request, _context()).error_code == "GITHUB_AUTH_UNAVAILABLE"
    assert github_disabled.dispatch(request, _context()).error_code == "GITHUB_WRITE_UNAVAILABLE"
    assert git_disabled.dispatch(request, _context()).error_code == "GIT_PUBLISH_UNAVAILABLE"


def test_confirmation_rejects_branch_changes_and_failed_publication():
    stale = _runtime(states=[_state(), _state(head_sha="changed")])
    request = AppActionRequest(action_id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID)
    review = stale.dispatch(request, _context())
    stale_receipt = stale.confirm(review.confirmation.token, request, _context())
    assert stale_receipt.status == "failed"
    assert stale_receipt.error_code == "STALE_ACTION_TARGET"

    github_calls = []
    failed = _runtime(
        github_runner=lambda payload: github_calls.append(payload) or "should not run",
        git_writer=lambda **_payload: "Git command failed (1): rejected",
        states=[_state(), _state()],
    )
    review = failed.dispatch(request, _context())
    failed_receipt = failed.confirm(review.confirmation.token, request, _context())
    assert failed_receipt.status == "failed"
    assert failed_receipt.error_code == "PR_PUBLICATION_FAILED"
    assert github_calls == []


def test_create_pull_request_requires_a_real_url_from_github():
    runtime = _runtime(
        github_runner=lambda _payload: "GitHub MCP create_pull_request completed.",
        states=[_state(), _state()],
    )
    request = AppActionRequest(action_id=GITHUB_PULL_REQUEST_CREATE_ACTION_ID)
    review = runtime.dispatch(request, _context())
    receipt = runtime.confirm(review.confirmation.token, request, _context())

    assert receipt.status == "failed"
    assert receipt.error_code == "PR_CREATION_FAILED"
