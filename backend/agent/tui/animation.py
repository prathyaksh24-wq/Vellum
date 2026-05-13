"""Animation timing constants and helpers shared by motion widgets."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

# Boot splash
BOOT_FLICKER_FRAMES = ("v3llum", "v€llum", "v3ll0m", "v€ll0m", "vellum")
BOOT_FLICKER_INTERVAL = 0.045  # seconds per frame
BOOT_FADE_FRAMES = ("#0c0c0e", "#1f1c19", "#3a3530", "#5a544c", "#716d68", "#8a857e", "#aaa49b")
BOOT_FADE_INTERVAL = 0.05
BOOT_TOTAL_MS = 600

# Spinner
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_FPS = 12

# Marching rule
MARCHING_GLYPHS = "╴╴╴╴◉"
MARCHING_FPS = 8
MARCHING_WIDTH = 72

# Header shimmer
SHIMMER_INTERVAL = 0.05


async def tick(fps: int) -> AsyncIterator[int]:
    """Yield an incrementing frame count at the requested FPS."""
    interval = 1.0 / max(1, fps)
    frame = 0
    while True:
        yield frame
        frame += 1
        await asyncio.sleep(interval)
