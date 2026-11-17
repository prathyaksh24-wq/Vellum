"""Read-only file tools for the browser snapshot cache.

Browser snapshots and extracted web pages are saved to BROWSER_CACHE_DIR when
they are too long for one tool result. read_file and list_files let the agent
page through them, the same workflow Hermes uses for its ~/.hermes/cache/web
snapshots. Every path is resolved and confined to the cache before any command
runs, and no tool here can write or delete files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from agent.config import _resolve_against_repo, get_settings

_MAX_READ_BYTES = 1024 * 1024


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


def _confine_cache(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = _cache_root() / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(_cache_root()):
        raise ValueError("Path must stay inside the browser cache.")
    return candidate


def _read_text_cli(target: Path) -> str:
    return _powershell(
        f"Get-Content -Raw -LiteralPath {_ps_quote(str(target))} -Encoding UTF8",
        timeout=60,
    )


@tool
def read_file(path: str) -> str:
    """Read a saved browser snapshot or extracted page from the browser cache via PowerShell."""
    try:
        target = _confine_cache(Path(path))
        if not target.is_file():
            return f"File not found: {path}"
        if target.stat().st_size > _MAX_READ_BYTES:
            return f"File is too large to read whole: {path} ({target.stat().st_size} bytes)"
        return _read_text_cli(target)
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)


@tool
def list_files(directory: str = "") -> str:
    """List saved snapshots and pages in a browser cache directory via PowerShell."""
    try:
        target = _confine_cache(Path(directory or "."))
        if not target.exists() or not target.is_dir():
            return f"No files found in '{directory or 'browser cache'}'"
        raw = _powershell(
            f"Get-ChildItem -LiteralPath {_ps_quote(str(target))} -Force "
            f"| Sort-Object Name | Select-Object -ExpandProperty Name"
        )
        names = [line for line in raw.splitlines() if line]
        prefix = target.relative_to(_cache_root()).as_posix() if target != _cache_root() else ""
        paths = sorted(f"{prefix}/{name}" if prefix else name for name in names)
        return "\n".join(f"- {path}" for path in paths) if paths else f"No files found in '{directory or 'browser cache'}'"
    except (OSError, RuntimeError, ValueError) as exc:
        return str(exc)
