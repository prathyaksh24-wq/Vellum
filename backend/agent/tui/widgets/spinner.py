"""Braille spinner widget for tool-call panels."""

from __future__ import annotations

import asyncio

from textual.widgets import Static

from agent.tui.animation import SPINNER_FPS, SPINNER_FRAMES


class BrailSpinner(Static):
    """Rotating braille spinner; stops on .done(success=True/False)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(SPINNER_FRAMES[0], **kwargs)
        self._task: asyncio.Task | None = None
        self._frame = 0
        self._stopped = False
        self._final = ""

    def on_mount(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        interval = 1.0 / SPINNER_FPS
        try:
            while not self._stopped:
                glyph = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
                self.update(f"[#d97746]{glyph}[/]")
                self._frame += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def done(self, success: bool = True) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
        self._final = "[#a8c098]✓[/]" if success else "[#d97746]×[/]"
        self.update(self._final)
