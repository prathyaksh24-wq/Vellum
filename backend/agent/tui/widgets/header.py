from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class VellumHeader(Static):
    """Quiet one-line header with thread and model state."""

    thread_title = reactive("untitled")
    model_name = reactive("")
    attending = reactive(False)

    def compose(self):
        yield Static("", id="topline")
        yield Static("--------------------------------------------------------------------------------", id="rule")

    def on_mount(self) -> None:
        self._refresh()

    def watch_thread_title(self, _value: str) -> None:
        self._refresh()

    def watch_model_name(self, _value: str) -> None:
        self._refresh()

    def watch_attending(self, _value: bool) -> None:
        self._refresh()

    def _refresh(self) -> None:
        dot = "[#d97746]o[/]" if self.attending else "[#716d68]o[/]"
        title = self.thread_title or "untitled"
        model = self.model_name or "model"
        left = f"[italic]vellum[/]  {dot}  [#716d68 italic]{title}[/]"
        line = f"{left}{model:>{max(1, 88 - len(title))}}"
        widget = self.query_one("#topline", Static)
        widget.update(line)
