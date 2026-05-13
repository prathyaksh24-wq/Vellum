"""Assistant message widget with Rich Markdown rendering + footnotes."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from agent.tui.animation import MARCHING_FPS, MARCHING_GLYPHS, MARCHING_WIDTH


class _MarchingRule(Static):
    """Marching-ants stream rule, runs while assistant streams."""

    def __init__(self) -> None:
        super().__init__("", classes="marching-rule")
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._offset = 0

    def on_mount(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        interval = 1.0 / MARCHING_FPS
        try:
            while not self._stopped:
                self._render_frame()
                self._offset = (self._offset + 1) % len(MARCHING_GLYPHS)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def _render_frame(self) -> None:
        buf = []
        for i in range(MARCHING_WIDTH):
            glyph = MARCHING_GLYPHS[(i + self._offset) % len(MARCHING_GLYPHS)]
            buf.append(glyph)
        rule = "".join(buf)
        self.update(f"[#d97746]{rule}[/]")

    def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
        self.update("[#24211f]" + "─" * MARCHING_WIDTH + "[/]")


class MarkdownMessage(Widget):
    """Assistant message: Rich Markdown body + (optional) marching rule + footnotes."""

    DEFAULT_CSS = "MarkdownMessage { height: auto; width: 100%; padding: 0; }"

    def __init__(self, source: str = "from your library") -> None:
        super().__init__()
        self._source = source
        self._buffer = ""
        self._rendered_body: Static | None = None
        self._rule: _MarchingRule | None = None
        self._foot: Static | None = None
        self._meta: Static | None = None
        self._refresh_pending = False
        self._finalized = False

    def compose(self):
        self._meta = Static(f"[#716d68]vellum . {self._source}[/]", classes="message-meta")
        yield self._meta
        self._rendered_body = Static("", classes="message-vellum")
        yield self._rendered_body
        self._rule = _MarchingRule()
        yield self._rule
        self._foot = Static("", classes="message-footnotes")
        yield self._foot

    def append_token(self, text: str) -> None:
        if self._finalized:
            return
        self._buffer += text
        if not self._refresh_pending:
            self._refresh_pending = True
            self.set_timer(0.06, self._render_body)

    def _render_body(self) -> None:
        self._refresh_pending = False
        if self._rendered_body is None:
            return
        text = self._buffer or " "
        try:
            md = Markdown(text, code_theme="monokai", inline_code_lexer="text")
            self._rendered_body.update(md)
        except Exception:
            self._rendered_body.update(text)

    def finalize(self, citations: list[dict] | None = None, source: str | None = None) -> None:
        self._finalized = True
        if source and self._meta is not None:
            self._source = source
            self._meta.update(f"[#716d68]vellum . {self._source}[/]")
        self._render_body()
        if self._rule is not None:
            self._rule.stop()
        if citations and self._foot is not None:
            self._foot.update(self._render_footnotes(citations))
        elif self._foot is not None:
            self._foot.update("")

    @staticmethod
    def _render_footnotes(citations: list[dict]) -> str:
        marks = ["i.", "ii.", "iii.", "iv.", "v.", "vi.", "vii.", "viii.", "ix.", "x."]
        lines = ["[#24211f]" + "─" * 6 + "[/]"]
        for entry in citations:
            n = int(entry.get("n", 0))
            mark = marks[n - 1] if 1 <= n <= len(marks) else f"{n}."
            path = str(entry.get("path", ""))
            lines.append(f"  [#716d68]{mark:<5}[/] [#aaa49b]{path}[/]")
        return "\n".join(lines)
