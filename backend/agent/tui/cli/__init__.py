"""Vellum CLI — subcommand surface following BRAND.md voice."""

from __future__ import annotations


PHRASES: dict[str, str] = {
    "set": "Set.",
    "filed": "Filed.",
    "out": "Out.",
    "withheld": "Withheld.",
    "unreachable": "Unreachable.",
    "nothing_library": "Nothing on this in your library.",
    "not_configured": "vellum has not been configured. begin setup.",
    "landing_setup": "two paths.",
    "path_quick": "quick      the few choices that matter",
    "path_full":  "full       every choice",
    "confirm_yes": "yes",
    "confirm_no": "no",
    "cancelled": "Out.",
}


def main() -> None:
    from agent.tui.cli.app import app

    app()


__all__ = ["main", "PHRASES"]
