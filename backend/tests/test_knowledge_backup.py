from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from agent.knowledge import backup as backup_module
from agent.knowledge.backup import KnowledgeBackupError, KnowledgeBackupService
from agent.knowledge.models import ExternalPolicy, Sensitivity, SourceItemInput
from agent.knowledge.store import KnowledgeStore


def build_store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(
        tmp_path / "data" / "knowledge" / "core.db",
        tmp_path / "data" / "knowledge" / "blobs",
    )


def test_backup_is_atomic_complete_and_verifiable(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    store.upsert_source(
        SourceItemInput(
            kind="book_page",
            external_id="book:1:page:1",
            title="Private page",
            content="Local-only text.",
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            external_policy=ExternalPolicy.DENY_RAW,
        )
    )
    archive = tmp_path / "backups" / "knowledge.zip"

    created = KnowledgeBackupService(store).create(archive)
    verified = KnowledgeBackupService(store).verify(archive)

    assert created["valid"] is True
    assert verified["schema_version"] == store.status()["schema_version"]
    assert verified["entry_count"] == 2
    assert archive.is_file()
    with zipfile.ZipFile(archive) as backup:
        assert {"manifest.json", "core.db"} <= set(backup.namelist())
        assert any(name.startswith("blobs/sha256/") for name in backup.namelist())


def test_backup_verification_rejects_checksum_mismatch(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    store.upsert_source(SourceItemInput(kind="note", external_id="note-1", content="Original"))
    archive = tmp_path / "knowledge.zip"
    service = KnowledgeBackupService(store)
    service.create(archive)

    corrupt = tmp_path / "knowledge-corrupt.zip"
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(corrupt, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name.startswith("blobs/"):
                content = b"x" * len(content)
            target.writestr(name, content)

    with pytest.raises(KnowledgeBackupError, match="checksum mismatch"):
        service.verify(corrupt)


def test_live_store_integrity_check_is_clean(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    assert store.integrity_check() == {
        "ok": True,
        "sqlite": "ok",
        "foreign_key_errors": 0,
    }


def test_restore_replaces_store_and_preserves_pre_restore_backup(tmp_path: Path) -> None:
    source_store = KnowledgeStore(
        tmp_path / "source" / "core.db",
        tmp_path / "source" / "blobs",
    )
    source_store.upsert_source(
        SourceItemInput(
            kind="youtube_takeout_video",
            external_id="youtube:video:restored",
            title="Restored source",
            content="Restored private watch event.",
            sensitivity=Sensitivity.PRIVATE_LOCAL_ONLY,
            external_policy=ExternalPolicy.DENY_RAW,
        )
    )
    archive = tmp_path / "source.zip"
    KnowledgeBackupService(source_store).create(archive)

    destination_store = KnowledgeStore(
        tmp_path / "destination" / "core.db",
        tmp_path / "destination" / "blobs",
    )
    destination_store.upsert_source(
        SourceItemInput(
            kind="note",
            external_id="current-note",
            title="Current source",
            content="Current content.",
        )
    )
    rollback = tmp_path / "rollback.zip"

    result = KnowledgeBackupService(destination_store).restore(
        archive,
        rollback_destination=rollback,
    )

    assert result["restored"] is True
    assert result["integrity"]["ok"] is True
    assert result["rollback"]["path"] == str(rollback.resolve())
    assert [source["title"] for source in destination_store.list_sources()] == ["Restored source"]
    assert KnowledgeBackupService(destination_store).verify(rollback)["valid"] is True


def test_restore_rolls_back_live_store_when_activation_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_store = KnowledgeStore(
        tmp_path / "source" / "core.db",
        tmp_path / "source" / "blobs",
    )
    source_store.upsert_source(
        SourceItemInput(
            kind="youtube_takeout_video",
            external_id="youtube:video:new",
            title="New source",
            content="New content.",
        )
    )
    archive = tmp_path / "source.zip"
    KnowledgeBackupService(source_store).create(archive)

    destination_store = KnowledgeStore(
        tmp_path / "destination" / "core.db",
        tmp_path / "destination" / "blobs",
    )
    destination_store.upsert_source(
        SourceItemInput(
            kind="note",
            external_id="current-note",
            title="Current source",
            content="Current content.",
        )
    )
    live_blobs = destination_store.blobs.root.resolve()
    real_replace = backup_module.os.replace

    def fail_blob_activation(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        if Path(destination).resolve() == live_blobs and ".restore-" in source_path.name:
            raise OSError("simulated activation failure")
        real_replace(source, destination)

    monkeypatch.setattr(backup_module.os, "replace", fail_blob_activation)

    with pytest.raises(KnowledgeBackupError, match="was rolled back"):
        KnowledgeBackupService(destination_store).restore(archive)

    assert [source["title"] for source in destination_store.list_sources()] == ["Current source"]
    rollback_archives = list((destination_store.db_path.parent / "backups").glob("pre-restore-*.zip"))
    assert len(rollback_archives) == 1
