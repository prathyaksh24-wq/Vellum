"""Atomic, verifiable backups for the local Personal Intelligence store."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from agent.knowledge.store import KnowledgeStore, SCHEMA_VERSION


class KnowledgeBackupError(RuntimeError):
    pass


class KnowledgeBackupService:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def create(self, destination: str | Path) -> dict[str, Any]:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(handle)
        temporary_archive = Path(temporary_name)
        try:
            with tempfile.TemporaryDirectory(prefix="vellum-knowledge-backup-") as temp_dir:
                temp_root = Path(temp_dir)
                database_copy = temp_root / "core.db"
                self.store.backup_database(database_copy)
                database_check = self._check_database(database_copy)
                if not database_check["ok"]:
                    raise KnowledgeBackupError("Knowledge database failed integrity verification before backup.")

                entries = [self._entry("core.db", database_copy)]
                blob_files = self._blob_files()
                entries.extend(self._entry(f"blobs/{relative.as_posix()}", path) for relative, path in blob_files)
                manifest = {
                    "format": "vellum-knowledge-backup-v1",
                    "created_at": datetime.now(UTC).isoformat(),
                    "schema_version": database_check["schema_version"],
                    "entries": entries,
                }
                with zipfile.ZipFile(
                    temporary_archive,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive:
                    archive.write(database_copy, "core.db")
                    for relative, path in blob_files:
                        archive.write(path, f"blobs/{relative.as_posix()}")
                    archive.writestr(
                        "manifest.json",
                        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    )
            verified = self.verify(temporary_archive)
            os.replace(temporary_archive, target)
            return {**verified, "path": str(target)}
        finally:
            temporary_archive.unlink(missing_ok=True)

    def verify(self, archive_path: str | Path) -> dict[str, Any]:
        target = Path(archive_path).expanduser().resolve()
        if not target.is_file():
            raise KnowledgeBackupError("Knowledge backup does not exist.")
        with zipfile.ZipFile(target, "r") as archive:
            name_list = archive.namelist()
            names = set(name_list)
            if len(names) != len(name_list):
                raise KnowledgeBackupError("Knowledge backup contains duplicate paths.")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise KnowledgeBackupError("Knowledge backup contains an unsafe path.")
            if {"manifest.json", "core.db"} - names:
                raise KnowledgeBackupError("Knowledge backup is incomplete.")
            if archive.testzip() is not None:
                raise KnowledgeBackupError("Knowledge backup contains corrupt compressed data.")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (KeyError, json.JSONDecodeError) as exc:
                raise KnowledgeBackupError("Knowledge backup manifest is invalid.") from exc
            if manifest.get("format") != "vellum-knowledge-backup-v1":
                raise KnowledgeBackupError("Knowledge backup format is unsupported.")
            entries = manifest.get("entries")
            if not isinstance(entries, list):
                raise KnowledgeBackupError("Knowledge backup manifest entries are invalid.")
            entry_names = [str(entry.get("path") or "") for entry in entries if isinstance(entry, dict)]
            if len(entry_names) != len(entries) or set(entry_names) != names - {"manifest.json"}:
                raise KnowledgeBackupError("Knowledge backup manifest does not match archive contents.")
            for entry in entries:
                if not isinstance(entry, dict) or str(entry.get("path") or "") not in names:
                    raise KnowledgeBackupError("Knowledge backup manifest does not match archive contents.")
                content = archive.read(str(entry["path"]))
                if len(content) != int(entry.get("size") or -1):
                    raise KnowledgeBackupError("Knowledge backup entry size mismatch.")
                if hashlib.sha256(content).hexdigest() != str(entry.get("sha256") or ""):
                    raise KnowledgeBackupError("Knowledge backup entry checksum mismatch.")
            with tempfile.TemporaryDirectory(prefix="vellum-knowledge-verify-") as temp_dir:
                database_copy = Path(temp_dir) / "core.db"
                database_copy.write_bytes(archive.read("core.db"))
                database_check = self._check_database(database_copy)
        if not database_check["ok"]:
            raise KnowledgeBackupError("Knowledge backup database failed integrity verification.")
        return {
            "valid": True,
            "format": manifest["format"],
            "schema_version": database_check["schema_version"],
            "entry_count": len(entries),
            "created_at": str(manifest.get("created_at") or ""),
        }

    def _blob_files(self) -> list[tuple[Path, Path]]:
        root = self.store.blobs.root.resolve()
        if not root.is_dir():
            return []
        files: list[tuple[Path, Path]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise KnowledgeBackupError("Knowledge blob path escapes the blob root.")
            files.append((resolved.relative_to(root), resolved))
        return files

    @staticmethod
    def _entry(name: str, path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return {"path": name, "sha256": digest.hexdigest(), "size": size}

    @staticmethod
    def _check_database(path: Path) -> dict[str, Any]:
        try:
            with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.DatabaseError as exc:
            raise KnowledgeBackupError("Knowledge backup database is unreadable.") from exc
        return {
            "ok": integrity.casefold() == "ok" and not foreign_keys and 0 < version <= SCHEMA_VERSION,
            "schema_version": version,
            "sqlite": integrity,
            "foreign_key_errors": len(foreign_keys),
        }
