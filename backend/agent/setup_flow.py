"""First-run setup: who sees onboarding, and the local model download.

Onboarding is for new users only. It runs once, after sign-up (or after
choosing to use Vellum without an account), until setup is finished. An
install that already has conversations or memories is an existing user: it
is marked as set up and never shown the wizard.

The local model step downloads through Ollama's own pull API, in the
background, so the user can carry on with the rest of setup. When the
download finishes the model becomes the default (and memory follows it, see
agent/memory/engines/runtime.py).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
PRIVACY_MODES = ("local_only", "ask_before_sharing", "protect_for_me", "full_context")


def state_path(root: Path) -> Path:
    return Path(root) / "data" / "memory" / "setup_state.json"


def read_state(root: Path) -> dict[str, Any]:
    try:
        value = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def write_state(root: Path, payload: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _rows(db: Path, table: str) -> int:
    if not db.is_file():
        return 0
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608 - fixed names
    except sqlite3.Error:
        return 0


def has_history(root: Path) -> bool:
    """True when this workspace was already used: conversations or memories exist."""
    sessions = Path(root) / "data" / "memory" / "sessions.db"
    return any(_rows(sessions, table) for table in ("thread_titles", "thread_state", "memory_items"))


def onboarding_status(root: Path) -> dict[str, Any]:
    """Whether to show onboarding. Existing users are recorded as set up, once."""
    state = read_state(root)
    if state.get("completed_at"):
        return {"needs_onboarding": False, "reason": "completed"}
    if state.get("started_at"):
        # A new user part-way through setup; memories they imported there don't make them an existing user.
        return {"needs_onboarding": True, "reason": "in_progress"}
    if has_history(root):
        write_state(root, {**state, "completed_at": _now(), "existing_user": True})
        return {"needs_onboarding": False, "reason": "existing_user"}
    write_state(root, {**state, "started_at": _now()})
    return {"needs_onboarding": True, "reason": "new_user"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- local model download --------------------------------------------------------


@dataclass
class PullStatus:
    model: str = ""
    state: str = "idle"  # idle | pulling | done | error
    detail: str = ""
    completed: int = 0
    total: int = 0
    started_at: float = 0.0
    applied_model: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["percent"] = round(100 * self.completed / self.total, 1) if self.total else 0.0
        return value


class ModelPull:
    """One background Ollama pull at a time, with progress for the wizard."""

    def __init__(self, *, opener: Callable[..., Any] = urllib.request.urlopen,
                 on_done: Callable[[str], str] | None = None) -> None:
        self._open = opener
        self._on_done = on_done
        self._lock = threading.Lock()
        self.status = PullStatus()
        self._thread: threading.Thread | None = None

    def start(self, base_url: str, model: str) -> dict[str, Any]:
        model = model.strip()
        if not model or len(model) > 300 or any(ch in model for ch in " \n\r\t\"'"):
            raise ValueError("Choose a model to download.")
        with self._lock:
            if self.status.state == "pulling" and self._thread is not None and self._thread.is_alive():
                if self.status.model == model:
                    return self.status.as_dict()
                raise RuntimeError("Another model is already downloading.")
            self.status = PullStatus(model=model, state="pulling", detail="Starting", started_at=time.time())
            self._thread = threading.Thread(target=self._run, args=(base_url.rstrip("/"), model),
                                            name="setup-model-pull", daemon=True)
            self._thread.start()
            return self.status.as_dict()

    def _run(self, base_url: str, model: str) -> None:
        request = urllib.request.Request(f"{base_url}/api/pull", method="POST",
                                         data=json.dumps({"model": model, "stream": True}).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with self._open(request, timeout=60) as response:  # noqa: S310 - loopback Ollama
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise RuntimeError(str(event["error"]))
                    with self._lock:
                        self.status.detail = str(event.get("status") or self.status.detail)
                        if event.get("total"):
                            self.status.total = int(event["total"])
                            self.status.completed = int(event.get("completed") or 0)
            applied = self._on_done(model) if self._on_done else ""
            with self._lock:
                self.status.state, self.status.detail, self.status.applied_model = "done", "Ready", applied
                if self.status.total:
                    self.status.completed = self.status.total
        except Exception as exc:  # noqa: BLE001 - reported to the wizard
            with self._lock:
                self.status.state, self.status.error = "error", _friendly_pull_error(exc)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.status.as_dict()


def _friendly_pull_error(exc: Exception) -> str:
    text = str(exc)
    if "Connection refused" in text or "10061" in text or "urlopen error" in text:
        return "Ollama isn't running. Start Ollama, then try again."
    if "not found" in text.lower() or "manifest" in text.lower():
        return "That model couldn't be found on Hugging Face or Ollama."
    return f"The download stopped: {text[:200]}"


def ollama_status(base_url: str, *, opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    import shutil

    running = False
    try:
        with opener(f"{base_url.rstrip('/')}/api/version", timeout=1.5) as response:  # noqa: S310 - loopback
            running = response.status == 200
    except Exception:  # noqa: BLE001
        running = False
    return {"installed": running or bool(shutil.which("ollama")), "running": running,
            "download_url": OLLAMA_DOWNLOAD_URL}
