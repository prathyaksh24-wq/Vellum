"""Controlled local Git operations for the current checkout."""

from __future__ import annotations

from pathlib import Path
import subprocess

from langchain_core.tools import tool

from agent.config import get_settings

READ_ACTIONS = {
    "status": ["git", "status", "--short"],
    "log": ["git", "log", "--oneline", "-20"],
    "branch": ["git", "branch", "--show-current"],
}


def _writes_allowed() -> bool:
    return get_settings().git_tool_allow_writes


def _repo_path(repo_path: str) -> Path:
    candidate = Path(repo_path or ".").expanduser().resolve()
    if not (candidate / ".git").exists():
        raise ValueError(f"Not a git repository: {candidate}")
    return candidate


def _run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=get_settings().mcp_timeout_seconds,
    )
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return f"Git command failed ({result.returncode}): {output}"
    return output or "Git command completed."


@tool
def git_action(
    action: str,
    repo_path: str = ".",
    message: str = "",
    remote: str = "origin",
    branch: str = "",
) -> str:
    """Run controlled local Git actions: status, log, branch, pull, commit, push.

    pull/commit/push require GIT_TOOL_ALLOW_WRITES=true. commit stages all
    current changes and uses the provided message.
    """

    normalized = action.strip().casefold().replace("-", "_")
    try:
        repo = _repo_path(repo_path)
    except ValueError as exc:
        return str(exc)

    if normalized in READ_ACTIONS:
        return _run(READ_ACTIONS[normalized], repo)

    if normalized in {"pull", "commit", "push"} and not _writes_allowed():
        return f"Git action '{normalized}' requires GIT_TOOL_ALLOW_WRITES=true."

    if normalized == "pull":
        return _run(["git", "pull", remote], repo)
    if normalized == "commit":
        if not message.strip():
            return "Git commit requires a message."
        add_result = _run(["git", "add", "-A"], repo)
        if add_result.startswith("Git command failed"):
            return add_result
        return _run(["git", "commit", "-m", message.strip()], repo)
    if normalized == "push":
        target_branch = branch.strip()
        if target_branch.startswith(":"):
            return "Git push refuses delete-style refs."
        command = ["git", "push", remote]
        if target_branch:
            command.append(target_branch)
        return _run(command, repo)

    return f"Unsupported Git action: {normalized}."
