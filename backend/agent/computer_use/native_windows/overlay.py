"""Native Windows computer-use activity overlay."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable

from agent.config import get_settings


OVERLAY_BLUE = "#168cff"
OVERLAY_BLUE_DARK = "#0757bd"
OVERLAY_BLUE_LIGHT = "#8fd1ff"
TRANSPARENT_COLOR = "#010203"
OVERLAY_MESSAGE = "Vellum is using your computer - Esc to cancel"
OVERLAY_DESIGN = "smooth_single_edge_glow_status_pill"
PILL_OFFSET_Y = 32


class OverlayStartError(RuntimeError):
    """Raised when the native activity overlay cannot stay running."""


def _activity_overlay_enabled() -> bool:
    return get_settings().computer_use_activity_overlay


def _overlay_script() -> str:
    return rf"""
from pathlib import Path
import ctypes
import sys
import tkinter as tk

BLUE = {OVERLAY_BLUE!r}
BLUE_DARK = {OVERLAY_BLUE_DARK!r}
BLUE_LIGHT = {OVERLAY_BLUE_LIGHT!r}
TRANSPARENT_COLOR = {TRANSPARENT_COLOR!r}
MESSAGE = {OVERLAY_MESSAGE!r}
EDGE_GLOW_DESIGN = {OVERLAY_DESIGN!r}
PILL_OFFSET_Y = {PILL_OFFSET_Y!r}
sentinel = Path(sys.argv[1])

root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
root.configure(bg=TRANSPARENT_COLOR)
try:
    root.attributes("-transparentcolor", TRANSPARENT_COLOR)
except tk.TclError:
    pass
width = root.winfo_screenwidth()
height = root.winfo_screenheight()
root.geometry(f"{{width}}x{{height}}+0+0")

canvas = tk.Canvas(root, width=width, height=height, bg=TRANSPARENT_COLOR, highlightthickness=0, bd=0)
canvas.pack(fill="both", expand=True)

def create_rounded_rect(x1, y1, x2, y2, radius, **kwargs):
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=12, **kwargs)

def hex_to_rgba(value, alpha):
    value = value.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        alpha,
    )

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageTk

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    soft_edge = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    edge_draw = ImageDraw.Draw(soft_edge)
    edge_draw.rounded_rectangle(
        (10, 10, width - 10, height - 10),
        radius=30,
        outline=hex_to_rgba(BLUE, 120),
        width=16,
    )
    soft_edge = soft_edge.filter(ImageFilter.GaussianBlur(14))
    glow.alpha_composite(soft_edge)

    crisp_draw = ImageDraw.Draw(glow)
    crisp_draw.rounded_rectangle(
        (2, 2, width - 3, height - 3),
        radius=24,
        outline=hex_to_rgba(BLUE_LIGHT, 220),
        width=2,
    )
    crisp_draw.rounded_rectangle(
        (6, 6, width - 7, height - 7),
        radius=22,
        outline=hex_to_rgba(BLUE, 145),
        width=1,
    )

    glow_image = ImageTk.PhotoImage(glow)
    canvas.create_image(0, 0, image=glow_image, anchor="nw")
    canvas._glow_image = glow_image
except Exception:
    canvas.create_line(1, 1, width - 1, 1, fill=BLUE_LIGHT, width=3)
    canvas.create_line(width - 2, 1, width - 2, height - 1, fill=BLUE, width=3)
    canvas.create_line(width - 1, height - 2, 1, height - 2, fill=BLUE_LIGHT, width=3)
    canvas.create_line(1, height - 1, 1, 1, fill=BLUE, width=3)

pill_width = max(420, min(620, width - 48))
pill_height = 44
pill_x1 = (width - pill_width) // 2
pill_y1 = PILL_OFFSET_Y
pill_x2 = pill_x1 + pill_width
pill_y2 = pill_y1 + pill_height
pill_shadow = create_rounded_rect(
    pill_x1 - 2,
    pill_y1 - 1,
    pill_x2 + 2,
    pill_y2 + 3,
    18,
    fill=BLUE_DARK,
    outline="",
)
pill = create_rounded_rect(
    pill_x1,
    pill_y1,
    pill_x2,
    pill_y2,
    18,
    fill=BLUE,
    outline=BLUE_LIGHT,
    width=2,
)
canvas.create_text(
    width // 2,
    pill_y1 + pill_height // 2,
    text=MESSAGE,
    fill="white",
    font=("Segoe UI", 12, "bold"),
)

try:
    hwnd = root.winfo_id()
    user32 = ctypes.windll.user32
    exstyle = user32.GetWindowLongW(hwnd, -20)
    user32.SetWindowLongW(hwnd, -20, exstyle | 0x00000020 | 0x00000080)
except Exception:
    pass

def interrupt(_event=None):
    try:
        sentinel.write_text("esc", encoding="utf-8")
    except Exception:
        pass
    root.destroy()

def pulse(step=0):
    canvas.itemconfigure(pill_shadow, fill=BLUE_DARK)
    canvas.itemconfigure(pill, fill=BLUE if step % 2 == 0 else BLUE_DARK, outline=BLUE_LIGHT)
    root.after(650, pulse, step + 1)

root.bind("<Escape>", interrupt)
root.bind_all("<Escape>", interrupt)
root.after(50, root.focus_force)
root.after(100, pulse)

def poll_escape():
    try:
        if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
            interrupt()
            return
    except Exception:
        pass
    root.after(80, poll_escape)

root.after(120, poll_escape)
root.mainloop()
"""


class NativeWindowsOverlayController:
    """Owns the subprocess that displays the full-screen Esc overlay."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._sentinel: Path | None = None
        self._interrupt_callback: Callable[[str], None] | None = None
        self._watcher: threading.Thread | None = None
        self._stop_watcher = threading.Event()
        self._generation = 0
        self._lock = threading.RLock()

    def set_interrupt_callback(self, callback: Callable[[str], None]) -> None:
        self._interrupt_callback = callback

    def start(self) -> str:
        if not _activity_overlay_enabled():
            return "Computer-use activity overlay is disabled."
        previous_watcher: threading.Thread | None = None
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return "Computer-use activity overlay is already visible."
            previous_watcher = self._watcher
            self._cleanup_sentinel()
            self._stop_watcher.set()
        if previous_watcher is not None and previous_watcher is not threading.current_thread():
            previous_watcher.join(timeout=0.2)
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return "Computer-use activity overlay is already visible."
            self._cleanup_sentinel()
            self._stop_watcher = threading.Event()
            self._generation += 1
            generation = self._generation
            stop_event = self._stop_watcher
            sentinel = Path(tempfile.gettempdir()) / f"vellum-computer-use-overlay-{id(self)}.interrupt"
            try:
                kwargs: dict[str, Any] = {
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if sys.platform == "win32":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                process = subprocess.Popen([sys.executable, "-c", _overlay_script(), str(sentinel)], **kwargs)
            except Exception:
                self._process = None
                self._sentinel = None
                raise OverlayStartError("Computer-use activity overlay could not be started.")
            self._process = process
            self._sentinel = sentinel
            self._watcher = threading.Thread(
                target=self._watch_for_interrupt,
                args=(stop_event, process, sentinel, generation),
                daemon=True,
            )
            self._watcher.start()
        time.sleep(0.12)
        if process.poll() is not None:
            with self._lock:
                if self._generation == generation:
                    stop_event.set()
                    self._process = None
                    self._cleanup_sentinel()
                    self._sentinel = None
            raise OverlayStartError("Computer-use activity overlay could not be started.")
        return "Computer-use activity overlay started."

    def stop(self) -> str:
        with self._lock:
            process = self._process
            self._process = None
            self._stop_watcher.set()
            self._generation += 1
            self._cleanup_sentinel()
            self._sentinel = None
        if process is None or process.poll() is not None:
            return "Computer-use activity overlay is not running."
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
        return "Computer-use activity overlay stopped."

    def status(self) -> dict[str, object]:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            pid = self._process.pid if running and self._process is not None else None
        return {
            "ready": running,
            "controller": "native_windows",
            "pid": pid,
            "message": OVERLAY_MESSAGE,
            "design": OVERLAY_DESIGN,
            "transparent": True,
            "click_through": True,
            "edge_glow": True,
            "status_pill": True,
            "pill_offset_y": PILL_OFFSET_Y,
            "edge_glow_style": "smooth-single",
            "transparent_color": TRANSPARENT_COLOR,
            "accent": OVERLAY_BLUE,
        }

    def _watch_for_interrupt(
        self,
        stop_event: threading.Event,
        process: subprocess.Popen,
        sentinel: Path,
        generation: int,
    ) -> None:
        while not stop_event.is_set():
            with self._lock:
                if generation != self._generation:
                    return
            if sentinel.exists():
                reason = self._read_interrupt_reason(sentinel)
                with self._lock:
                    if generation != self._generation:
                        return
                    callback = self._interrupt_callback
                if callback is not None:
                    callback(reason)
                return
            if process.poll() is not None:
                return
            time.sleep(0.1)

    def _read_interrupt_reason(self, sentinel: Path) -> str:
        try:
            reason = sentinel.read_text(encoding="utf-8").strip()
        except OSError:
            reason = ""
        return reason or "esc"

    def _cleanup_sentinel(self) -> None:
        if self._sentinel is None:
            return
        try:
            self._sentinel.unlink(missing_ok=True)
        except OSError:
            pass
