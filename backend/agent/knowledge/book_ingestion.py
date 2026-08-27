"""Fail-closed, idempotent EPUB intake owned by Knowledge Core."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Literal, Protocol
import unicodedata
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from agent.knowledge.ingestion import IngestionCoordinator, IngestionResult
from agent.knowledge.models import BookImportRequest, BookImportStatus, IngestionJobInput
from agent.knowledge.store import KnowledgeStore


class MalwareScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["clean", "detected", "unavailable", "error"]
    scanner: str = Field(min_length=1, max_length=120)
    scanner_version: str = Field(default="", max_length=120)
    reason_code: str = Field(min_length=1, max_length=80)


class MalwareScanner(Protocol):
    def scan(self, path: Path) -> MalwareScanResult: ...


class UnavailableMalwareScanner:
    def scan(self, path: Path) -> MalwareScanResult:
        _ = path
        return MalwareScanResult(
            outcome="unavailable",
            scanner="unconfigured",
            reason_code="MALWARE_SCANNER_UNAVAILABLE",
        )


class WindowsDefenderScanner:
    """Fail-closed adapter for Microsoft Defender's local command-line scanner."""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        runner: Any = subprocess.run,
        timeout_seconds: int = 180,
    ) -> None:
        self._explicit_executable = Path(executable) if executable is not None else None
        self._runner = runner
        self.timeout_seconds = max(1, int(timeout_seconds))

    def scan(self, path: Path) -> MalwareScanResult:
        executable = self._explicit_executable or _find_windows_defender()
        if executable is None or not executable.is_file():
            return MalwareScanResult(
                outcome="unavailable",
                scanner="windows-defender",
                reason_code="MALWARE_SCANNER_UNAVAILABLE",
            )
        target = path.resolve()
        if not target.is_file():
            return MalwareScanResult(
                outcome="error",
                scanner="windows-defender",
                scanner_version=_defender_version(executable),
                reason_code="MALWARE_SCAN_INPUT_MISSING",
            )
        command = [
            str(executable),
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(target),
            "-DisableRemediation",
        ]
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": self.timeout_seconds,
            "check": False,
        }
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            completed = self._runner(command, **kwargs)
        except (OSError, subprocess.SubprocessError):
            return MalwareScanResult(
                outcome="error",
                scanner="windows-defender",
                scanner_version=_defender_version(executable),
                reason_code="MALWARE_SCAN_FAILED",
            )
        return_code = int(getattr(completed, "returncode", -1))
        output = f"{getattr(completed, 'stdout', '')}\n{getattr(completed, 'stderr', '')}".casefold()
        details = {
            "scanner": "windows-defender",
            "scanner_version": _defender_version(executable),
        }
        if return_code == 0:
            return MalwareScanResult(outcome="clean", reason_code="CLEAN", **details)
        detection_markers = ("threat was found", "threats were found", "malware detected")
        if return_code == 2 and any(marker in output for marker in detection_markers):
            return MalwareScanResult(outcome="detected", reason_code="MALWARE_DETECTED", **details)
        reason_code = "MALWARE_SCAN_AMBIGUOUS" if return_code == 2 else "MALWARE_SCAN_FAILED"
        return MalwareScanResult(outcome="error", reason_code=reason_code, **details)


def _find_windows_defender() -> Path | None:
    candidates: list[Path] = []
    program_data = os.environ.get("PROGRAMDATA", "").strip()
    if program_data:
        platform_root = Path(program_data) / "Microsoft" / "Windows Defender" / "Platform"
        if platform_root.is_dir():
            candidates.extend(sorted(platform_root.glob("*/MpCmdRun.exe"), reverse=True))
    program_files = os.environ.get("PROGRAMFILES", "").strip()
    if program_files:
        candidates.append(Path(program_files) / "Windows Defender" / "MpCmdRun.exe")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _defender_version(executable: Path) -> str:
    parent = executable.parent.name.strip()
    return parent if parent.casefold() != "windows defender" else ""


class BookIngestionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "book-epub-security-v1"
    max_asset_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    max_entries: int = Field(default=5000, ge=4)
    max_expanded_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    max_compression_ratio: float = Field(default=1000.0, ge=1.0)

    def digest(self) -> str:
        encoded = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class EpubValidationError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class RetryableBookIngestionError(RuntimeError):
    pass


class BookIngestionPipeline:
    def __init__(
        self,
        store: KnowledgeStore,
        *,
        scanner: MalwareScanner | None = None,
        policy: BookIngestionPolicy | None = None,
    ) -> None:
        self.store = store
        self.scanner = scanner or UnavailableMalwareScanner()
        self.policy = policy or BookIngestionPolicy()
        self.coordinator = IngestionCoordinator(store)

    def import_epub(self, request: BookImportRequest, content: bytes) -> BookImportStatus:
        if request.scan_approved is not True:
            raise ValueError("Local malware scan approval is required.")
        raw = bytes(content)
        asset_sha256 = hashlib.sha256(raw).hexdigest()
        policy_hash = self.policy.digest()
        job_request = IngestionJobInput(
            connector="books",
            account_id=request.user_id,
            job_type="epub_intake",
            idempotency_key=f"{asset_sha256}:{request.pipeline_version}:{policy_hash}",
            requested_by=request.requested_by,
        )
        identity = self.store.book_import_ids(
            user_id=request.user_id,
            asset_sha256=asset_sha256,
            pipeline_version=request.pipeline_version,
            policy_snapshot_hash=policy_hash,
        )
        initial_status = BookImportStatus.model_validate(
            self.store.begin_book_import(
                user_id=request.user_id,
                asset_sha256=asset_sha256,
                byte_size=len(raw),
                rights_attestation_version=request.rights_attestation_version,
                local_only=request.local_only,
                pipeline_version=request.pipeline_version,
                policy_snapshot_hash=policy_hash,
            )
        )
        if initial_status.status in {"validated", "rejected", "failed_permanent"}:
            return initial_status

        def operation(_cursor):
            status = self._process(
                request=request,
                current=initial_status,
                raw=raw,
                asset_sha256=asset_sha256,
            )
            if status.status == "failed_retryable":
                raise RetryableBookIngestionError(status.error_code)
            return IngestionResult(stats={"book_status": status.status})

        try:
            self.coordinator.run(job_request, operation=operation)
        except RetryableBookIngestionError:
            pass
        return BookImportStatus.model_validate(
            self.store.get_book_import_status(
                user_id=request.user_id,
                import_id=identity["import_id"],
                run_id=identity["run_id"],
            )
        )

    def _process(
        self,
        *,
        request: BookImportRequest,
        current: BookImportStatus,
        raw: bytes,
        asset_sha256: str,
    ) -> BookImportStatus:
        status = current
        if len(raw) > self.policy.max_asset_bytes:
            return self._fail(
                request.user_id,
                status,
                "failed_permanent",
                "ASSET_TOO_LARGE",
                stage="received",
                stage_version="intake-limits-v1",
                metadata=self._policy_metadata(),
            )

        tenant_scope = self.store.book_tenant_scope(request.user_id)
        try:
            digest, blob_path, _size = self.store.blobs.put_book_asset(
                raw,
                tenant_scope=tenant_scope,
            )
        except OSError:
            return self._fail(
                request.user_id,
                status,
                "failed_retryable",
                "QUARANTINE_WRITE_FAILED",
                stage="received",
                stage_version="quarantine-v1",
                metadata=self._policy_metadata(),
            )
        status = BookImportStatus.model_validate(
            self.store.publish_book_stage(
                user_id=request.user_id,
                import_id=status.import_id,
                run_id=status.run_id,
                stage="quarantined",
                stage_version="quarantine-v1",
                input_digest=asset_sha256,
                output_digest=digest,
                status="succeeded",
                reason_code="QUARANTINED",
                metadata=self._policy_metadata(),
                blob_path=blob_path,
            )
        )
        try:
            scan = MalwareScanResult.model_validate(
                self.scanner.scan(self.store.blobs.resolve(blob_path))
            )
        except Exception:
            return self._fail(
                request.user_id,
                status,
                "failed_retryable",
                "MALWARE_SCAN_FAILED",
                stage="quarantined",
                stage_version="malware-scan-v1",
            )
        scan_metadata = {
            **self._policy_metadata(),
            "scanner": _safe_scanner_label(scan.scanner, default="unknown"),
            "scanner_version": _safe_scanner_label(scan.scanner_version, default=""),
            "scan_outcome": scan.outcome,
        }
        if scan.outcome == "detected":
            return self._fail(
                request.user_id,
                status,
                "rejected",
                "MALWARE_DETECTED",
                stage="quarantined",
                stage_version="malware-scan-v1",
                metadata=scan_metadata,
            )
        if scan.outcome in {"unavailable", "error"}:
            return self._fail(
                request.user_id,
                status,
                "failed_retryable",
                _scanner_failure_code(scan),
                stage="quarantined",
                stage_version="malware-scan-v1",
                metadata=scan_metadata,
            )
        try:
            validate_epub_archive(raw, self.policy)
        except EpubValidationError as exc:
            return self._fail(request.user_id, status, "rejected", exc.reason_code, metadata=scan_metadata)
        return BookImportStatus.model_validate(
            self.store.publish_book_stage(
                user_id=request.user_id,
                import_id=status.import_id,
                run_id=status.run_id,
                stage="validated",
                stage_version="epub-validation-v1",
                input_digest=asset_sha256,
                output_digest=asset_sha256,
                status="succeeded",
                reason_code="VALIDATED",
                metadata=scan_metadata,
                media_type="application/epub+zip",
            )
        )

    def _fail(
        self,
        user_id: str,
        current: BookImportStatus,
        status: Literal["rejected", "failed_retryable", "failed_permanent"],
        reason_code: str,
        *,
        stage: Literal["received", "quarantined", "validated"] = "validated",
        stage_version: str = "epub-validation-v1",
        metadata: dict | None = None,
    ) -> BookImportStatus:
        return BookImportStatus.model_validate(
            self.store.publish_book_stage(
                user_id=user_id,
                import_id=current.import_id,
                run_id=current.run_id,
                stage=stage,
                stage_version=stage_version,
                input_digest=current.asset_sha256,
                output_digest="",
                status=status,
                reason_code=reason_code,
                metadata=metadata or self._policy_metadata(),
            )
        )

    def _policy_metadata(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy.version,
            "limits": {
                "max_asset_bytes": self.policy.max_asset_bytes,
                "max_entries": self.policy.max_entries,
                "max_expanded_bytes": self.policy.max_expanded_bytes,
                "max_compression_ratio": self.policy.max_compression_ratio,
            },
        }


def validate_epub_archive(raw: bytes, policy: BookIngestionPolicy) -> None:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > policy.max_entries:
                raise EpubValidationError("ARCHIVE_ENTRY_LIMIT")
            if not entries or entries[0].filename != "mimetype" or entries[0].compress_type != ZIP_STORED:
                raise EpubValidationError("INVALID_EPUB_MIMETYPE_ENTRY")
            if archive.read(entries[0]) != b"application/epub+zip":
                raise EpubValidationError("INVALID_EPUB_MIMETYPE")
            total = 0
            names: set[str] = set()
            canonical_names: set[str] = set()
            for entry in entries:
                _validate_entry(entry, policy)
                canonical_name = unicodedata.normalize("NFC", entry.filename).casefold()
                if canonical_name in canonical_names:
                    raise EpubValidationError("DUPLICATE_ARCHIVE_ENTRY")
                canonical_names.add(canonical_name)
                total += entry.file_size
                if total > policy.max_expanded_bytes:
                    raise EpubValidationError("ARCHIVE_EXPANDED_SIZE_LIMIT")
                names.add(entry.filename)
                if not entry.is_dir() and entry.filename != "mimetype":
                    with archive.open(entry) as handle:
                        _validate_payload_signature(handle.read(65536))
            if "META-INF/container.xml" not in names:
                raise EpubValidationError("EPUB_CONTAINER_MISSING")
            container = archive.read("META-INF/container.xml")
            _reject_active_xml(container)
            root = ET.fromstring(container)
            rootfile = root.find(".//{*}rootfile")
            opf_path = str(rootfile.get("full-path") if rootfile is not None else "")
            _validate_archive_name(opf_path)
            if not opf_path or opf_path not in names:
                raise EpubValidationError("EPUB_PACKAGE_MISSING")
            package = archive.read(opf_path)
            _reject_active_xml(package)
            ET.fromstring(package)
    except EpubValidationError:
        raise
    except (BadZipFile, ET.ParseError, KeyError, OSError, RuntimeError, ValueError) as exc:
        raise EpubValidationError("MALFORMED_EPUB") from exc


def _validate_entry(entry: ZipInfo, policy: BookIngestionPolicy) -> None:
    _validate_archive_name(entry.filename)
    if entry.flag_bits & 0x1:
        raise EpubValidationError("ENCRYPTED_ARCHIVE_ENTRY")
    if ((entry.external_attr >> 16) & 0o170000) == 0o120000:
        raise EpubValidationError("ARCHIVE_SYMLINK")
    suffix = PurePosixPath(entry.filename.casefold()).suffix
    if suffix in {
        ".zip",
        ".epub",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".tgz",
        ".cab",
        ".iso",
        ".exe",
        ".dll",
        ".com",
        ".bat",
        ".cmd",
        ".ps1",
        ".js",
        ".jar",
        ".msi",
        ".scr",
        ".vbs",
        ".hta",
        ".reg",
        ".lnk",
    }:
        raise EpubValidationError("UNSAFE_ARCHIVE_PAYLOAD")
    compressed = max(1, int(entry.compress_size))
    if entry.file_size / compressed > policy.max_compression_ratio:
        raise EpubValidationError("ARCHIVE_COMPRESSION_RATIO_LIMIT")


def _validate_archive_name(name: str) -> None:
    if (
        not name
        or "\\" in name
        or name.startswith(("/", "\\"))
        or ":" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise EpubValidationError("UNSAFE_ARCHIVE_PATH")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise EpubValidationError("UNSAFE_ARCHIVE_PATH")
    reserved = {"con", "prn", "aux", "nul", "clock$"}
    for part in path.parts:
        trimmed = part.rstrip(" .")
        stem = trimmed.split(".", 1)[0].casefold()
        if trimmed != part or stem in reserved:
            raise EpubValidationError("UNSAFE_ARCHIVE_PATH")
        if len(stem) == 4 and stem[:3] in {"com", "lpt"} and stem[3] in "123456789":
            raise EpubValidationError("UNSAFE_ARCHIVE_PATH")


def _validate_payload_signature(prefix: bytes) -> None:
    zip_signatures = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    if any(signature in prefix for signature in zip_signatures):
        raise EpubValidationError("UNSAFE_ARCHIVE_PAYLOAD")
    prefix_signatures = (
        b"Rar!\x1a\x07",
        b"7z\xbc\xaf\x27\x1c",
        b"\x1f\x8b",
        b"BZh",
        b"\xfd7zXZ\x00",
        b"MZ",
        b"\x7fELF",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        b"\xca\xfe\xba\xbe",
        b"\x00asm",
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"#!",
    )
    if any(prefix.startswith(signature) for signature in prefix_signatures):
        raise EpubValidationError("UNSAFE_ARCHIVE_PAYLOAD")
    if len(prefix) >= 262 and prefix[257:262] == b"ustar":
        raise EpubValidationError("UNSAFE_ARCHIVE_PAYLOAD")


def _safe_scanner_label(value: str, *, default: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return default
    if len(clean) > 120 or not all(character.isalnum() or character in "._ -" for character in clean):
        return default
    return clean


def _scanner_failure_code(scan: MalwareScanResult) -> str:
    if scan.outcome == "unavailable":
        return "MALWARE_SCANNER_UNAVAILABLE"
    allowed = {
        "MALWARE_SCAN_AMBIGUOUS",
        "MALWARE_SCAN_FAILED",
        "MALWARE_SCAN_INPUT_MISSING",
    }
    return scan.reason_code if scan.reason_code in allowed else "MALWARE_SCAN_FAILED"


def _reject_active_xml(raw: bytes) -> None:
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise EpubValidationError("UNSAFE_XML_DECLARATION")
