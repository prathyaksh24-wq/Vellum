"""Brand-voiced screen primitives for the vellum CLI.

Each interactive step calls `ansi_clear()` first so the previous step
vanishes — viewport AND scrollback. Headers are letter-spaced uppercase,
matching the brand's "DM Sans, weight 500, letter-spacing 0.16em uppercase"
metadata register.
"""

from __future__ import annotations

import sys
from typing import Iterable

import questionary
from questionary import Choice
from rich.console import Console

EMBER = "#d97746"
PARCHMENT = "#ece6db"
GRAPHITE = "#0c0c0e"
DIM = "#716d68"

console = Console()


def ansi_clear() -> None:
    """Clear viewport and scrollback. Works on Windows Terminal + PowerShell."""
    sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
    sys.stdout.flush()


def draw_header(label: str) -> None:
    """Render a brand-voiced uppercase letter-spaced header."""
    spaced = " ".join(label.upper())
    console.print()
    console.print(f"  [bold {PARCHMENT}]{spaced}[/]")
    console.print()


_style = questionary.Style([
    ("qmark", f"fg:{EMBER} bold"),
    ("question", f"fg:{PARCHMENT}"),
    ("answer", f"fg:{EMBER} bold"),
    ("pointer", f"fg:{EMBER} bold"),
    ("highlighted", f"fg:{EMBER} bold"),
    ("selected", f"fg:{EMBER}"),
    ("instruction", f"fg:{DIM}"),
    ("text", f"fg:{PARCHMENT}"),
    ("disabled", f"fg:{DIM}"),
])


def pick(
    *,
    header: str,
    choices: Iterable[tuple[str, str]] | Iterable[Choice],
    default: str | None = None,
) -> str | None:
    """Show an arrow-key picker on a fresh screen. Returns the selected value or None on cancel.

    `choices` may be (value, label) tuples or pre-built Choice objects.
    """
    ansi_clear()
    draw_header(header)
    normalized: list[Choice] = []
    for c in choices:
        if isinstance(c, Choice):
            normalized.append(c)
        else:
            value, label = c
            normalized.append(Choice(title=label, value=value))
    return questionary.select(
        "",
        choices=normalized,
        default=default,
        instruction="↑↓ select   enter confirm",
        style=_style,
        qmark=">",
    ).ask()


def ask_text(*, header: str, prompt: str, default: str = "") -> str | None:
    """Single-line text input on a fresh screen."""
    ansi_clear()
    draw_header(header)
    return questionary.text(
        prompt,
        default=default,
        instruction="enter saves   esc cancels",
        style=_style,
        qmark=">",
    ).ask()


def ask_password(*, header: str, prompt: str) -> str | None:
    """Single-line password input on a fresh screen."""
    ansi_clear()
    draw_header(header)
    return questionary.password(
        prompt,
        instruction="enter saves   esc cancels",
        style=_style,
        qmark=">",
    ).ask()


def say(phrase: str) -> None:
    """Print a brand-voiced phrase on its own line, in parchment."""
    console.print(f"[{PARCHMENT}]{phrase}[/]")
