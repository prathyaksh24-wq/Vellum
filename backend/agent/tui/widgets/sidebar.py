from __future__ import annotations

from textual.widgets import Static


class ThreadsSidebar(Static):
    """Left thread rail."""

    def on_mount(self) -> None:
        self.update(
            "[italic #ece6db]threads[/]\n\n"
            "[#716d68]today[/]\n"
            "[#d97746]| i.   untitled[/]\n"
            "  ii.  what are you reading\n"
            "  iii. river passage\n\n"
            "[#716d68]yesterday[/]\n"
            "  i.   books left open\n"
            "  ii.  qdrant indexing\n\n"
            "[#716d68]earlier[/]\n"
            "  i.   first vault pass"
        )

    def toggle_open(self) -> None:
        self.toggle_class("open")


class LedgerSidebar(Static):
    """Right compact usage rail."""

    def on_mount(self) -> None:
        self.update(
            "[italic #ece6db]ledger[/]\n\n"
            "[#716d68]today[/]\n"
            "0 tokens. $0.00.\n\n"
            "[#716d68]thread[/]\n"
            "0 tokens.\n\n"
            "[#716d68]models[/]\n"
            "i.   primary . 0\n"
            "ii.  fallback . 0\n"
            "iii. fast . 0\n\n"
            "[#716d68]week[/]\n"
            "0 tokens. $0.00.\n\n"
            "[#716d68]Filed locally. Nothing sent.[/]"
        )

    def toggle_open(self) -> None:
        self.toggle_class("open")
