"""Atomic, verifiable backups for the local Personal Intelligence store."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
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
                if name not in {"manifest.json", "core.db"} and not name.startswith("blobs/"):
                    raise KnowledgeBackupError("Knowledge backup contains an unsupported path.")
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
                self._check_archive_blob_references(archive, database_copy)
        if not database_check["ok"]:
            raise KnowledgeBackupError("Knowledge backup database failed integrity verification.")
        return {
            "valid": True,
            "format": manifest["format"],
            "schema_version": database_check["schema_version"],
            "entry_count": len(entries),
            "created_at": str(manifest.get("created_at") or ""),
        }

    def restore(
        self,
        archive_path: str | Path,
        *,
        rollback_destination: str | Path | None = None,
    ) -> dict[str, Any]:
        source = Path(archive_path).expanduser().resolve()
        verified = self.verify(source)
        rollback = (
            Path(rollback_destination).expanduser().resolve()
            if rollback_destination is not None
            else self._default_rollback_path()
        )
        if rollback == source:
            raise KnowledgeBackupError("Rollback destination must differ from the restore archive.")

        rollback_result = self.create(rollback)
        database_parent = self.store.db_path.expanduser().resolve().parent
        blob_parent = self.store.blobs.root.expanduser().resolve().parent
        database_parent.mkdir(parents=True, exist_ok=True)
        blob_parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix=".vellum-knowledge-db-restore-",
            dir=database_parent,
        ) as database_temp, tempfile.TemporaryDirectory(
            prefix=".vellum-knowledge-blob-restore-",
            dir=blob_parent,
        ) as blob_temp:
            staged_database = Path(database_temp) / "core.db"
            staged_blobs = Path(blob_temp) / "blobs"
            self._extract(source, staged_database, staged_blobs)
            KnowledgeStore(staged_database, staged_blobs)
            self._checkpoint_live_database(staged_database)
            staged_check = self._check_database(staged_database)
            self._check_blob_files(staged_database, staged_blobs)
            if not staged_check["ok"]:
                raise KnowledgeBackupError("Staged knowledge database failed integrity verification.")
            self._activate(staged_database, staged_blobs)

        live_check = self.store.integrity_check()
        self._check_blob_files(self.store.db_path, self.store.blobs.root)
        return {
            "restored": True,
            "archive": str(source),
            "archive_schema_version": verified["schema_version"],
            "schema_version": self.store.status()["schema_version"],
            "entry_count": verified["entry_count"],
            "integrity": live_check,
            "rollback": {
                "path": str(rollback),
                "valid": rollback_result["valid"],
                "entry_count": rollback_result["entry_count"],
            },
        }

    def _default_rollback_path(self) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self.store.db_path.parent / "backups" / f"pre-restore-{timestamp}.zip"

    @staticmethod
    def _extract(source: Path, staged_database: Path, staged_blobs: Path) -> None:
        staged_blobs.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(source, "r") as archive:
            with archive.open("core.db", "r") as input_file, staged_database.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            for name in sorted(archive.namelist()):
                if not name.startswith("blobs/") or name.endswith("/"):
                    continue
                relative = PurePosixPath(name).relative_to("blobs")
                target = staged_blobs.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name, "r") as input_file, target.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)

    def _activate(self, staged_database: Path, staged_blobs: Path) -> None:
        database = self.store.db_path.expanduser().resolve()
        blobs = self.store.blobs.root.expanduser().resolve()
        token = uuid.uuid4().hex
        prepared_database = database.with_name(f".{database.name}.restore-{token}")
        previous_database = database.with_name(f".{database.name}.previous-{token}")
        prepared_blobs = blobs.with_name(f".{blobs.name}.restore-{token}")
        previous_blobs = blobs.with_name(f".{blobs.name}.previous-{token}")
        sidecars = [Path(f"{database}-wal"), Path(f"{database}-shm")]
        previous_sidecars = [Path(f"{path}.previous-{token}") for path in sidecars]

        moved_database = False
        moved_blobs = False
        installed_database = False
        installed_blobs = False
        moved_sidecars: list[tuple[Path, Path]] = []
        try:
            self._checkpoint_live_database(database)
            os.replace(staged_database, prepared_database)
            os.replace(staged_blobs, prepared_blobs)
            if database.exists():
                os.replace(database, previous_database)
                moved_database = True
            if blobs.exists():
                os.replace(blobs, previous_blobs)
                moved_blobs = True
            for sidecar, previous in zip(sidecars, previous_sidecars, strict=True):
                if sidecar.exists():
                    os.replace(sidecar, previous)
                    moved_sidecars.append((sidecar, previous))
            os.replace(prepared_database, database)
            installed_database = True
            os.replace(prepared_blobs, blobs)
            installed_blobs = True
            live_check = self._check_database(database)
            self._check_blob_files(database, blobs)
            if not live_check["ok"]:
                raise KnowledgeBackupError("Restored knowledge database failed integrity verification.")
        except Exception as exc:
            rollback_errors: list[str] = []
            try:
                if database.exists() and installed_database:
                    database.unlink()
                if blobs.exists() and installed_blobs:
                    shutil.rmtree(blobs)
                if moved_database and previous_database.exists():
                    os.replace(previous_database, database)
                if moved_blobs and previous_blobs.exists():
                    os.replace(previous_blobs, blobs)
                for sidecar, previous in moved_sidecars:
                    if previous.exists():
                        os.replace(previous, sidecar)
            except Exception as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(type(rollback_exc).__name__)
            detail = f" ({', '.join(rollback_errors)})" if rollback_errors else ""
            raise KnowledgeBackupError(f"Knowledge restore activation failed and was rolled back{detail}.") from exc
        finally:
            prepared_database.unlink(missing_ok=True)
            if prepared_blobs.exists():
                shutil.rmtree(prepared_blobs)

        previous_database.unlink(missing_ok=True)
        if previous_blobs.exists():
            shutil.rmtree(previous_blobs)
        for _sidecar, previous in moved_sidecars:
            previous.unlink(missing_ok=True)

    @staticmethod
    def _checkpoint_live_database(database: Path) -> None:
        if not database.exists():
            return
        try:
            with closing(sqlite3.connect(database, timeout=5)) as connection:
                connection.execute("PRAGMA busy_timeout = 5000")
                result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.DatabaseError as exc:
            raise KnowledgeBackupError("Knowledge database could not enter restore maintenance mode.") from exc
        if result is not None and int(result[0]) != 0:
            raise KnowledgeBackupError("Knowledge database is busy; stop Vellum before restoring.")

    @classmethod
    def _check_archive_blob_references(cls, archive: zipfile.ZipFile, database: Path) -> None:
        names = set(archive.namelist())
        for content_hash, blob_path, byte_size in cls._database_blob_references(database):
            cls._validate_blob_reference(content_hash, blob_path)
            archive_name = f"blobs/{blob_path}"
            if archive_name not in names:
                raise KnowledgeBackupError("Knowledge backup is missing a referenced blob.")
            try:
                with archive.open(archive_name, "r") as compressed:
                    cls._verify_blob_stream(compressed, content_hash, byte_size)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                raise KnowledgeBackupError("Knowledge backup contains an unreadable blob.") from exc

    @classmethod
    def _check_blob_files(cls, database: Path, blob_root: Path) -> None:
        root = blob_root.resolve()
        for content_hash, blob_path, byte_size in cls._database_blob_references(database):
            cls._validate_blob_reference(content_hash, blob_path)
            target = (root / blob_path).resolve()
            if not target.is_relative_to(root) or not target.is_file() or target.is_symlink():
                raise KnowledgeBackupError("Knowledge store is missing a referenced blob.")
            try:
                with target.open("rb") as compressed:
                    cls._verify_blob_stream(compressed, content_hash, byte_size)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                raise KnowledgeBackupError("Knowledge store contains an unreadable blob.") from exc

    @staticmethod
    def _database_blob_references(database: Path) -> list[tuple[str, str, int]]:
        try:
            with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
                rows = connection.execute(
                    "SELECT content_hash, blob_path, byte_size FROM source_versions WHERE blob_path <> ''"
                ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise KnowledgeBackupError("Knowledge backup blob references are unreadable.") from exc
        return [(str(row[0]), str(row[1]), int(row[2])) for row in rows]

    @staticmethod
    def _validate_blob_reference(content_hash: str, blob_path: str) -> None:
        expected = f"sha256/{content_hash[:2]}/{content_hash}.txt.gz"
        if len(content_hash) != 64 or blob_path != expected:
            raise KnowledgeBackupError("Knowledge backup contains an invalid blob reference.")

    @staticmethod
    def _verify_blob_stream(compressed: Any, content_hash: str, byte_size: int) -> None:
        digest = hashlib.sha256()
        size = 0
        with gzip.GzipFile(fileobj=compressed, mode="rb") as raw:
            for chunk in iter(lambda: raw.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        if digest.hexdigest() != content_hash or size != byte_size:
            raise KnowledgeBackupError("Knowledge backup blob content does not match its database record.")

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
