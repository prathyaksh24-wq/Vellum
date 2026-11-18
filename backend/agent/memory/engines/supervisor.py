"""Start, watch and stop Vellum's memory engine processes.

Engines run as child processes of the backend, never threads in it: a crash
or memory spike in an engine cannot take chat down, and each engine's RAM is
visible on its own. Startup runs in the background, so chat never waits for
an engine. A crashed engine restarts with backoff (2 s doubling to 60 s,
like the desktop shell's backend supervisor). Shutdown stops engines in
reverse order and the shared Postgres last.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATES = ("off", "starting", "ready", "needs_model", "error", "stopped")


class EngineNotReady(Exception):
    """Raised by a spec factory when the user's setup can't run the engine yet."""

    def __init__(self, state: str, reason: str) -> None:
        super().__init__(reason)
        self.state = state
        self.reason = reason


@dataclass
class EngineSpec:
    name: str
    argv: list[str]
    env: dict[str, str]
    health_url: str
    cwd: str | None = None
    url: str = ""
    ready_timeout: float = 600.0  # first start downloads models
    log_path: Path | None = None
    before_start: list[list[str]] = field(default_factory=list)  # e.g. migrations
    on_ready: Callable[[], None] | None = None  # e.g. record a one-time setup step
    settle_seconds: float = 5.0  # no health_url: ready once alive this long (a worker)


@dataclass
class EngineStatus:
    state: str = "off"
    reason: str = ""
    url: str = ""
    pid: int | None = None
    restarts: int = 0
    started_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "reason": self.reason, "url": self.url, "pid": self.pid,
                "restarts": self.restarts, "started_at": self.started_at}


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback health
            return 200 <= int(response.status) < 300
    except Exception:  # noqa: BLE001
        return False


def _kill_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S603,S607
                       capture_output=True, check=False)
    else:
        process.kill()


class EngineSupervisor:
    def __init__(self, *, health_check: Callable[[str], bool] = http_ok,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 sleep: Callable[[float], None] = time.sleep,
                 poll_interval: float = 1.0) -> None:
        self._factories: list[tuple[str, Callable[[], EngineSpec]]] = []
        self._status: dict[str, EngineStatus] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._specs: dict[str, EngineSpec] = {}
        self._before_all: list[Callable[[], None]] = []
        self._after_all: list[Callable[[], None]] = []
        self._health = health_check
        self._popen = popen
        self._sleep = sleep
        self._poll = poll_interval
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    # -- configuration -------------------------------------------------------

    def add_engine(self, name: str, factory: Callable[[], EngineSpec]) -> None:
        self._factories.append((name, factory))
        self._status.setdefault(name, EngineStatus())

    def before_all(self, hook: Callable[[], None]) -> None:
        self._before_all.append(hook)

    def after_all(self, hook: Callable[[], None]) -> None:
        self._after_all.append(hook)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start everything in the background; returns immediately."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        for status in self._status.values():  # visible immediately, before the thread runs
            status.state, status.reason = "starting", ""
        self._thread = threading.Thread(target=self._run, name="memory-engines", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for hook in self._before_all:
                hook()
        except Exception as exc:  # noqa: BLE001 - shared Postgres failed: every engine is down
            logger.exception("[ENGINES] shared setup failed")
            for status in self._status.values():
                status.state, status.reason = "error", f"Database failed to start: {exc}"
            return
        for name, factory in self._factories:
            if self._stop.is_set():
                return
            self._launch(name, factory)
        self._watch()

    def _launch(self, name: str, factory: Callable[[], EngineSpec]) -> bool:
        status = self._status[name]
        try:
            spec = factory()
        except EngineNotReady as exc:
            status.state, status.reason = exc.state, exc.reason
            return False
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ENGINES] %s could not be configured", name)
            status.state, status.reason = "error", str(exc)
            return False
        status.state, status.reason, status.url = "starting", "", spec.url
        try:
            for step in spec.before_start:
                done = subprocess.run(step, env=spec.env, cwd=spec.cwd, capture_output=True,  # noqa: S603
                                      timeout=600, check=False)
                if done.returncode != 0:
                    tail = (done.stderr or done.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-3:]
                    raise RuntimeError(f"setup step failed ({' '.join(step[-2:])}): {' | '.join(tail)}")
            log = open(spec.log_path, "ab") if spec.log_path else subprocess.DEVNULL  # noqa: SIM115
            extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            process = self._popen(spec.argv, env=spec.env, cwd=spec.cwd, stdout=log, stderr=log,
                                  stdin=subprocess.DEVNULL, **extra)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[ENGINES] %s failed to start", name)
            status.state, status.reason = "error", f"Failed to start: {exc}"
            return False
        with self._lock:
            self._processes[name], self._specs[name] = process, spec
        status.pid, status.started_at = process.pid, time.time()
        deadline = time.monotonic() + spec.ready_timeout
        while not self._stop.is_set() and time.monotonic() < deadline:
            if process.poll() is not None:
                status.state, status.reason = "error", f"Exited during startup (code {process.returncode})"
                return False
            alive_for = time.time() - (status.started_at or time.time())
            if (self._health(spec.health_url) if spec.health_url else alive_for >= spec.settle_seconds):
                status.state = "ready"
                logger.info("[ENGINES] %s ready at %s", name, spec.url or "(worker)")
                if spec.on_ready is not None:
                    try:
                        spec.on_ready()
                    except Exception:  # noqa: BLE001
                        logger.exception("[ENGINES] %s on_ready failed", name)
                return True
            self._sleep(self._poll)
        if not self._stop.is_set():
            status.state, status.reason = "error", "Did not become ready in time"
            _kill_tree(process)
        return False

    def _watch(self) -> None:
        backoff: dict[str, float] = {}
        while not self._stop.is_set():
            for name, factory in self._factories:
                process = self._processes.get(name)
                status = self._status[name]
                if process is None or process.poll() is None or self._stop.is_set():
                    continue
                delay = backoff.get(name, 2.0)
                status.state, status.reason = "error", f"Stopped unexpectedly; restarting in {int(delay)}s"
                self._sleep(delay)
                if self._stop.is_set():
                    return
                status.restarts += 1
                backoff[name] = min(delay * 2, 60.0)
                if self._launch(name, factory):
                    backoff[name] = 2.0
            self._sleep(self._poll)

    def restart(self, name: str) -> None:
        """Restart one engine, e.g. after the user changes their model."""
        factory = dict(self._factories)[name]
        self._terminate(name)
        threading.Thread(target=self._launch, args=(name, factory), daemon=True).start()

    def _terminate(self, name: str) -> None:
        with self._lock:
            process = self._processes.pop(name, None)
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _kill_tree(process)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        for name, _factory in reversed(self._factories):
            self._terminate(name)
            self._status[name].state = "stopped"
            self._status[name].pid = None
        for hook in self._after_all:
            try:
                hook()
            except Exception:  # noqa: BLE001 - shutdown continues
                logger.exception("[ENGINES] shutdown hook failed")

    # -- status ------------------------------------------------------------------

    def status(self) -> dict[str, dict[str, Any]]:
        return {name: status.as_dict() for name, status in self._status.items()}

    def url(self, name: str) -> str:
        status = self._status.get(name)
        return status.url if status and status.state == "ready" else ""


def child_env(extra: dict[str, str]) -> dict[str, str]:
    """A clean environment for an engine: inherit PATH/SYSTEMROOT, drop Vellum's secrets."""
    keep = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
            "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE", "HOME", "LANG"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    # PYTHONIOENCODING: with output redirected to a log file, Windows uses the
    # legacy code page and engines that print Unicode (Hindsight's banner) crash.
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8", **extra})
    return env
