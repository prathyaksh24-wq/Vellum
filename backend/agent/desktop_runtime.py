"""Desktop startup protocol and the single-writer lease for a local workspace.

No models or application stores are imported here. The desktop launcher takes
the lease before importing the API, so a second app cannot open the same data.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import threading

PROTOCOL_VERSION = 1
SOURCE_ROOT = Path(__file__).resolve().parents[2]
_lease = None
_serving = False


def serving() -> bool:
    """True only inside the real backend process started by main()."""
    return _serving


def workspace_root() -> Path:
    selected = os.environ.get("VELLUM_WORKSPACE_ROOT")
    if selected and not Path(selected).is_absolute():
        raise ValueError("VELLUM_WORKSPACE_ROOT must be absolute.")
    return Path(selected).resolve() if selected else SOURCE_ROOT


def source_files(root: Path = SOURCE_ROOT) -> list[Path]:
    files = []
    for directory in ("backend/agent", "plugins", "scripts"):
        files.extend(p for p in (root / directory).rglob("*")
                     if p.is_file() and not p.is_symlink() and p.suffix in {".py", ".json", ".yaml", ".yml", ".ps1", ".md", ".txt"}
                     and not any(part in {"__pycache__", "node_modules", ".git", "tests"} for part in p.relative_to(root).parts)
                     and p.name not in {"auth.json", "oauth-flow.json"})
    for name in ("backend/pyproject.toml", "docs/main.md", "docs/SOUL.md", "docs/PERSONALITY.md"):
        if (root / name).is_file():
            files.append(root / name)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def source_build_id(root: Path = SOURCE_ROOT) -> str:
    """Content identity, shared with desktop/electron/backend.cjs."""
    digest = hashlib.sha256()
    for file in source_files(root):
        digest.update(file.relative_to(root).as_posix().encode() + b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_identity() -> dict:
    manifest = SOURCE_ROOT / "desktop-backend.json"
    # The desktop host already hashed this source tree to launch it; reuse that
    # value instead of reading every source file again during startup.
    launched = os.environ.get("VELLUM_DESKTOP_BUILD_ID", "")
    if manifest.is_file():
        build_id = json.loads(manifest.read_text(encoding="utf-8"))["build_id"]
    elif len(launched) == 64 and all(c in "0123456789abcdef" for c in launched):
        build_id = launched
    else:
        build_id = source_build_id()
    return {"service": "vellum", "protocol_version": PROTOCOL_VERSION,
            "workspace_root": str(workspace_root()), "build_id": build_id,
            "pid": os.getpid(), "launch_id": os.environ.get("VELLUM_DESKTOP_LAUNCH_ID") or None}


def acquire_workspace_lease() -> None:
    global _lease
    if _lease is not None:
        return
    directory = workspace_root() / ".api-runtime"
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "workspace.lock").open("a+b")
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("This Vellum workspace already has a backend. Use that instance or quit it first.") from None
    _lease = handle  # OS releases the lock on process exit, including a crash.


def start_loop_watchdog(loop, *, interval: float = 5.0, stall_after: float = 10.0, log_path: Path | None = None) -> threading.Event:
    """Record every thread's stack when the event loop stops answering.

    A blocked loop makes the whole API unreachable while the process looks
    alive. The desktop host restarts it; this log says what blocked it.
    """
    import faulthandler
    import time

    stop = threading.Event()
    path = log_path or workspace_root() / ".api-runtime" / "backend-stall.log"

    def watch() -> None:
        reported = False
        while not stop.wait(interval):
            answered = threading.Event()
            try:
                loop.call_soon_threadsafe(answered.set)
            except RuntimeError:
                return  # The loop has closed.
            if answered.wait(stall_after):
                reported = False
                continue
            if reported:
                continue
            reported = True
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as log:
                    log.write(f"\n=== Event loop unresponsive for {stall_after:.0f}s at "
                              f"{time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()}) ===\n")
                    log.flush()
                    faulthandler.dump_traceback(file=log, all_threads=True)
            except OSError:
                pass

    threading.Thread(target=watch, name="vellum-loop-watchdog", daemon=True).start()
    return stop


async def prestart_worker_threads(loop, *, executor_workers: int = 32, threadpool_workers: int = 40) -> None:
    """Start every worker thread the API will use before it serves requests.

    On Windows, starting a thread waits for the process loader lock. A long
    native-library load (scipy, torch, spaCy) holds that lock, so a request that
    had to create a worker at that moment froze the whole event loop. Workers
    created up front are reused for the life of the process.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    executor = ThreadPoolExecutor(max_workers=executor_workers, thread_name_prefix="vellum-worker")
    loop.set_default_executor(executor)
    gate = threading.Barrier(executor_workers + 1)
    for _ in range(executor_workers):
        executor.submit(gate.wait, 30)
    try:
        # Startup only: nothing is served yet, so waiting here is harmless.
        gate.wait(30)
    except threading.BrokenBarrierError:
        pass

    # Starlette runs sync endpoints on AnyIO's pool, whose idle workers would
    # otherwise exit after 10 seconds and be re-created later on demand.
    try:
        import anyio
        from anyio._backends import _asyncio as anyio_asyncio

        worker = getattr(anyio_asyncio, "WorkerThread", None)
        if worker is not None and hasattr(worker, "MAX_IDLE_TIME"):
            worker.MAX_IDLE_TIME = 24 * 60 * 60
        limiter = anyio.to_thread.current_default_thread_limiter()
        count = min(threadpool_workers, int(limiter.total_tokens))
        anyio_gate = threading.Barrier(count)
        async with anyio.create_task_group() as group:
            for _ in range(count):
                group.start_soon(anyio.to_thread.run_sync, anyio_gate.wait, 30)
    except Exception:
        pass


_STARTED = None


def startup_mark(phase: str) -> None:
    """Write one startup timing line to the backend log (stderr)."""
    import time

    if _STARTED is not None:
        print(f"[Vellum startup] {phase}: {time.perf_counter() - _STARTED:.2f}s", file=sys.stderr, flush=True)


def main(*, standalone: bool = False) -> None:
    global _serving, _STARTED
    import time

    _STARTED = time.perf_counter()
    _serving = True
    acquire_workspace_lease()
    os.chdir(workspace_root())
    # Child workers inherit these defaults, including the packaged interpreter.
    for key, value in {"OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "HF_HUB_DISABLE_XET": "1"}.items():
        os.environ.setdefault(key, value)
    import uvicorn
    # Pin this install's embedding model before any settings are read: Ollama's
    # EmbeddingGemma when present, otherwise the model bundled with Vellum.
    from agent.rag.embedding_profile import ensure_profile
    ensure_profile(workspace_root(), os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434")
    startup_mark("runtime ready")
    from agent.api import app
    startup_mark("API imported")

    host = os.environ.get("API_HOST", "127.0.0.1") if standalone else "127.0.0.1"
    port = int(os.environ.get("API_PORT", "8000")) if standalone else 8000
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, access_log=False))

    def parent_control():
        # This pipe belongs only to the spawning desktop process. EOF also
        # shuts down a child whose desktop host crashed; no public stop API.
        for line in sys.stdin:
            if line.strip() == "stop":
                break
        server.should_exit = True

    if not standalone:
        threading.Thread(target=parent_control, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
