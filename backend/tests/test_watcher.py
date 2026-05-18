from types import SimpleNamespace

from agent.obsidian import watcher as watcher_mod
from agent.obsidian.watcher import VaultWatcher, start_vault_watcher


class FakeIngester:
    def __init__(self):
        self.ingested = []
        self.deleted = []

    def ingest_file(self, path):
        self.ingested.append(path)
        return 1

    def delete_file_records(self, path):
        self.deleted.append(path)


class FakeObserver:
    def __init__(self):
        self.scheduled = []
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path, recursive=True):
        self.scheduled.append((handler, path, recursive))

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        self.joined = True


def test_watcher_reindexes_markdown_changes_immediately(tmp_path):
    note = tmp_path / "Sports" / "NBA" / "latest.md"
    note.parent.mkdir(parents=True)
    note.write_text("NBA", encoding="utf-8")
    ingester = FakeIngester()

    watcher = VaultWatcher(
        vault_root=tmp_path,
        ingester_factory=lambda: ingester,
        debounce_seconds=0,
        observer=FakeObserver(),
    )
    watcher.handle_path(note, "upsert")

    assert ingester.ingested == [note.resolve()]
    assert ingester.deleted == []


def test_watcher_deletes_index_records_for_deleted_notes(tmp_path):
    note = tmp_path / "Books" / "private.md"
    note.parent.mkdir(parents=True)
    ingester = FakeIngester()

    watcher = VaultWatcher(
        vault_root=tmp_path,
        ingester_factory=lambda: ingester,
        debounce_seconds=0,
        observer=FakeObserver(),
    )
    watcher.handle_path(note, "delete")

    assert ingester.ingested == []
    assert ingester.deleted == [note.resolve()]


def test_watcher_ignores_non_markdown_files(tmp_path):
    ingester = FakeIngester()
    watcher = VaultWatcher(
        vault_root=tmp_path,
        ingester_factory=lambda: ingester,
        debounce_seconds=0,
        observer=FakeObserver(),
    )

    watcher.handle_path(tmp_path / "image.png", "upsert")

    assert ingester.ingested == []
    assert ingester.deleted == []


def test_watcher_handles_ingester_factory_failure(tmp_path):
    note = tmp_path / "Agent" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("note", encoding="utf-8")

    def broken_factory():
        raise RuntimeError("vector store unavailable")

    watcher = VaultWatcher(
        vault_root=tmp_path,
        ingester_factory=broken_factory,
        debounce_seconds=0,
        observer=FakeObserver(),
    )

    watcher.handle_path(note, "upsert")


def test_start_vault_watcher_starts_and_stops_provided_watcher(monkeypatch, tmp_path):
    observer = FakeObserver()
    watcher = VaultWatcher(vault_root=tmp_path, debounce_seconds=0, observer=observer)
    settings = SimpleNamespace(enable_vault_watcher=True, enable_vector_search=True)

    monkeypatch.setattr(watcher_mod, "get_settings", lambda: settings)
    started = start_vault_watcher(watcher)
    started.stop()

    assert started is watcher
    assert observer.started is True
    assert observer.stopped is True
    assert observer.joined is True


def test_start_vault_watcher_skips_when_vector_search_disabled(monkeypatch, tmp_path):
    observer = FakeObserver()
    watcher = VaultWatcher(vault_root=tmp_path, debounce_seconds=0, observer=observer)
    settings = SimpleNamespace(enable_vault_watcher=True, enable_vector_search=False)

    monkeypatch.setattr(watcher_mod, "get_settings", lambda: settings)

    assert start_vault_watcher(watcher) is None
    assert observer.started is False
