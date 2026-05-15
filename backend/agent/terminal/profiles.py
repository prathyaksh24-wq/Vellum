from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess


DEFAULT_CWD = Path(__file__).resolve().parents[3]

PROFILE_ALIASES = {
    "powershell": "powershell",
    "ps": "powershell",
    "cmd": "cmd",
    "pwsh": "pwsh",
    "ubuntu": "wsl",
    "wsl": "wsl",
    "bash": "git-bash",
    "git-bash": "git-bash",
    "mac": "macos",
    "macos": "macos",
}


@dataclass(frozen=True)
class TerminalProfile:
    id: str
    label: str
    command: str
    args: list[str]
    cwd: Path
    available: bool
    reason: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "available": self.available,
            "reason": self.reason,
            "cwd": str(self.cwd),
        }


def _which(name: str) -> str | None:
    return shutil.which(name)


def _wsl_distros() -> list[str]:
    if not _which("wsl.exe"):
        return []
    try:
        result = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip().replace("\x00", "") for line in result.stdout.splitlines() if line.strip()]


def _git_bash_path() -> str | None:
    path_value = _which("bash.exe")
    if path_value:
        return path_value
    if not _which("git.exe"):
        return None
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def list_profiles() -> list[TerminalProfile]:
    cwd = DEFAULT_CWD
    powershell_path = _which("powershell.exe") or "powershell.exe"
    cmd_path = _which("cmd.exe") or "cmd.exe"
    pwsh_path = _which("pwsh.exe")
    wsl_path = _which("wsl.exe")
    wsl_distros = _wsl_distros()
    git_bash_path = _git_bash_path()
    macos_target = os.environ.get("VELLUM_MACOS_SSH_TARGET", "").strip()

    return [
        TerminalProfile("powershell", "PowerShell", powershell_path, ["-NoLogo"], cwd, True),
        TerminalProfile("cmd", "CMD", cmd_path, [], cwd, True),
        TerminalProfile(
            "pwsh",
            "PowerShell Core",
            pwsh_path or "pwsh.exe",
            ["-NoLogo"],
            cwd,
            pwsh_path is not None,
            None if pwsh_path else "pwsh.exe was not found on PATH.",
        ),
        TerminalProfile(
            "wsl",
            "WSL Ubuntu",
            wsl_path or "wsl.exe",
            ["-d", "Ubuntu"],
            cwd,
            wsl_path is not None and "Ubuntu" in wsl_distros,
            None if wsl_path and "Ubuntu" in wsl_distros else "WSL Ubuntu is not available.",
        ),
        TerminalProfile(
            "git-bash",
            "Git Bash",
            git_bash_path or "bash.exe",
            ["--login"],
            cwd,
            git_bash_path is not None,
            None if git_bash_path else "Git Bash was not found.",
        ),
        TerminalProfile(
            "macos",
            "macOS SSH",
            "ssh",
            [macos_target] if macos_target else [],
            cwd,
            bool(macos_target),
            None if macos_target else "macOS SSH target is not configured. Set VELLUM_MACOS_SSH_TARGET.",
        ),
    ]


def get_profile(profile_id: str) -> TerminalProfile | None:
    canonical = PROFILE_ALIASES.get(profile_id.casefold())
    if not canonical:
        return None
    return next((profile for profile in list_profiles() if profile.id == canonical), None)
