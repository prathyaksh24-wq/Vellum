"""vellum doctor — diagnostics. No auto-fix."""

from __future__ import annotations

import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

import typer
from rich.console import Console

from agent.telemetry.prices import MODEL_PRICES
from agent.tui.cli.atomic_env import load_env
from agent.tui.cli.screen import EMBER, PARCHMENT

console = Console()


def _row(label: str, status: str, detail: str = "") -> tuple[str, bool]:
    is_error = status == "error"
    color = EMBER if is_error else PARCHMENT
    line = f"  [{PARCHMENT}]{label:.<40}[/] [{color}]{status}[/]"
    if detail:
        line += f"  [{PARCHMENT}]— {detail}[/]"
    return line, is_error


def _check_openrouter(url: str) -> tuple[str, str]:
    try:
        req = urllib.request.Request(url, method="HEAD")
        urllib.request.urlopen(req, timeout=5)  # noqa: S310
        return "ok", ""
    except urllib.error.URLError as e:
        return "error", str(e.reason)
    except Exception as e:
        return "error", str(e)


def _check_db_readable(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "absent", ""
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT 1")
        conn.close()
        return "ok", ""
    except Exception as e:
        return "error", str(e)


def doctor_command() -> None:
    """report on configuration and connectivity."""
    env = load_env(Path(".env"))
    lines: list[str] = []
    any_error = False

    # openrouter reachable
    base = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    status, detail = _check_openrouter(f"{base}/models")
    line, err = _row("openrouter reachable", status, detail)
    lines.append(line); any_error = any_error or err

    # vault exists
    vault = env.get("OBSIDIAN_VAULT_PATH", "")
    if vault and Path(vault).is_dir():
        line, err = _row("vault exists", "ok")
    else:
        line, err = _row("vault exists", "error", "OBSIDIAN_VAULT_PATH missing or not a dir")
    lines.append(line); any_error = any_error or err

    # mcp path sandboxed
    mcp = env.get("FILESYSTEM_MCP_PATH", "")
    if vault and mcp:
        try:
            sandboxed = Path(mcp).resolve().is_relative_to(Path(vault).resolve())
        except Exception:
            sandboxed = False
        if sandboxed:
            line, err = _row("mcp path sandboxed", "ok")
        else:
            line, err = _row("mcp path sandboxed", "error", "FILESYSTEM_MCP_PATH not inside vault")
    else:
        line, err = _row("mcp path sandboxed", "error", "FILESYSTEM_MCP_PATH not inside vault")
    lines.append(line); any_error = any_error or err

    # zdr on
    zdr = env.get("ZDR_ONLY", "").lower()
    if zdr == "true":
        line, err = _row("zdr on", "ok")
    else:
        line, err = _row("zdr on", "error", "ZDR_ONLY must be true")
    lines.append(line); any_error = any_error or err

    # checkpoints.db readable
    status, detail = _check_db_readable(Path("data/memory/checkpoints.db"))
    line, err = _row("checkpoints.db readable", status, detail)
    lines.append(line); any_error = any_error or err

    # long_term.db readable
    status, detail = _check_db_readable(Path("data/memory/long_term.db"))
    line, err = _row("long_term.db readable", status, detail)
    lines.append(line); any_error = any_error or err

    # usage.db readable
    status, detail = _check_db_readable(Path("data/memory/usage.db"))
    line, err = _row("usage.db readable", status, detail)
    lines.append(line); any_error = any_error or err

    # models priced
    missing = [m for m in [env.get("PRIMARY_MODEL"), env.get("FAST_MODEL"), env.get("FALLBACK_MODEL")]
               if m and m not in MODEL_PRICES]
    if missing:
        line, err = _row("models priced", "error", "missing: " + ", ".join(missing))
    else:
        line, err = _row("models priced", "ok")
    lines.append(line); any_error = any_error or err

    for line in lines:
        console.print(line)

    if any_error:
        raise typer.Exit(code=1)
