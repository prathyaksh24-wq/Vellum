from __future__ import annotations

import asyncio

from textual.reactive import reactive
from textual.widgets import Static


_SHIMMER_FRAMES = (
    "#716d68",
    "#8a857e",
    "#aaa49b",
    "#ece6db",
    "#aaa49b",
    "#8a857e",
    "#716d68",
)


class VellumHeader(Static):
    """Quiet one-line header with thread and model state."""

    thread_title = reactive("untitled")
    model_name = reactive("")
    attending = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._shimmer_color: str | None = None
        self._shimmer_task: asyncio.Task | None = None

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
        color = self._shimmer_color or "#716d68"
        left = f"[italic]vellum[/]  {dot}  [#716d68 italic]{title}[/]"
        right_padding = max(1, 88 - len(title) - len(model) - 18)
        line = f"{left}{' ' * right_padding}[{color}]{model}[/]"
        widget = self.query_one("#topline", Static)
        widget.update(line)

    def shimmer(self) -> None:
        """One-pass color sweep across the model badge."""
        if self._shimmer_task is not None and not self._shimmer_task.done():
            self._shimmer_task.cancel()
        self._shimmer_task = asyncio.create_task(self._shimmer_loop())

    async def _shimmer_loop(self) -> None:
        try:
            for color in _SHIMMER_FRAMES:
                self._shimmer_color = color
                self._refresh()
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass
        finally:
            self._shimmer_color = None
            self._refresh()
