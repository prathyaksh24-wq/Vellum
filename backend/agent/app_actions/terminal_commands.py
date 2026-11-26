"""Run a terminal command on this computer, only after the user confirms it.

``terminal.command.run`` is operation-bound: the confirmation the user sees names
the exact command, working folder and shell, and only that exact request can run.
Nothing executes on the model's say-so. The result (exit code and output) is kept
per conversation for a while so the agent can read what the confirmed run printed
on its next turn without running it again.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.tools.registry import CapabilityAccess

TERMINAL_COMMAND_RUN_ACTION_ID = "terminal.command.run"
TERMINAL_APPROVAL_SET_ACTION_ID = "terminal.approval.set"
TERMINAL_ACTION_IDS = frozenset({TERMINAL_COMMAND_RUN_ACTION_ID})
TERMINAL_SETTING_ACTION_IDS = frozenset({TERMINAL_APPROVAL_SET_ACTION_ID})

DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 600
MAX_OUTPUT_CHARS = 20_000
MAX_COMMAND_CHARS = 8_000
RESULT_TTL = timedelta(hours=2)
MAX_RESULTS = 100
SHELLS = ("powershell", "cmd", "bash")


class TerminalCommandError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


def default_shell() -> str:
    return "powershell" if os.name == "nt" else "bash"


def normalize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validated, canonical arguments; the confirmation is bound to exactly these."""
    command = str(arguments.get("command") or "").strip()
    if not command:
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", "A command is required.")
    if len(command) > MAX_COMMAND_CHARS:
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", "The command is too long.")
    shell = str(arguments.get("shell") or default_shell()).strip().lower()
    if shell not in SHELLS:
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", f"Shell must be one of: {', '.join(SHELLS)}.")
    raw_cwd = str(arguments.get("cwd") or "").strip()
    cwd = Path(raw_cwd).expanduser() if raw_cwd else Path.home()
    if not cwd.is_absolute():
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", "The working folder must be an absolute path.")
    if not cwd.is_dir():
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", f"The working folder does not exist: {cwd}")
    try:
        timeout = int(arguments.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", "timeout_seconds must be a number.") from None
    timeout = max(1, min(timeout, MAX_TIMEOUT_SECONDS))
    return {"command": command, "cwd": str(cwd.resolve()), "shell": shell, "timeout_seconds": timeout}


def command_key(conversation_id: str, arguments: dict[str, Any]) -> str:
    material = "\x1f".join([conversation_id or "", arguments["command"], arguments["cwd"], arguments["shell"]])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class TerminalResults:
    """Recent confirmed runs, per conversation, held in memory only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def put(self, key: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = {**result, "_stored_at": datetime.now(UTC)}
            self._items.move_to_end(key)
            while len(self._items) > MAX_RESULTS:
                self._items.popitem(last=False)

    def take(self, key: str) -> dict[str, Any] | None:
        """The stored run for this exact request, consumed once so a repeat request asks again."""
        with self._lock:
            item = self._items.pop(key, None)
        if item is None or datetime.now(UTC) - item["_stored_at"] > RESULT_TTL:
            return None
        return {k: v for k, v in item.items() if k != "_stored_at"}


_RESULTS = TerminalResults()


def terminal_results() -> TerminalResults:
    return _RESULTS


def _argv(shell: str, command: str) -> list[str]:
    if shell == "powershell":
        executable = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    if shell == "cmd":
        return [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c", command]
    executable = shutil.which("bash") or "/bin/bash"
    return [executable, "-lc", command]


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    half = MAX_OUTPUT_CHARS // 2
    return text[:half] + "\n… [output truncated] …\n" + text[-half:], True


def run_command(arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute already-normalized arguments and report exit code and output."""
    started = time.monotonic()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            _argv(arguments["shell"], arguments["command"]),
            cwd=arguments["cwd"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=arguments["timeout_seconds"],
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        exit_code: int | None = completed.returncode
        stdout, stderr, timed_out = completed.stdout or "", completed.stderr or "", False
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        timed_out = True
    except OSError as exc:
        raise TerminalCommandError("TERMINAL_UNAVAILABLE", f"The shell could not start: {exc}", unavailable=True) from exc
    stdout, stdout_truncated = _clip(stdout)
    stderr, stderr_truncated = _clip(stderr)
    return {
        "command": arguments["command"],
        "cwd": arguments["cwd"],
        "shell": arguments["shell"],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 2),
        "stdout": stdout,
        "stderr": stderr,
        "truncated": stdout_truncated or stderr_truncated,
    }


def summary_message(result: dict[str, Any]) -> str:
    if result["timed_out"]:
        status = f"stopped after {result['duration_seconds']}s (time limit)"
    else:
        status = f"exit code {result['exit_code']}"
    output = (result["stdout"] or result["stderr"] or "").strip()
    tail = output[-600:]
    return f"Ran `{result['command'][:200]}` — {status}." + (f"\n\n{tail}" if tail else "")


def set_approval_mode(arguments: dict[str, Any], context: AppActionContext) -> dict[str, Any]:
    """Only the user, from the app, may change how commands are approved."""
    from agent.terminal.approval import MODES, get_mode, set_mode

    if context.source != "ui":
        raise TerminalCommandError("ACTION_NOT_AUTHORIZED",
                                   "Only you can change command approval, from the composer.", unavailable=True)
    mode = str(arguments.get("mode") or "").strip()
    if mode not in MODES:
        raise TerminalCommandError("INVALID_ACTION_ARGUMENTS", f"Mode must be one of: {', '.join(MODES)}.")
    previous = get_mode()
    set_mode(mode)
    labels = {"ask": "Ask for approval", "auto": "Approve for me", "full": "Full access"}
    return {"changed": previous != mode, "mode": mode, "_target_kind": "terminal", "_target_id": "approval",
            "_message": f"Command approval: {labels[mode]}."}


def execute_terminal_action(action_id: str, arguments: dict[str, Any], context: AppActionContext) -> dict[str, Any]:
    if action_id == TERMINAL_APPROVAL_SET_ACTION_ID:
        return set_approval_mode(arguments, context)
    if action_id != TERMINAL_COMMAND_RUN_ACTION_ID:
        raise TerminalCommandError("ACTION_NOT_FOUND", "Unknown terminal action.", unavailable=True)
    normalized = normalize_arguments(arguments)
    identifier = _skill_identifier(normalized["command"])
    result = _install_skill(normalized, identifier) if identifier else run_command(normalized)
    conversation_id = str(context.invocation_conversation_id or "")
    terminal_results().put(command_key(conversation_id, normalized), result)
    return {
        "changed": True,
        **result,
        "_target_kind": "terminal",
        "_target_id": normalized["cwd"],
        "_message": summary_message(result),
    }


def _skill_identifier(command: str) -> str | None:
    from agent.app_actions.skill_install_commands import SkillInstallCommandError, skill_install_identifier

    try:
        return skill_install_identifier(command)
    except SkillInstallCommandError as exc:
        raise TerminalCommandError("SKILL_INSTALL_UNRESOLVED", str(exc)) from exc


def _install_skill(arguments: dict[str, Any], identifier: str) -> dict[str, Any]:
    """A skill-install command installs into Vellum's own skills folder, not another agent's."""
    from agent.app_actions.skill_install_commands import install_into_vellum

    started = time.monotonic()
    try:
        applied = install_into_vellum(identifier)
        exit_code, stdout, stderr = 0, (f"Installed skill '{applied.get('name') or identifier}' into Vellum "
                                        f"({identifier}). It now shows in your Skills."), ""
    except Exception as exc:  # noqa: BLE001 — reported like a failed command
        exit_code, stdout, stderr = 1, "", f"Could not install {identifier}: {exc}"
    return {
        "command": arguments["command"], "cwd": arguments["cwd"], "shell": arguments["shell"],
        "exit_code": exit_code, "timed_out": False, "duration_seconds": round(time.monotonic() - started, 2),
        "stdout": stdout, "stderr": stderr, "truncated": False, "skill_identifier": identifier,
    }


def confirmation_message(arguments: dict[str, Any]) -> str:
    normalized = normalize_arguments(arguments)
    identifier = _skill_identifier(normalized["command"])
    if identifier:
        return (f"Install the skill {identifier} into Vellum's skills folder?\n\n"
                f"Requested with: {normalized['command']}")
    return (f"Run this {normalized['shell']} command in {normalized['cwd']}?\n\n"
            f"{normalized['command']}")


def terminal_action_definitions() -> list[AppActionDefinition]:
    return [AppActionDefinition(
        id=TERMINAL_COMMAND_RUN_ACTION_ID,
        version="1",
        owner="terminal",
        title="Run a terminal command",
        description=("Run one shell command on this computer after the user confirms the exact command. "
                     "Returns exit code, stdout and stderr."),
        scope="device",
        access_class=CapabilityAccess.WRITE.value,
        confirmation_rule="operation_bound",
        executor_location="server",
        supports_undo=False,
        idempotent=False,
        argument_schema={
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string", "description": "The full command line to run."},
                "cwd": {"type": "string", "description": "Absolute working folder; defaults to the user's home folder."},
                "shell": {"enum": list(SHELLS), "description": "Defaults to PowerShell on Windows, bash elsewhere."},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT_SECONDS},
            },
        },
        result_schema={"type": "object", "required": ["exit_code", "stdout", "stderr"]},
        ui_reference="terminal",
        audit_label=TERMINAL_COMMAND_RUN_ACTION_ID,
    ), AppActionDefinition(
        id=TERMINAL_APPROVAL_SET_ACTION_ID,
        version="1",
        owner="terminal",
        title="Set command approval",
        description=("Choose how Vellum's terminal commands are approved: ask (every command), "
                     "auto (read-only commands run; others ask) or full (no asking). Only the user can set it."),
        scope="device",
        access_class=CapabilityAccess.WRITE.value,
        confirmation_rule="current_user_intent",
        executor_location="server",
        supports_undo=False,
        idempotent=True,
        argument_schema={"type": "object", "required": ["mode"],
                         "properties": {"mode": {"enum": ["ask", "auto", "full"]}}},
        result_schema={"type": "object", "required": ["mode"]},
        ui_reference="composer",
        audit_label=TERMINAL_APPROVAL_SET_ACTION_ID,
    )]
