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
    for name in ("backend/pyproject.toml", "docs/SOUL.md"):
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
    build_id = json.loads(manifest.read_text(encoding="utf-8"))["build_id"] if manifest.is_file() else source_build_id()
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


def main(*, standalone: bool = False) -> None:
    acquire_workspace_lease()
    os.chdir(workspace_root())
    # Child workers inherit these defaults, including the packaged interpreter.
    for key, value in {"OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "HF_HUB_DISABLE_XET": "1"}.items():
        os.environ.setdefault(key, value)
    import uvicorn
    from agent.api import app

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
