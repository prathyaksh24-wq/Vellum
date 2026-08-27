from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from threading import Event, Thread
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.knowledge.book_ingestion import (
    BookIngestionPolicy,
    EpubValidationError,
    MalwareScanResult,
    WindowsDefenderScanner,
    _validate_entry,
    validate_epub_archive,
)
from agent.knowledge.api import router as knowledge_router
from agent.knowledge.models import BookImportRequest, ContextPackRequest
from agent.knowledge.runtime import set_knowledge_core
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore


class CleanScanner:
    def scan(self, path: Path) -> MalwareScanResult:
        assert path.exists()
        return MalwareScanResult(
            outcome="clean",
            scanner="test-scanner",
            scanner_version="1",
            reason_code="CLEAN",
        )


class OutcomeScanner:
    def __init__(self, outcome: str, reason_code: str) -> None:
        self.outcome = outcome
        self.reason_code = reason_code

    def scan(self, path: Path) -> MalwareScanResult:
        assert path.exists()
        return MalwareScanResult(
            outcome=self.outcome,
            scanner="test-scanner",
            scanner_version="1",
            reason_code=self.reason_code,
        )


class ThrowingScanner:
    def scan(self, path: Path) -> MalwareScanResult:
        _ = path
        raise OSError("scanner process failed with a private path")


class BlockingScanner:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def scan(self, path: Path) -> MalwareScanResult:
        assert path.exists()
        self.entered.set()
        assert self.release.wait(timeout=5)
        return MalwareScanResult(
            outcome="clean",
            scanner="test-scanner",
            scanner_version="1",
            reason_code="CLEAN",
        )


def build_core(tmp_path: Path, *, scanner=None) -> KnowledgeCore:
    vault = tmp_path / "Vault"
    vault.mkdir()
    conversations = tmp_path / "data" / "ui" / "conversations.json"
    conversations.parent.mkdir(parents=True)
    conversations.write_text('{"conversations": []}\n', encoding="utf-8")
    return KnowledgeCore(
        KnowledgeStore(
            tmp_path / "data" / "knowledge" / "core.db",
            tmp_path / "data" / "knowledge" / "blobs",
        ),
        conversations_path=conversations,
        vault_root=vault,
        book_malware_scanner=scanner or CleanScanner(),
    )


def valid_epub_bytes() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:test:book</dc:identifier>
    <dc:title>Fixture Book</dc:title>
  </metadata>
  <manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="chapter"/></spine>
</package>""",
        )
        archive.writestr("OEBPS/chapter.xhtml", "<html><body><p>Private fixture text.</p></body></html>")
    return output.getvalue()


def epub_with_extra_entry(entry_name: str, content: bytes = b"not allowed") -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(entry_name, content)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"/>')
    return output.getvalue()


def epub_with_symlink() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        link = zipfile.ZipInfo("OEBPS/link.xhtml")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "chapter.xhtml")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"/>')
    return output.getvalue()


def test_same_user_epub_import_is_idempotent_and_path_free(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    request = BookImportRequest(
        user_id="user-1",
        rights_attestation_version="local-epub-v1",
        scan_approved=True,
    )
    content = valid_epub_bytes()

    first = core.import_book_epub(request, content)
    duplicate = core.import_book_epub(request, content)

    assert first.status == "validated"
    assert request.scan_approved is True
    assert duplicate.model_dump() == first.model_dump()
    assert [receipt.stage for receipt in first.receipts] == ["received", "quarantined", "validated"]
    assert len({receipt.id for receipt in first.receipts}) == 3
    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "Private fixture text" not in serialized
    assert str(tmp_path) not in serialized
    status = core.store.status()
    assert status["counts"]["book_assets"] == 1
    assert status["counts"]["user_book_imports"] == 1
    assert status["counts"]["book_ingestion_runs"] == 1
    assert status["counts"]["book_stage_receipts"] == 3
    pack = core.create_context_pack(
        ContextPackRequest(
            query="Fixture Book", purpose="specialist", destination="external",
            token_budget=512, source_kinds=["book", "book_document", "book_page", "book_skill"],
        )
    )
    assert pack["evidence"] == []


def test_local_only_book_import_cannot_be_cleared_by_an_idempotent_reimport(
    tmp_path: Path,
) -> None:
    core = build_core(tmp_path)
    protected = BookImportRequest(
        user_id="user-1",
        rights_attestation_version="local-epub-v1",
        scan_approved=True,
        local_only=True,
    )
    content = valid_epub_bytes()

    first = core.import_book_epub(protected, content)
    duplicate = core.import_book_epub(
        protected.model_copy(update={"local_only": False}),
        content,
    )

    assert first.local_only is True
    assert duplicate.local_only is True


def test_pipeline_versions_return_their_exact_run(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    content = valid_epub_bytes()
    version_one = BookImportRequest(
        user_id="user-1",
        rights_attestation_version="local-epub-v1",
        scan_approved=True,
        pipeline_version="book-epub-intake-v1",
    )
    version_two = version_one.model_copy(update={"pipeline_version": "book-epub-intake-v2"})

    first = core.import_book_epub(version_one, content)
    second = core.import_book_epub(version_two, content)
    first_again = core.import_book_epub(version_one, content)

    assert first.run_id != second.run_id
    assert first_again.run_id == first.run_id
    assert first_again.receipts == first.receipts
    assert core.get_book_ingestion_status(
        user_id="user-1",
        import_id=first.import_id,
        run_id=first.run_id,
    ).run_id == first.run_id
    status = core.store.status()
    assert status["counts"]["book_assets"] == 1
    assert status["counts"]["user_book_imports"] == 1
    assert status["counts"]["book_ingestion_runs"] == 2
    assert status["counts"]["book_stage_receipts"] == 6


def test_duplicate_during_active_scan_returns_durable_in_progress_status(tmp_path: Path) -> None:
    scanner = BlockingScanner()
    core = build_core(tmp_path, scanner=scanner)
    request = BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True)
    content = valid_epub_bytes()
    completed = []

    worker = Thread(target=lambda: completed.append(core.import_book_epub(request, content)))
    worker.start()
    assert scanner.entered.wait(timeout=5)
    duplicate = core.import_book_epub(request, content)
    scanner.release.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert duplicate.status == "quarantined"
    assert completed[0].status == "validated"
    status = core.store.status()
    assert status["counts"]["book_assets"] == 1
    assert status["counts"]["book_ingestion_runs"] == 1
    assert status["counts"]["book_stage_receipts"] == 3


def test_received_status_exists_before_coordinator_can_deduplicate(tmp_path: Path, monkeypatch) -> None:
    core = build_core(tmp_path)
    request = BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True)
    content = valid_epub_bytes()

    def deduplicate_without_running(_request, *, operation):
        _ = operation
        assert core.store.status()["counts"]["book_ingestion_runs"] == 1
        return {"status": "running", "should_run": False, "deduplicated": True}

    monkeypatch.setattr(core.book_ingestion.coordinator, "run", deduplicate_without_running)
    result = core.import_book_epub(request, content)

    assert result.status == "received"
    assert [receipt.stage for receipt in result.receipts] == ["received"]


def test_malware_detection_rejects_before_archive_validation(tmp_path: Path) -> None:
    core = build_core(
        tmp_path,
        scanner=OutcomeScanner("detected", "TEST_SIGNATURE"),
    )

    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        b"this is not an epub and must never reach archive validation",
    )

    assert result.status == "rejected"
    assert result.current_stage == "quarantined"
    assert result.error_code == "MALWARE_DETECTED"
    assert result.receipts[-1].stage == "quarantined"
    assert result.receipts[-1].reason_code == "MALWARE_DETECTED"
    serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    assert "TEST_SIGNATURE" not in serialized
    assert str(tmp_path) not in serialized


def test_unavailable_scanner_fails_closed_and_is_retryable(tmp_path: Path) -> None:
    core = build_core(
        tmp_path,
        scanner=OutcomeScanner("unavailable", "MALWARE_SCANNER_UNAVAILABLE"),
    )
    request = BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True)
    content = valid_epub_bytes()

    first = core.import_book_epub(request, content)
    retried = core.import_book_epub(request, content)

    assert first.status == "failed_retryable"
    assert retried.status == "failed_retryable"
    assert retried.current_stage == "quarantined"
    assert retried.error_code == "MALWARE_SCANNER_UNAVAILABLE"
    assert [receipt.attempt for receipt in retried.receipts] == [1, 1, 1, 2, 2, 2]


def test_scanner_exception_is_sanitized_as_retryable(tmp_path: Path) -> None:
    core = build_core(tmp_path, scanner=ThrowingScanner())

    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        valid_epub_bytes(),
    )

    assert result.status == "failed_retryable"
    assert result.current_stage == "quarantined"
    assert result.error_code == "MALWARE_SCAN_FAILED"
    assert "private path" not in result.model_dump_json()


def test_quarantine_write_failure_is_sanitized_as_retryable(tmp_path: Path, monkeypatch) -> None:
    core = build_core(tmp_path)

    def fail_write(*_args, **_kwargs):
        raise OSError("disk failure at C:\\private\\book.epub")

    monkeypatch.setattr(core.store.blobs, "put_book_asset", fail_write)
    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        valid_epub_bytes(),
    )

    assert result.status == "failed_retryable"
    assert result.current_stage == "received"
    assert result.error_code == "QUARANTINE_WRITE_FAILED"
    assert "private" not in result.model_dump_json()


def test_scanner_reason_code_is_allowlisted(tmp_path: Path) -> None:
    core = build_core(
        tmp_path,
        scanner=OutcomeScanner("error", "C:\\private\\scanner-output.txt"),
    )

    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        valid_epub_bytes(),
    )

    assert result.status == "failed_retryable"
    assert result.error_code == "MALWARE_SCAN_FAILED"
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("entry_name", "content", "reason_code"),
    [
        ("../escape.xhtml", b"text", "UNSAFE_ARCHIVE_PATH"),
        ("OEBPS/CON.xhtml", b"text", "UNSAFE_ARCHIVE_PATH"),
        ("OEBPS/payload.tar", b"text", "UNSAFE_ARCHIVE_PAYLOAD"),
        ("OEBPS/installer.msi", b"text", "UNSAFE_ARCHIVE_PAYLOAD"),
        ("OEBPS/image.bin", b"PK\x03\x04nested", "UNSAFE_ARCHIVE_PAYLOAD"),
        ("OEBPS/image.bin", b"harmless-stub-PK\x03\x04nested", "UNSAFE_ARCHIVE_PAYLOAD"),
        ("OEBPS/image.bin", b"MZexecutable", "UNSAFE_ARCHIVE_PAYLOAD"),
    ],
)
def test_unsafe_archive_entry_is_rejected_without_extraction(
    tmp_path: Path,
    entry_name: str,
    content: bytes,
    reason_code: str,
) -> None:
    core = build_core(tmp_path)

    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        epub_with_extra_entry(entry_name, content),
    )

    assert result.status == "rejected"
    assert result.error_code == reason_code
    assert not (tmp_path / "escape.xhtml").exists()


def test_symlink_and_entry_limit_are_rejected_before_extraction() -> None:
    with pytest.raises(EpubValidationError, match="ARCHIVE_SYMLINK"):
        validate_epub_archive(epub_with_symlink(), BookIngestionPolicy())
    over_limit = BytesIO(epub_with_extra_entry("OEBPS/extra-one.xhtml"))
    with zipfile.ZipFile(over_limit, "a") as archive:
        archive.writestr("OEBPS/extra-two.xhtml", "extra")
    with pytest.raises(EpubValidationError, match="ARCHIVE_ENTRY_LIMIT"):
        validate_epub_archive(
            over_limit.getvalue(),
            BookIngestionPolicy(max_entries=4),
        )


def test_encrypted_duplicate_and_compression_ratio_entries_are_rejected() -> None:
    encrypted = zipfile.ZipInfo("OEBPS/encrypted.xhtml")
    encrypted.flag_bits = 0x1
    with pytest.raises(EpubValidationError, match="ENCRYPTED_ARCHIVE_ENTRY"):
        _validate_entry(encrypted, BookIngestionPolicy())

    duplicate = BytesIO(valid_epub_bytes())
    with pytest.warns(UserWarning), zipfile.ZipFile(duplicate, "a") as archive:
        archive.writestr("OEBPS/chapter.xhtml", "duplicate")
    with pytest.raises(EpubValidationError, match="DUPLICATE_ARCHIVE_ENTRY"):
        validate_epub_archive(duplicate.getvalue(), BookIngestionPolicy())

    compressed = BytesIO(valid_epub_bytes())
    with zipfile.ZipFile(compressed, "a") as archive:
        archive.writestr(
            "OEBPS/compressed.bin",
            b"A" * 10_000,
            compress_type=zipfile.ZIP_DEFLATED,
        )
    with pytest.raises(EpubValidationError, match="ARCHIVE_COMPRESSION_RATIO_LIMIT"):
        validate_epub_archive(
            compressed.getvalue(),
            BookIngestionPolicy(max_compression_ratio=2.0),
        )


def test_asset_and_expanded_size_limits_are_durable(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    core.book_ingestion.policy = BookIngestionPolicy(max_asset_bytes=1024)
    result = core.import_book_epub(
        BookImportRequest(
            user_id="user-1",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        b"x" * 1025,
    )
    assert result.status == "failed_permanent"
    assert result.current_stage == "received"
    assert result.error_code == "ASSET_TOO_LARGE"

    expanded = BytesIO(valid_epub_bytes())
    with zipfile.ZipFile(expanded, "a") as archive:
        archive.writestr("OEBPS/large.bin", b"x" * 2048)
    with pytest.raises(EpubValidationError, match="ARCHIVE_EXPANDED_SIZE_LIMIT"):
        validate_epub_archive(
            expanded.getvalue(),
            BookIngestionPolicy(max_expanded_bytes=1024),
        )


def test_validation_receipt_metadata_is_bounded_and_contains_no_raw_output(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        valid_epub_bytes(),
    )

    with core.store._connect() as connection:
        row = connection.execute(
            "SELECT metadata_json FROM book_stage_receipts WHERE run_id = ? AND stage = 'validated'",
            (result.run_id,),
        ).fetchone()
    metadata = json.loads(row[0])
    assert metadata["scan_outcome"] == "clean"
    assert metadata["limits"]["max_entries"] == 5000
    serialized = json.dumps(metadata, sort_keys=True)
    assert "Private fixture text" not in serialized
    assert str(tmp_path) not in serialized


def test_same_epub_is_isolated_between_users(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    content = valid_epub_bytes()

    first = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        content,
    )
    second = core.import_book_epub(
        BookImportRequest(user_id="user-2", rights_attestation_version="local-epub-v1", scan_approved=True),
        content,
    )

    assert first.asset_sha256 == second.asset_sha256
    assert first.asset_id != second.asset_id
    assert first.import_id != second.import_id
    with core.store._connect() as connection:
        paths = [row[0] for row in connection.execute("SELECT blob_path FROM book_assets ORDER BY user_id")]
    assert paths[0] != paths[1]
    assert all(path.startswith("books/quarantine/usr_") for path in paths)


def test_book_status_is_tenant_scoped(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    result = core.import_book_epub(
        BookImportRequest(user_id="user-1", rights_attestation_version="local-epub-v1", scan_approved=True),
        valid_epub_bytes(),
    )

    try:
        core.get_book_ingestion_status(user_id="user-2", import_id=result.import_id)
    except KeyError:
        pass
    else:
        raise AssertionError("another user must not resolve the import status")


def test_http_import_and_status_preserve_sanitized_contract(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    app = FastAPI()
    app.include_router(knowledge_router, prefix="/api/knowledge")
    set_knowledge_core(core)
    try:
        with TestClient(app) as client:
            imported = client.post(
                "/api/knowledge/core/books/epub",
                data={
                    "user_id": "user-1",
                    "rights_attestation_version": "local-epub-v1",
                    "scan_approved": "true",
                },
                files={
                    "file": (
                        "misleading-name.bin",
                        valid_epub_bytes(),
                        "application/octet-stream",
                    )
                },
            )
            assert imported.status_code == 200
            result = imported.json()
            assert result["status"] == "validated"

            status = client.get(
                f"/api/knowledge/core/books/imports/{result['import_id']}",
                params={"user_id": "user-1", "run_id": result["run_id"]},
            )
            hidden = client.get(
                f"/api/knowledge/core/books/imports/{result['import_id']}",
                params={"user_id": "user-2"},
            )
    finally:
        set_knowledge_core(None)

    assert status.status_code == 200
    assert status.json() == result
    assert hidden.status_code == 404
    serialized = json.dumps(result, sort_keys=True)
    assert "misleading-name.bin" not in serialized
    assert "Private fixture text" not in serialized
    assert str(tmp_path) not in serialized


def test_http_import_rejects_empty_upload_without_creating_a_record(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    app = FastAPI()
    app.include_router(knowledge_router, prefix="/api/knowledge")
    set_knowledge_core(core)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/knowledge/core/books/epub",
                data={
                    "user_id": "user-1",
                    "rights_attestation_version": "local-epub-v1",
                    "scan_approved": "true",
                },
                files={"file": ("empty.epub", b"", "application/epub+zip")},
            )
    finally:
        set_knowledge_core(None)

    assert response.status_code == 422
    assert core.store.status()["counts"]["book_assets"] == 0


def test_http_import_requires_explicit_scan_approval(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    app = FastAPI()
    app.include_router(knowledge_router, prefix="/api/knowledge")
    set_knowledge_core(core)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/knowledge/core/books/epub",
                data={"user_id": "user-1", "rights_attestation_version": "local-epub-v1"},
                files={"file": ("book.epub", valid_epub_bytes(), "application/epub+zip")},
            )
    finally:
        set_knowledge_core(None)

    assert response.status_code == 422
    assert core.store.status()["counts"]["book_assets"] == 0


def test_core_import_cannot_bypass_scan_approval(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    approved = BookImportRequest(
        user_id="user-1",
        rights_attestation_version="local-epub-v1",
        scan_approved=True,
    )

    with pytest.raises(ValueError, match="scan approval"):
        core.import_book_epub(
            approved.model_copy(update={"scan_approved": False}),
            valid_epub_bytes(),
        )

    assert core.store.status()["counts"]["book_assets"] == 0


def test_http_import_rejects_oversize_before_storage(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    core.book_ingestion.policy = BookIngestionPolicy(max_asset_bytes=1024)
    app = FastAPI()
    app.include_router(knowledge_router, prefix="/api/knowledge")
    set_knowledge_core(core)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/knowledge/core/books/epub",
                data={
                    "user_id": "user-1",
                    "rights_attestation_version": "local-epub-v1",
                    "scan_approved": "true",
                },
                files={"file": ("book.epub", b"x" * 1025, "application/epub+zip")},
            )
    finally:
        set_knowledge_core(None)

    assert response.status_code == 413
    assert core.store.status()["counts"]["book_assets"] == 0


class DefenderResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_windows_defender_adapter_uses_custom_scan_without_remediation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "Platform" / "4.0.0" / "MpCmdRun.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    asset = Path("quarantine") / "private.epub"
    asset.parent.mkdir()
    asset.write_bytes(valid_epub_bytes())
    observed = {}

    def runner(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return DefenderResult(0, stdout="Scan finished.")

    result = WindowsDefenderScanner(executable=executable, runner=runner).scan(asset)

    assert result.outcome == "clean"
    assert result.reason_code == "CLEAN"
    assert observed["command"] == [
        str(executable),
        "-Scan",
        "-ScanType",
        "3",
        "-File",
        str(asset.resolve()),
        "-DisableRemediation",
    ]
    assert observed["kwargs"]["timeout"] > 0


def test_windows_defender_adapter_only_marks_explicit_detection(tmp_path: Path) -> None:
    executable = tmp_path / "MpCmdRun.exe"
    executable.write_bytes(b"")
    asset = tmp_path / "private.epub"
    asset.write_bytes(valid_epub_bytes())

    detected = WindowsDefenderScanner(
        executable=executable,
        runner=lambda *_args, **_kwargs: DefenderResult(2, stdout="Threat was found."),
    ).scan(asset)
    ambiguous = WindowsDefenderScanner(
        executable=executable,
        runner=lambda *_args, **_kwargs: DefenderResult(2, stderr=f"scan failed for {asset}"),
    ).scan(asset)

    assert detected.outcome == "detected"
    assert detected.reason_code == "MALWARE_DETECTED"
    assert ambiguous.outcome == "error"
    assert ambiguous.reason_code == "MALWARE_SCAN_AMBIGUOUS"
    assert str(asset) not in ambiguous.model_dump_json()


def test_windows_defender_adapter_reports_missing_scanner_as_unavailable(tmp_path: Path) -> None:
    result = WindowsDefenderScanner(executable=tmp_path / "missing.exe").scan(tmp_path / "book.epub")

    assert result.outcome == "unavailable"
    assert result.reason_code == "MALWARE_SCANNER_UNAVAILABLE"
