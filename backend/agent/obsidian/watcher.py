"""Watch the Obsidian vault and keep the local vector index fresh."""

from __future__ import annotations

from pathlib import Path
import logging
from threading import Lock, Timer
from typing import Callable, Literal

from agent.config import get_settings
from agent.obsidian.ingester import VaultIngester

logger = logging.getLogger(__name__)

WatchAction = Literal["upsert", "delete"]


class VaultWatcher:
    def __init__(
        self,
        *,
        vault_root: str | Path | None = None,
        ingester_factory: Callable[[], VaultIngester] = VaultIngester,
        debounce_seconds: float | None = None,
        observer=None,
    ):
        settings = get_settings()
        self.vault_root = Path(vault_root or settings.obsidian_vault_path).expanduser().resolve()
        self.ingester_factory = ingester_factory
        self.debounce_seconds = (
            debounce_seconds
            if debounce_seconds is not None
            else settings.vault_watcher_debounce_seconds
        )
        self.observer = observer
        self._handler = None
        self._timer: Timer | None = None
        self._pending: dict[Path, WatchAction] = {}
        self._lock = Lock()

    def start(self) -> "VaultWatcher":
        if self.observer is None:
            try:
                from watchdog.observers import Observer
            except ImportError as exc:
                raise RuntimeError("watchdog is required for vault auto-reindexing.") from exc
            self.observer = Observer()

        self._handler = _MarkdownEventHandler(self)
        self.observer.schedule(self._handler, str(self.vault_root), recursive=True)
        self.observer.start()
        logger.info("[OBSIDIAN] Vault watcher started for %s", self.vault_root)
        return self

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()

        if self.observer is not None:
            self.observer.stop()
            self.observer.join(timeout=5)
            logger.info("[OBSIDIAN] Vault watcher stopped.")

    def handle_path(self, path: str | Path, action: WatchAction = "upsert") -> None:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.vault_root / target
        target = target.resolve()
        if not _is_markdown(target):
            return
        if not target.is_relative_to(self.vault_root):
            logger.warning("[OBSIDIAN] Ignoring watcher event outside vault: %s", target)
            return

        with self._lock:
            self._pending[target] = action
            if self._timer is not None:
                self._timer.cancel()
            if self.debounce_seconds <= 0:
                self._flush_locked()
                return
            self._timer = Timer(self.debounce_seconds, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        pending = dict(self._pending)
        self._pending.clear()
        self._timer = None
        if not pending:
            return

        ingester = self.ingester_factory()
        for path, action in pending.items():
            try:
                if action == "delete" or not path.exists():
                    ingester.delete_file_records(path)
                    logger.info("[OBSIDIAN] Removed deleted note from index: %s", path)
                else:
                    chunks = ingester.ingest_file(path)
                    logger.info("[OBSIDIAN] Reindexed %s chunks from %s", chunks, path)
            except Exception as exc:
                logger.warning("[OBSIDIAN] Failed to process watcher event for %s: %s", path, exc)


class _MarkdownEventHandler:
    def __init__(self, watcher: VaultWatcher):
        try:
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            FileSystemEventHandler = object

        class Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    watcher.handle_path(event.src_path, "upsert")

            def on_modified(self, event):
                if not event.is_directory:
                    watcher.handle_path(event.src_path, "upsert")

            def on_deleted(self, event):
                if not event.is_directory:
                    watcher.handle_path(event.src_path, "delete")

            def on_moved(self, event):
                if not event.is_directory:
                    watcher.handle_path(event.src_path, "delete")
                    watcher.handle_path(event.dest_path, "upsert")

        self._handler = Handler()

    def __getattr__(self, name):
        return getattr(self._handler, name)


def start_vault_watcher(watcher: VaultWatcher | None = None) -> VaultWatcher | None:
    settings = get_settings()
    if not settings.enable_vault_watcher:
        logger.info("[OBSIDIAN] Vault watcher disabled.")
        return None

    try:
        return (watcher or VaultWatcher()).start()
    except Exception as exc:
        logger.warning("[OBSIDIAN] Vault watcher unavailable: %s", exc)
        return None


def _is_markdown(path: Path) -> bool:
    return path.suffix.casefold() == ".md"
