"""Model access to terminal commands, gated by the user's confirmation.

The tool never runs anything by itself. The first call asks the user to confirm the
exact command in the app (``terminal.command.run``); the user's click runs it and
the output appears in the chat. Calling the tool again with the same arguments then
returns that confirmed run's output so the agent can continue from it.
"""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import tool

from agent.app_actions.terminal_commands import (
    TERMINAL_COMMAND_RUN_ACTION_ID,
    TerminalCommandError,
    command_key,
    normalize_arguments,
    terminal_results,
)


@tool
def run_command(
    command: str,
    cwd: str = "",
    shell: Literal["powershell", "cmd", "bash", ""] = "",
    timeout_seconds: int = 120,
) -> str:
    """Run a shell command on the user's computer (PowerShell by default on Windows).

    If the user pastes a skill install command (`npx skills add ...`, `clawhub install ...`),
    pass it here unchanged: Vellum installs that skill into its own skills folder instead
    of running it in a shell.

    Depending on the approval mode the user picked in the composer, a command may run
    at once (status "completed"). Otherwise the first call shows them the exact command
    and returns status "awaiting_confirmation". Then stop and tell the user, in one or
    two sentences, what the command does and that they can click Run command. After
    they confirm, the output is shown in the chat; when they ask you to continue, call
    run_command again with exactly the same arguments to read the exit code and
    output (it does not run a second time). Use an absolute `cwd`; it defaults to the
    user's home folder. Prefer read-only commands, and never use this to read or
    print secrets, passwords or keys.
    """
    from agent.tools.app_actions import _SESSION, app_action

    arguments = {"command": command, "cwd": cwd, "shell": shell, "timeout_seconds": timeout_seconds}
    try:
        normalized = normalize_arguments(arguments)
    except TerminalCommandError as exc:
        return json.dumps({"status": "failed", "message": str(exc)})
    session = _SESSION.get()
    conversation_id = str(getattr(getattr(session, "context", None), "invocation_conversation_id", "") or "")
    finished = terminal_results().take(command_key(conversation_id, normalized))
    if finished is not None:
        return json.dumps({"status": "completed", **finished})
    from agent.terminal.approval import runs_without_asking

    if runs_without_asking(normalized["command"]):
        # The user chose Approve for me (read-only commands) or Full access in the composer.
        from agent.app_actions.models import AppActionContext
        from agent.app_actions.terminal_commands import execute_terminal_action

        context = getattr(session, "context", None) or AppActionContext(source="nlp")
        try:
            result = execute_terminal_action(TERMINAL_COMMAND_RUN_ACTION_ID, normalized, context)
        except TerminalCommandError as exc:
            return json.dumps({"status": "failed", "message": str(exc)})
        terminal_results().take(command_key(conversation_id, normalized))  # already returned here
        return json.dumps({"status": "completed", "approved_by": "approval mode",
                           **{k: v for k, v in result.items() if not k.startswith("_") and k != "changed"}})
    receipt = json.loads(app_action.invoke({
        "operation": "execute",
        "action_id": TERMINAL_COMMAND_RUN_ACTION_ID,
        "arguments": normalized,
    }))
    if receipt.get("status") == "confirmation_required":
        return json.dumps({
            "status": "awaiting_confirmation",
            "command": normalized["command"],
            "cwd": normalized["cwd"],
            "shell": normalized["shell"],
            "message": ("The user was asked to confirm this command in Vellum. Stop here: say what it will do. "
                        "After they confirm and ask you to continue, call run_command again with the same "
                        "arguments to read its output."),
        })
    return json.dumps({"status": receipt.get("status", "failed"),
                       "message": receipt.get("message") or "The command could not be prepared."})
