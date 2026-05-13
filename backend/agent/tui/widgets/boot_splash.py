"""Boot splash widget: glyph flicker + fade + dissolve into chat."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from agent.tui.animation import (
    BOOT_FADE_FRAMES,
    BOOT_FADE_INTERVAL,
    BOOT_FLICKER_FRAMES,
    BOOT_FLICKER_INTERVAL,
)


class BootSplash(Vertical):
    """Centered logo flicker + tagline fade. Self-removes when finished."""

    def __init__(self, **kwargs) -> None:
        super().__init__(classes="boot-splash", **kwargs)
        self._task: asyncio.Task | None = None
        self._cancelled = False

    def compose(self) -> ComposeResult:
        yield Static("vellum", id="boot-logo")
        yield Static("", id="boot-tagline")

    def on_mount(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        logo = self.query_one("#boot-logo", Static)
        tagline = self.query_one("#boot-tagline", Static)
        try:
            # Phase 1: glyph flicker
            for frame in BOOT_FLICKER_FRAMES:
                if self._cancelled:
                    break
                logo.update(f"[italic #ece6db]{frame}[/]")
                await asyncio.sleep(BOOT_FLICKER_INTERVAL)
            # Phase 2: tagline fade-in
            for color in BOOT_FADE_FRAMES:
                if self._cancelled:
                    break
                tagline.update(f"[italic {color}]trained on you[/]")
                await asyncio.sleep(BOOT_FADE_INTERVAL)
            # Phase 3: hold briefly
            if not self._cancelled:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await self.remove()
            except Exception:
                pass

    def skip(self) -> None:
        self._cancelled = True
        if self._task is not None:
            self._task.cancel()
