"""Typer entry point for the `vellum` command."""

from __future__ import annotations

import typer

VERSION = "0.1.0"

app = typer.Typer(
    name="vellum",
    help="trained on you.",
    add_completion=False,
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vellum {VERSION}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="show version and exit.",
    ),
) -> None:
    """trained on you."""
    if ctx.invoked_subcommand is None:
        from agent.tui.cli.commands.chat import chat as chat_cmd
        chat_cmd()


from agent.tui.cli.commands.chat import chat as _chat_cmd
from agent.tui.cli.commands.chat import resume as _resume_cmd

app.command(name="chat", help="open the chat surface.")(_chat_cmd)
app.command(name="resume", help="reopen a saved thread.")(_resume_cmd)

from agent.tui.cli.commands.setup import setup_command

app.command(name="setup", help="begin configuration.")(setup_command)

from agent.tui.cli.commands.models import models_command

app.command(name="models", help="choose the primary model.")(models_command)

from agent.tui.cli.commands.sessions import sessions_app

app.add_typer(sessions_app, name="sessions")

from agent.tui.cli.commands.usage import usage_command

app.command(name="usage", help="token ledger summary.")(usage_command)

from agent.tui.cli.commands.config import config_app

app.add_typer(config_app, name="config")

from agent.tui.cli.commands.doctor import doctor_command

app.command(name="doctor", help="diagnostics.")(doctor_command)
