from pathlib import Path
from types import SimpleNamespace

from agent.tools import git_local


def make_repo(path: Path) -> Path:
    (path / ".git").mkdir()
    return path


def test_git_status_runs_in_repo(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, cwd=None, capture_output=None, text=None, timeout=None):
        seen["command"] = command
        seen["cwd"] = cwd
        return SimpleNamespace(returncode=0, stdout="clean", stderr="")

    monkeypatch.setattr(git_local.subprocess, "run", fake_run)

    result = git_local.git_action.func(action="status", repo_path=str(make_repo(tmp_path)))

    assert result == "clean"
    assert seen["command"] == ["git", "status", "--short"]
    assert seen["cwd"] == Path(tmp_path).resolve()


def test_git_commit_requires_write_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(git_local, "_writes_allowed", lambda: False)

    result = git_local.git_action.func(action="commit", repo_path=str(make_repo(tmp_path)), message="test")

    assert "requires GIT_TOOL_ALLOW_WRITES=true" in result


def test_git_commit_runs_add_and_commit_when_writes_allowed(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(git_local, "_writes_allowed", lambda: True)

    def fake_run(command, cwd=None, capture_output=None, text=None, timeout=None):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(git_local.subprocess, "run", fake_run)

    result = git_local.git_action.func(action="commit", repo_path=str(make_repo(tmp_path)), message="ship it")

    assert result == "ok"
    assert commands == [["git", "add", "-A"], ["git", "commit", "-m", "ship it"]]


def test_git_delete_remote_branch_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(git_local, "_writes_allowed", lambda: True)

    result = git_local.git_action.func(action="push", repo_path=str(make_repo(tmp_path)), branch=":main")

    assert "refuses delete-style refs" in result
