from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import os
from pathlib import Path
import time
from typing import Iterator


class SkillLockTimeout(TimeoutError):
    pass


class _FileLock:
    def __init__(self, path: Path, *, timeout: float, poll_interval: float):
        self.path = path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._handle = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"0")
            self._handle.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock()
                return self
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise SkillLockTimeout(f"timed out waiting for skill lock: {self.path.name}")
                time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        try:
            self._unlock()
        finally:
            self._handle.close()
            self._handle = None

    def _lock(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)


class SkillLockManager:
    """Cross-process locks keyed by normalized skill identity."""

    def __init__(self, root: str | Path, *, timeout: float = 10.0, poll_interval: float = 0.05):
        self.root = Path(root)
        self.timeout = timeout
        self.poll_interval = poll_interval

    @staticmethod
    def normalize(name: str) -> str:
        normalized = "-".join(name.strip().casefold().split())
        if not normalized:
            raise ValueError("skill name is required")
        return normalized

    def path_for(self, name: str) -> Path:
        normalized = self.normalize(name)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.lock"

    @contextmanager
    def acquire(self, name: str) -> Iterator[None]:
        with _FileLock(self.path_for(name), timeout=self.timeout, poll_interval=self.poll_interval):
            yield

    @contextmanager
    def acquire_many(self, names: list[str]) -> Iterator[None]:
        ordered = sorted({self.normalize(name) for name in names})
        with ExitStack() as stack:
            for name in ordered:
                stack.enter_context(self.acquire(name))
            yield
