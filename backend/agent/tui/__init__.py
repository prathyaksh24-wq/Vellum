"""Textual terminal interface for Vellum."""

from __future__ import annotations

from .app import VellumTuiApp


def main() -> None:
    VellumTuiApp().run()


__all__ = ["VellumTuiApp", "main"]
