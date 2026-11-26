"""How terminal commands are approved, chosen in the composer.

- ``ask``  (Ask for approval): every command waits for the user's click.
- ``auto`` (Approve for me): read-only commands run at once; anything that could
  change files, settings, processes or the network still asks.
- ``full`` (Full access): every command runs without asking.

Only the user can change the mode (from the UI); the agent cannot raise its own access.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import threading

MODES = ("ask", "auto", "full")
DEFAULT_MODE = "ask"
_LOCK = threading.Lock()


def _path() -> Path:
    from agent.config import REPO_ROOT

    return Path(REPO_ROOT) / "data" / "terminal-approval.json"


def get_mode() -> str:
    try:
        mode = json.loads(_path().read_text(encoding="utf-8")).get("mode")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    with _LOCK:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mode": mode}), encoding="utf-8")
    return mode


# Commands that only read. Anything else (or any of these with redirection,
# chaining into another command, or a destructive flag) is "potentially unsafe".
_READ_ONLY = {
    "get-childitem", "gci", "ls", "dir", "get-content", "gc", "cat", "type", "echo", "write-output",
    "pwd", "get-location", "cd", "set-location", "where", "where.exe", "which", "whoami", "hostname",
    "date", "get-date", "test-path", "select-string", "findstr", "sort", "sort-object", "measure-object",
    "select-object", "where-object", "format-table", "format-list", "out-string", "get-item", "get-process",
    "get-service", "get-command", "get-help", "get-netipconfiguration", "ipconfig", "systeminfo", "tree",
    "grep", "rg", "head", "tail", "wc", "uname", "env", "printenv", "get-childitem", "resolve-path",
    "get-filehash", "get-itemproperty", "get-computerinfo", "ver", "node", "python", "py", "npm", "pip",
    "git", "dotnet", "java", "go", "cargo", "rustc", "ollama",
}
_READ_ONLY_SUBCOMMANDS = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "describe", "ls-files", "blame", "tag"},
    "npm": {"ls", "list", "view", "outdated", "--version", "-v", "config"},
    "pip": {"list", "show", "freeze", "--version"},
    "node": {"--version", "-v", "-e", "-p"},
    "python": {"--version", "-v", "-V"},
    "py": {"--version", "-V", "--list"},
    "dotnet": {"--version", "--info", "--list-sdks"},
    "java": {"-version", "--version"},
    "go": {"version", "env"},
    "cargo": {"--version", "tree"},
    "rustc": {"--version"},
    "ollama": {"list", "ps", "show", "--version"},
}
_UNSAFE_TOKENS = re.compile(
    r"(>|>>|\b(rm|rmdir|del|erase|remove-item|ri|move-item|mv|copy-item|cp|rename-item|ren|set-content|"
    r"add-content|out-file|new-item|ni|mkdir|md|stop-process|kill|taskkill|shutdown|restart-computer|"
    r"format|diskpart|reg|set-itemproperty|invoke-webrequest|iwr|curl|wget|invoke-expression|iex|start-process|"
    r"sudo|chmod|chown|install|uninstall|-delete|-exec)\b)",
    re.IGNORECASE,
)


def is_read_only(command: str) -> bool:
    """A conservative check: True only for commands made of known read-only parts."""
    text = command.strip()
    if not text or _UNSAFE_TOKENS.search(text) or "`" in text or "$(" in text:
        return False
    for segment in re.split(r"\|\||&&|;|\|", text):
        words = segment.strip().split()
        if not words:
            continue
        head = words[0].casefold().removesuffix(".exe")
        if head not in _READ_ONLY:
            return False
        allowed = _READ_ONLY_SUBCOMMANDS.get(head)
        if allowed is not None:
            if len(words) < 2 or words[1].casefold() not in allowed:
                return False
            if head == "node" and words[1] in {"-e", "-p"}:
                return False  # arbitrary code
    return True


def runs_without_asking(command: str, *, mode: str | None = None) -> bool:
    mode = mode or get_mode()
    if mode == "full":
        return True
    if mode == "auto":
        from agent.app_actions.skill_install_commands import SkillInstallCommandError, skill_install_identifier

        try:
            if skill_install_identifier(command):
                return False  # installing something always asks in this mode
        except SkillInstallCommandError:
            return False
        return is_read_only(command)
    return False
