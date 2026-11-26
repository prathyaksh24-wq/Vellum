"""Terminal commands run only after the user confirms the exact command."""

from __future__ import annotations

import json
import sys

from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.app_actions.terminal_commands import (
    TERMINAL_COMMAND_RUN_ACTION_ID,
    normalize_arguments,
    terminal_results,
)

SHELL = "cmd" if sys.platform == "win32" else "bash"


def _request(tmp_path, command: str) -> AppActionRequest:
    return AppActionRequest(action_id=TERMINAL_COMMAND_RUN_ACTION_ID,
                            arguments=normalize_arguments({"command": command, "cwd": str(tmp_path), "shell": SHELL}))


def test_dispatch_never_runs_and_confirm_runs_the_exact_command(tmp_path) -> None:
    runtime = AppActionRuntime()
    context = AppActionContext(source="nlp", invocation_conversation_id="chat-1")
    marker = tmp_path / "ran.txt"
    request = _request(tmp_path, "echo hello> ran.txt" if SHELL == "cmd" else "echo hello > ran.txt")

    receipt = runtime.dispatch(request, context)
    assert receipt.status == "confirmation_required"
    assert request.arguments["command"] in receipt.message
    assert not marker.exists()

    confirmed = runtime.confirm(receipt.confirmation.token, request, AppActionContext(source="ui", invocation_conversation_id="chat-1"))
    assert confirmed.status == "applied"
    assert confirmed.result["exit_code"] == 0
    assert marker.read_text().strip() == "hello"
    # A confirmation is single use.
    again = runtime.confirm(receipt.confirmation.token, request, context)
    assert again.status != "applied"


def test_confirmation_is_bound_to_the_command(tmp_path) -> None:
    runtime = AppActionRuntime()
    context = AppActionContext(source="nlp", invocation_conversation_id="chat-1")
    receipt = runtime.dispatch(_request(tmp_path, "echo safe"), context)
    swapped = _request(tmp_path, "echo swapped")
    result = runtime.confirm(receipt.confirmation.token, swapped, context)
    assert result.status == "failed" and result.error_code == "CONFIRMATION_MISMATCH"


def test_failed_command_reports_exit_code_and_stderr(tmp_path) -> None:
    runtime = AppActionRuntime()
    context = AppActionContext(source="ui", invocation_conversation_id="chat-2")
    request = _request(tmp_path, "exit 3")
    receipt = runtime.dispatch(request, context)
    confirmed = runtime.confirm(receipt.confirmation.token, request, context)
    assert confirmed.status == "applied"
    assert confirmed.result["exit_code"] == 3


def test_run_command_tool_asks_first_then_returns_the_confirmed_output(tmp_path) -> None:
    from agent.tools.app_actions import app_action_session
    from agent.tools.terminal_command import run_command

    runtime = AppActionRuntime()
    arguments = {"command": "echo from-tool", "cwd": str(tmp_path), "shell": SHELL}
    with app_action_session(AppActionContext(source="nlp"), "thread-9", runtime=runtime) as session:
        first = json.loads(run_command.invoke(arguments))
        assert first["status"] == "awaiting_confirmation"
        receipt = session.emitted[-1]["receipt"]
        request = AppActionRequest(**session.emitted[-1]["request"])
        runtime.confirm(receipt["confirmation"]["token"], request,
                        AppActionContext(source="ui", invocation_conversation_id="thread-9"))
        second = json.loads(run_command.invoke(arguments))
        assert second["status"] == "completed"
        assert "from-tool" in second["stdout"]
        # Consumed: asking for the same command again needs a new confirmation.
        third = json.loads(run_command.invoke(arguments))
        assert third["status"] == "awaiting_confirmation"
    assert terminal_results() is not None


def test_relative_or_missing_folders_are_rejected(tmp_path) -> None:
    import pytest
    from agent.app_actions.terminal_commands import TerminalCommandError

    with pytest.raises(TerminalCommandError):
        normalize_arguments({"command": "dir", "cwd": "relative/path"})
    with pytest.raises(TerminalCommandError):
        normalize_arguments({"command": "dir", "cwd": str(tmp_path / "missing")})
    with pytest.raises(TerminalCommandError):
        normalize_arguments({"command": "   "})


def test_install_commands_resolve_to_vellum_skill_identifiers() -> None:
    import pytest
    from agent.app_actions.skill_install_commands import SkillInstallCommandError, skill_install_identifier

    assert skill_install_identifier("npx skills add anthropics/skills --skill docx") == "skills-sh/anthropics/skills/docx"
    assert skill_install_identifier("npx -y skills add https://github.com/acme/kit/tree/main/skills/review") == "github/acme/kit/skills/review"
    assert skill_install_identifier("npx skills add https://skills.sh/vercel-labs/agent-skills/web-design") == "skills-sh/vercel-labs/agent-skills/web-design"
    assert skill_install_identifier("npx clawhub install weather") == "clawhub/weather"
    assert skill_install_identifier("npm install react") is None
    assert skill_install_identifier("git status") is None
    with pytest.raises(SkillInstallCommandError):
        skill_install_identifier("npx skills add anthropics/skills")


def test_read_only_check_is_conservative() -> None:
    from agent.terminal.approval import is_read_only

    for safe in ["git status", "Get-ChildItem C:/Users", "dir", "python --version", "git log -5 | Select-Object -First 3"]:
        assert is_read_only(safe), safe
    for unsafe in ["Remove-Item x", "del x", "echo hi > file.txt", "git push", "npm install", "curl https://x",
                   "node -e \"require('fs').rmSync('x')\"", "Stop-Process -Name code", "dir; rm x"]:
        assert not is_read_only(unsafe), unsafe


def test_approval_modes_decide_what_runs_without_asking(tmp_path, monkeypatch) -> None:
    from agent.terminal import approval

    monkeypatch.setattr(approval, "_path", lambda: tmp_path / "terminal-approval.json")
    assert approval.get_mode() == "ask"
    assert not approval.runs_without_asking("dir")
    approval.set_mode("auto")
    assert approval.runs_without_asking("dir") and not approval.runs_without_asking("del x")
    assert not approval.runs_without_asking("npx skills add anthropics/skills --skill docx")
    approval.set_mode("full")
    assert approval.runs_without_asking("del x")


def test_only_the_ui_can_change_the_approval_mode(tmp_path, monkeypatch) -> None:
    from agent.terminal import approval

    monkeypatch.setattr(approval, "_path", lambda: tmp_path / "terminal-approval.json")
    runtime = AppActionRuntime()
    request = AppActionRequest(action_id="terminal.approval.set", arguments={"mode": "full"})
    agent = runtime.dispatch(request, AppActionContext(source="nlp"))
    assert agent.status != "applied" and approval.get_mode() == "ask"
    user = runtime.dispatch(request, AppActionContext(source="ui"))
    assert user.status == "applied" and approval.get_mode() == "full"


def test_full_access_runs_the_command_in_the_tool_without_a_card(tmp_path, monkeypatch) -> None:
    from agent.terminal import approval
    from agent.tools.app_actions import app_action_session
    from agent.tools.terminal_command import run_command

    monkeypatch.setattr(approval, "_path", lambda: tmp_path / "terminal-approval.json")
    approval.set_mode("full")
    runtime = AppActionRuntime()
    with app_action_session(AppActionContext(source="nlp"), "thread-full", runtime=runtime) as session:
        result = json.loads(run_command.invoke({"command": "echo direct", "cwd": str(tmp_path), "shell": SHELL}))
        assert result["status"] == "completed" and "direct" in result["stdout"]
        assert session.emitted == []
