"""vellum config — view and edit the .env."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.tui.cli import PHRASES
from agent.tui.cli.atomic_env import load_env
from agent.tui.cli.screen import EMBER, PARCHMENT, say

config_app = typer.Typer(help="view current settings.", no_args_is_help=False)
console = Console()

SECRET_TOKENS = ("API_KEY", "TOKEN", "SECRET")


def _redact(key: str, value: str) -> str:
    upper = key.upper()
    if any(token in upper for token in SECRET_TOKENS) and value:
        return f"{value[:5]}…"
    return value


@config_app.callback(invoke_without_command=True)
def config_root(ctx: typer.Context) -> None:
    """print current .env values."""
    if ctx.invoked_subcommand is not None:
        return
    env_path = Path(".env")
    if not env_path.exists():
        say(PHRASES["nothing_library"])
        return
    values = load_env(env_path)
    if not values:
        say(PHRASES["nothing_library"])
        return
    table = Table(
        show_header=True,
        header_style=f"{PARCHMENT}",
        border_style=f"{EMBER}",
        show_edge=False,
        pad_edge=False,
        box=None,
    )
    table.add_column("key", style=f"{PARCHMENT}")
    table.add_column("value", style=f"{PARCHMENT}")
    for key, value in values.items():
        table.add_row(key, _redact(key, value))
    console.print(table)


@config_app.command("edit")
def edit() -> None:
    """open .env in $EDITOR."""
    env_path = Path(".env").resolve()
    editor = os.environ.get("EDITOR")
    if not editor:
        if sys.platform == "win32":
            editor = "notepad"
        elif shutil.which("nano"):
            editor = "nano"
        elif shutil.which("vi"):
            editor = "vi"
        else:
            console.print(str(env_path))
            return
    subprocess.run([editor, str(env_path)], check=False)
    say(PHRASES["filed"])
