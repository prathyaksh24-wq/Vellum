"""bare vellum, vellum chat, vellum resume <id> — all open the TUI."""

from __future__ import annotations

import typer

from agent.tui.cli import PHRASES
from agent.tui.cli.screen import say


def _settings_ok() -> bool:
    try:
        from agent.config import get_settings
        get_settings()
        return True
    except Exception:
        return False


def launch_tui(thread_id: str | None = None) -> None:
    """Start the Textual TUI, optionally pinned to a specific thread."""
    if not _settings_ok():
        say(PHRASES["not_configured"])
        from agent.tui.cli.commands.setup import run_wizard
        run_wizard(quick=True)
        if not _settings_ok():
            raise typer.Exit(code=1)
    from agent.tui.app import VellumTuiApp
    app_instance = VellumTuiApp()
    if thread_id:
        app_instance.active_thread_id = thread_id
    app_instance.run()


def chat() -> None:
    """trained on you. open the chat surface."""
    launch_tui(thread_id=None)


def resume(thread_id: str = typer.Argument(..., help="thread id to reopen")) -> None:
    """reopen a saved thread."""
    launch_tui(thread_id=thread_id)
