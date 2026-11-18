"""The bundled EmbeddingGemma 2 runtime for installs without it in Ollama.

Vellum ships Google's EmbeddingGemma 2 (Q8_0 GGUF, Apache 2.0, the same
model Ollama serves) with llama.cpp's ``llama-server`` (MIT). The server
starts on first use on a free loopback port, belongs to a Windows job object
so it can never outlive the backend (even after a crash), and stops after
ten idle minutes to give back its ~400 MB of RAM; the next request restarts
it in a few seconds.
"""
from __future__ import annotations

import atexit
import json
import logging
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

SERVER_DIR = "llama-server"
IDLE_SECONDS = 600.0
READY_TIMEOUT = 120.0
# Google documents an 8,192-token input budget; one slot keeps it per input.
CONTEXT_TOKENS = 8192


def _resources() -> Path:
    # Packaged: <resources>/backend-runtime/python/python.exe -> <resources>
    return Path(sys.executable).resolve().parents[2]


def bundled_server_path(root: Path) -> Path | None:
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    for folder in (_resources() / "engine-runtimes" / SERVER_DIR, Path(root) / ".engines" / SERVER_DIR):
        if (folder / name).is_file():
            return folder / name
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=1.0) as response:  # noqa: S310 - loopback
            return response.status == 200 and json.loads(response.read() or b"{}").get("status", "ok") == "ok"
    except Exception:  # noqa: BLE001
        return False


class EmbeddingServer:
    def __init__(self, server: Path, model: Path, *, log_path: Path | None = None,
                 idle_seconds: float = IDLE_SECONDS) -> None:
        self.server, self.model, self.log_path = server, model, log_path
        self.idle_seconds = idle_seconds
        self._process: subprocess.Popen | None = None
        self._job = None
        self._url = ""
        self._last_used = 0.0
        self._lock = threading.RLock()
        self._reaper: threading.Thread | None = None

    def url(self) -> str:
        """The running server's base URL, starting it if needed."""
        with self._lock:
            self._last_used = time.monotonic()
            if self._process is not None and self._process.poll() is None:
                return self._url
            self._start()
            return self._url

    def _start(self) -> None:
        port = _free_port()
        argv = [str(self.server), "-m", str(self.model), "--embeddings", "--host", "127.0.0.1", "--port", str(port),
                "-c", str(CONTEXT_TOKENS), "-b", str(CONTEXT_TOKENS), "-ub", str(CONTEXT_TOKENS),
                "--parallel", "1", "--no-webui"]
        log = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL  # noqa: SIM115
        extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        try:
            process = subprocess.Popen(argv, stdout=log, stderr=log, stdin=subprocess.DEVNULL,  # noqa: S603
                                       cwd=str(self.server.parent), **extra)
        finally:
            if log is not subprocess.DEVNULL:
                log.close()
        self._attach_job(process.pid)
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"The bundled embedding model stopped while starting (code {process.returncode}).")
            if _healthy(url):
                self._process, self._url = process, url
                logger.info("[EMBEDDINGS] bundled EmbeddingGemma 2 ready at %s", url)
                self._ensure_reaper()
                return
            time.sleep(0.25)
        process.kill()
        raise RuntimeError("The bundled embedding model did not start in time.")

    def _attach_job(self, pid: int) -> None:
        if sys.platform != "win32":
            return
        try:
            if self._job is None:
                from agent.mcp.windows_browser_job import WindowsBrowserJob

                self._job = WindowsBrowserJob()
            self._job.assign(pid)
        except Exception:  # noqa: BLE001 - atexit still stops it on a normal exit
            logger.warning("[EMBEDDINGS] could not tie the embedding server to the backend's lifetime")

    def _ensure_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._reaper = threading.Thread(target=self._reap, name="embedding-server-idle", daemon=True)
        self._reaper.start()

    def _reap(self) -> None:
        while True:
            time.sleep(min(30.0, self.idle_seconds))
            with self._lock:
                if self._process is None or self._process.poll() is not None:
                    return
                if time.monotonic() - self._last_used >= self.idle_seconds:
                    logger.info("[EMBEDDINGS] idle; stopping the bundled embedding model")
                    self._stop_locked()
                    return

    def _stop_locked(self) -> None:
        process, self._process, self._url = self._process, None, ""
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()


_server: EmbeddingServer | None = None
_server_lock = threading.Lock()


def get_embedding_server() -> EmbeddingServer:
    """The process-wide bundled embedding server (not started until first use)."""
    global _server
    with _server_lock:
        if _server is None:
            from agent.config import REPO_ROOT
            from agent.rag.embedding_profile import bundled_model_path

            server, model = bundled_server_path(REPO_ROOT), bundled_model_path(REPO_ROOT)
            if server is None or model is None:
                raise RuntimeError("The bundled embedding model is missing from this build.")
            log = Path(REPO_ROOT) / "data" / "embeddings" / "embedding-server.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            _server = EmbeddingServer(server, model, log_path=log)
            atexit.register(_server.stop)
        return _server
