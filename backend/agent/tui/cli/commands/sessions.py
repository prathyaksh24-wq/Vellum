"""vellum sessions — list, rename, delete threads."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.memory.sessions import SessionsReader
from agent.tui.cli import PHRASES
from agent.tui.cli.screen import EMBER, PARCHMENT, say

sessions_app = typer.Typer(help="manage saved threads.", no_args_is_help=False)
console = Console()


def _reader() -> SessionsReader:
    base = Path("data") / "memory"
    return SessionsReader(
        checkpoints_db=base / "checkpoints.db",
        sessions_db=base / "sessions.db",
    )


@sessions_app.callback(invoke_without_command=True)
def sessions_root(ctx: typer.Context) -> None:
    """list saved threads."""
    if ctx.invoked_subcommand is not None:
        return
    rows = _reader().list_sessions()
    if not rows:
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
    table.add_column("thread", style=f"{PARCHMENT}")
    table.add_column("msgs", justify="right", style=f"{PARCHMENT}")
    for r in rows:
        table.add_row(r["title"], str(r["msgs"]))
    console.print(table)


@sessions_app.command("rename")
def rename(
    thread_id: str = typer.Argument(..., help="thread id to rename"),
    title: str = typer.Argument(..., help="new title"),
) -> None:
    """rename a thread."""
    _reader().rename(thread_id, title)
    say(PHRASES["filed"])


@sessions_app.command("delete")
def delete(
    thread_id: str = typer.Argument(..., help="thread id to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="skip confirmation."),
) -> None:
    """delete a thread."""
    if not yes:
        confirm = typer.confirm("delete this thread", default=False)
        if not confirm:
            say(PHRASES["cancelled"])
            return
    _reader().delete(thread_id)
    say(PHRASES["out"])
