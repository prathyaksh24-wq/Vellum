from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

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
