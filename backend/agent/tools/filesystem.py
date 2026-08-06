"""Filesystem tools backed by PowerShell CLI, restricted to the vault.

The browser cache directory (BROWSER_CACHE_DIR) is additionally readable so
the agent can page through truncated browser snapshots with read_file, the
same workflow Hermes uses for its ~/.hermes/cache/web snapshots.

No MCP server is involved: every operation runs through PowerShell and every
path is resolved and confined to the vault (or browser cache) before any
command runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from agent.config import _resolve_against_repo, get_settings

_MAX_READ_BYTES = 1024 * 1024


def _vault_root() -> Path:
    return get_settings().obsidian_vault_path.resolve()


def _cache_root() -> Path:
    return _resolve_against_repo(get_settings().browser_cache_dir).resolve()


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell(script: str, timeout: int = 60) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:400]
        raise RuntimeError(f"CLI error ({result.returncode}): {detail}")
    return result.stdout.strip()


def _confine_vault(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = _vault_root() / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(_vault_root()):
        raise ValueError("Path must stay inside the Obsidian vault.")
    return candidate


def _confine_read(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        cache_candidate = (_cache_root() / candidate).resolve()
        if cache_candidate.is_file():
            return cache_candidate
        candidate = _vault_root() / candidate
    candidate = candidate.resolve()
    if candidate.is_relative_to(_vault_root()) or candidate.is_relative_to(_cache_root()):
        return candidate
    raise ValueError("Path must stay inside the Obsidian vault or browser cache.")


def _write_text_cli(target: Path, content: str) -> None:
    parent = target.parent
    script = (
        f"New-Item -ItemType Directory -Force -Path {_ps_quote(str(parent))} | Out-Null; "
        f"[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
        f"[System.IO.File]::WriteAllText({_ps_quote(str(target))}, "
        f"([Console]::In.ReadToEnd()), (New-Object System.Text.UTF8Encoding $false))"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        input=content,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:400]
        raise RuntimeError(f"CLI error ({result.returncode}): {detail}")


def _read_text_cli(target: Path) -> str:
    return _powershell(
        f"Get-Content -Raw -LiteralPath {_ps_quote(str(target))} -Encoding UTF8",
        timeout=60,
    )


@tool
def read_file(path: str) -> str:
    """Read a text file from the Obsidian vault or the browser snapshot cache via PowerShell."""
    try:
        target = _confine_read(Path(path))
        if not target.is_file():
            return f"File not found: {path}"
        if target.stat().st_size > _MAX_READ_BYTES:
            return f"File is too large to read whole: {path} ({target.stat().st_size} bytes)"
        return _read_text_cli(target)
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)


@tool
def list_files(directory: str = "") -> str:
    """List files in a directory within the Obsidian vault via PowerShell."""
    try:
        target = _confine_vault(Path(directory or "."))
        if not target.exists() or not target.is_dir():
            return f"No files found in '{directory or 'vault root'}'"
        raw = _powershell(
            f"Get-ChildItem -LiteralPath {_ps_quote(str(target))} -Force "
            f"| Sort-Object Name | Select-Object -ExpandProperty Name"
        )
        names = [line for line in raw.splitlines() if line]
        prefix = target.relative_to(_vault_root()).as_posix() if target != _vault_root() else ""
        paths = sorted(f"{prefix}/{name}" if prefix else name for name in names)
        return "\n".join(f"- {path}" for path in paths) if paths else f"No files found in '{directory or 'vault root'}'"
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a UTF-8 text file inside the Obsidian vault via PowerShell."""
    try:
        target = _confine_vault(Path(path))
        _write_text_cli(target, content)
        return f"Wrote {target.relative_to(_vault_root()).as_posix()}"
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)


@tool
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace the first occurrence of old_text in a vault text file via PowerShell."""
    try:
        target = _confine_vault(Path(path))
        if not target.is_file():
            return f"File not found: {path}"
        content = _read_text_cli(target)
        if old_text not in content:
            return f"Pattern not found in {path}."
        _write_text_cli(target, content.replace(old_text, new_text, 1))
        return f"Edited {target.relative_to(_vault_root()).as_posix()}"
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)


@tool
def delete_file(path: str, confirm: bool = False) -> str:
    """Delete a single file inside the Obsidian vault. Requires confirm=true."""
    if not confirm:
        return "Deleting a vault file requires confirm=true."
    try:
        target = _confine_vault(Path(path))
        if not target.is_file():
            return f"File not found: {path}"
        _powershell(f"Remove-Item -LiteralPath {_ps_quote(str(target))} -Force")
        return f"Deleted {target.relative_to(_vault_root()).as_posix()}"
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)


@tool
def create_directory(path: str) -> str:
    """Create a folder (and any missing parents) inside the Obsidian vault via PowerShell."""
    try:
        target = _confine_vault(Path(path))
        if target.exists() and target.is_dir():
            return f"Already exists: {path}"
        _powershell(f"New-Item -ItemType Directory -Force -Path {_ps_quote(str(target))} | Out-Null")
        return f"Created {target.relative_to(_vault_root()).as_posix()}"
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)
