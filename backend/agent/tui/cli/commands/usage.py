"""vellum usage — token-ledger summary table."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.telemetry.usage_ledger import UsageLedger
from agent.tui.cli import PHRASES
from agent.tui.cli.screen import EMBER, PARCHMENT, say

console = Console()


def usage_command(
    days: int = typer.Option(7, "--days", help="window size in days."),
) -> None:
    """usage over the last window."""
    ledger = UsageLedger(Path("data") / "memory" / "usage.db")
    if not ledger.path.exists():
        say(PHRASES["nothing_library"])
        return
    rows = ledger.summarize(days=days)
    if not rows:
        say(PHRASES["nothing_library"])
        return

    title = "this week" if days == 7 else f"last {days} days"
    table = Table(
        show_header=True,
        header_style=f"{PARCHMENT}",
        border_style=f"{EMBER}",
        show_edge=False,
        pad_edge=False,
        box=None,
    )
    table.add_column(title, style=f"{PARCHMENT}")
    table.add_column("in", justify="right", style=f"{PARCHMENT}")
    table.add_column("out", justify="right", style=f"{PARCHMENT}")
    table.add_column("usd", justify="right", style=f"{PARCHMENT}")

    total_in = total_out = 0
    total_cost = 0.0
    for r in rows:
        in_t = int(r["in_tokens"] or 0)
        out_t = int(r["out_tokens"] or 0)
        cost = float(r["cost_usd"] or 0.0)
        total_in += in_t
        total_out += out_t
        total_cost += cost
        table.add_row(r["model"], f"{in_t:,}", f"{out_t:,}", f"{cost:.2f}")
    table.add_row("", "", "", f"{total_cost:.2f}", style=f"bold {PARCHMENT}")
    console.print(table)
