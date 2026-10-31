"""Metadata-only presentation of canonical Books, with no separate library store."""

from __future__ import annotations

from io import BytesIO
from hashlib import sha256
import json
from typing import TYPE_CHECKING, Any
from zipfile import BadZipFile

from PIL import Image, UnidentifiedImageError

from agent.knowledge.book_documents import BookDocumentError, read_epub_presentation, section_display_title, epub_content_fingerprint
from agent.knowledge.book_reader import reader_manifest, reader_section, reader_text
from agent.knowledge.book_cover import cover_style
from agent.knowledge.models import (
    BookDocumentRequest,
    BookImportRequest,
    BookMaterializationRequest,
    BookQualityRequest,
)

if TYPE_CHECKING:
    from agent.knowledge.service import KnowledgeCore

SCHEMA_VERSION = "books-library-v1"
RIGHTS_ATTESTATION_VERSION = "local-epub-v1"
DISPLAY_ERRORS = (OSError, ValueError, KeyError, BadZipFile, BookDocumentError)


class BookLibrary:
    def __init__(self, core: KnowledgeCore, user_id: str) -> None:
        self.core = core
        self.user_id = user_id

    def list(self, *, limit: int, offset: int) -> dict[str, Any]:
        ids, total = self.core.store.list_book_library_imports(user_id=self.user_id, limit=limit, offset=offset)
        return {"schema_version": SCHEMA_VERSION, "items": [self.book(item) for item in ids],
                "total": total, "limit": limit, "offset": offset,
                "rights_attestation_version": RIGHTS_ATTESTATION_VERSION}

    def import_epub(
        self,
        *,
        filename: str,
        content: bytes,
        rights_attestation_version: str,
        scan_approved: bool,
        local_only: bool,
        defer_processing: bool = False,
    ) -> dict[str, Any]:
        """Import through the canonical EPUB pipeline, then project the Books library view."""

        if not str(filename or "").strip().casefold().endswith(".epub"):
            raise ValueError("BOOK_EPUB_REQUIRED")
        if not content:
            raise ValueError("BOOK_EPUB_EMPTY")
        if len(content) > self.core.book_ingestion.policy.max_asset_bytes:
            raise ValueError("BOOK_EPUB_TOO_LARGE")

        fingerprint = ""
        try:
            fingerprint = epub_content_fingerprint(content)
            existing = self.find_duplicate(fingerprint)
            if existing:
                result = self.detail(existing) if defer_processing else self.materialize(existing)
                return {**result, "already_present": True, "status":"already_present"}
            removed = self.find_duplicate(fingerprint, include_removed=True)
            if removed:
                self.core.store.set_book_on_shelf(user_id=self.user_id, import_id=removed, on_shelf=True)
                result = self.detail(removed) if defer_processing else self.materialize(removed)
                return {**result, "status":"imported", "restored":True, "processing_pending":defer_processing}
        except DISPLAY_ERRORS:
            # Let canonical intake report unreadable archives through its normal contract.
            pass

        status = self.core.import_book_epub(
            BookImportRequest(
                user_id=self.user_id,
                pipeline_version=self._pipeline_version(),
                rights_attestation_version=RIGHTS_ATTESTATION_VERSION,
                scan_approved=True,
                requested_by="user",
                local_only=bool(local_only),
            ),
            bytes(content),
        )
        self.core.store.set_book_on_shelf(user_id=self.user_id, import_id=status.import_id, on_shelf=True)
        if status.error_code:
            return {
                **self.detail(status.import_id),
                "status": status.status,
                "error_code": status.error_code,
            }
        if fingerprint:
            owner = self.core.store.canonicalize_book_import(user_id=self.user_id, import_id=status.import_id, fingerprint=fingerprint)
            if owner != status.import_id:
                return {**self.detail(owner), "status":"already_present", "error_code":"", "already_present":True}
        if defer_processing:
            return {**self.detail(status.import_id), "status":"imported", "error_code":"", "processing_pending":True}
        return self.materialize(status.import_id)

    def find_duplicate(self, fingerprint: str, *, include_removed: bool = False) -> str:
        for candidate in self.core.store.book_identity_candidates(user_id=self.user_id, include_removed=include_removed):
            current = candidate["content_fingerprint"]
            if not current:
                try:
                    current = epub_content_fingerprint(self.core.store.blobs.resolve(candidate["blob_path"]).read_bytes())
                    self.core.store.set_book_content_fingerprint(user_id=self.user_id, import_id=candidate["id"], fingerprint=current)
                except DISPLAY_ERRORS:
                    continue
            if current == fingerprint:
                # An incomplete/rejected attempt does not count as a readable shelf book.
                status = self.core.get_book_ingestion_status(user_id=self.user_id, import_id=candidate["id"])
                asset = self.core.store.get_book_library_asset(user_id=self.user_id, import_id=candidate["id"], run_id=status.run_id)
                if asset["validated"] and status.status != "rejected":
                    return candidate["id"]
        return ""

    def _pipeline_version(self) -> str:
        return "book-epub-intake-" + self.core.book_documents.parser_version

    def _source(self, import_id: str):
        status = self.core.get_book_ingestion_status(user_id=self.user_id, import_id=import_id)
        asset = self.core.store.get_book_library_asset(
            user_id=self.user_id, import_id=import_id, run_id=status.run_id,
        )
        if asset.get("removed_at"):
            raise KeyError("Book is not on the shelf.")
        return status, asset

    def remove(self, import_id: str) -> dict[str, Any]:
        changed = self.core.store.set_book_on_shelf(user_id=self.user_id, import_id=import_id, on_shelf=False)
        return {"schema_version":SCHEMA_VERSION, "removed_import_id":import_id, "removed":True, "changed":changed}

    def book(self, import_id: str, *, detail: bool = False) -> dict[str, Any]:
        status, asset = self._source(import_id)
        usable = bool(asset["validated"]) and status.status not in {"rejected", "failed_permanent"}
        readable = bool(asset["validated"]) and status.status != "rejected"
        validation_metadata = json.loads(asset.get("validation_metadata") or "{}")
        presentation = json.loads(asset.get("presentation_json") or "{}")
        expected_compiler = str(self.core.book_materializations.compiler_version)
        compiled_current = bool(asset["compiled"]) and str(asset["active_compiler_version"]) == expected_compiler
        quality_current = False
        quality_findings: list[str] = []
        if status.document_id and status.quality_evaluated:
            try:
                assessment = self.core.get_book_quality_assessment(user_id=self.user_id, document_id=status.document_id)
                quality_current = True
                quality_findings = assessment.finding_codes
            except DISPLAY_ERRORS:
                # A new quality policy must reassess the retained document,
                # rather than reusing an obsolete blocked verdict forever.
                pass
        book = {
            "id": import_id, "title": "Untitled book", "authors": [], "published_at": "",
            "document_id": status.document_id, "run_id": status.run_id, "state": status.status,
            "quality_outcome": status.quality_outcome,
            "can_read": readable,
            "scan_status": validation_metadata.get("scan_outcome", "unknown"),
            "reader_progress": asset.get("reader_progress", 0), "date_added": asset.get("date_added", ""),
            "cover_aspect": None, "cover_palette": None, "content_chars": 0,
            "quality_findings": quality_findings,
            "error_code": status.error_code, "local_only": status.local_only, "cover_url": "",
            "can_process": readable and (not quality_current or
                (status.document_id and self.core.book_documents.ocr_provider is not None and
                 self.core.get_book_document(user_id=self.user_id, document_id=status.document_id).parser_version != self.core.book_documents.parser_version)),
            "can_compile": usable and quality_current and status.quality_outcome == "PASS" and not compiled_current
            and callable(self.core.materialize_book_document),
            "skill_status": "compiled" if compiled_current else "not_compiled",
        }
        if readable:
            try:
                metadata, cover_data, cover_type = read_epub_presentation(self.core.store.blobs.resolve(asset["blob_path"]), include_cover=True)
                book.update(title=metadata.title[:1000] or "Untitled book", authors=[a[:300] for a in metadata.creators[:20]],
                            published_at=metadata.published_at[:100])
                if cover_type:
                    book["cover_url"] = f"/api/knowledge/core/books/library/{import_id}/cover"
                    book["cover_aspect"], book["cover_palette"] = cover_style(cover_data)
            except DISPLAY_ERRORS:
                book["display_error"] = "BOOK_METADATA_UNAVAILABLE"
            if presentation.get("title"):
                book["title"] = presentation["title"]
            if presentation.get("cover_blob_path"):
                try:
                    cover_data = self.core.store.blobs.read_book_artifact(presentation["cover_blob_path"])
                    book["cover_url"] = f"/api/knowledge/core/books/library/{import_id}/cover"
                    book["cover_aspect"], book["cover_palette"] = cover_style(cover_data)
                except DISPLAY_ERRORS:
                    book["display_error"] = "BOOK_COVER_UNAVAILABLE"
        if detail:
            book.update(sections=[], section_count=0)
            if status.document_id:
                try:
                    document = self.core.get_book_document(user_id=self.user_id, document_id=status.document_id)
                    book["section_count"] = len(document.sections)
                    book["content_chars"] = document.quality_report.text_characters
                    book["sections"] = [{"id": s.id, "title": section_display_title(document, s)[:1000], "block_count": len(s.blocks)}
                                        for s in document.sections[:500]]
                    book["sections_truncated"] = len(document.sections) > 500
                except DISPLAY_ERRORS:
                    book["display_error"] = "BOOK_SECTIONS_UNAVAILABLE"
        return book

    def detail(self, import_id: str) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "book": self.book(import_id, detail=True)}

    def materialize(self, import_id: str) -> dict[str, Any]:
        """Advance one validated EPUB through the canonical Book-to-Skill pipeline."""
        book = self.book(import_id)
        status = "ready"
        error = ""
        if book["can_process"]:
            processed = self.action(import_id, "process")
            status = str(processed.get("status") or status)
            error = str(processed.get("error_code") or "")
            book = processed["book"]
        if not error and book["can_compile"]:
            compiled = self.action(import_id, "compile")
            status = str(compiled.get("status") or status)
            error = str(compiled.get("error_code") or "")
            book = compiled["book"]
        if not error and book.get("skill_status") != "compiled":
            status = "blocked"
            error = {
                "OCR_REQUIRED": "BOOK_OCR_REQUIRED",
                "DEGRADED": "BOOK_QUALITY_DEGRADED",
                "FAILED_PERMANENT": "BOOK_QUALITY_FAILED",
                "FAILED_RETRYABLE": "BOOK_QUALITY_FAILED",
            }.get(book.get("quality_outcome"), "BOOK_COMPILE_NOT_ELIGIBLE")
        return {**self.detail(import_id), "status": status, "error_code": error}

    def cover(self, import_id: str) -> tuple[bytes, str]:
        status, asset = self._source(import_id)
        if not asset["validated"] or status.status == "rejected":
            raise ValueError("BOOK_COVER_UNAVAILABLE")
        try:
            presentation = json.loads(asset.get("presentation_json") or "{}")
            if presentation.get("cover_blob_path"):
                content = self.core.store.blobs.read_book_artifact(presentation["cover_blob_path"])
                media_type = presentation["cover_media_type"]
            else:
                _, content, media_type = read_epub_presentation(
                    self.core.store.blobs.resolve(asset["blob_path"]), include_cover=True,
                )
            with Image.open(BytesIO(content)) as image:
                expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}.get(media_type)
                if image.format != expected or image.width * image.height > 16_000_000:
                    raise ValueError("BOOK_COVER_UNAVAILABLE")
                image.verify()
            return content, media_type
        except (*DISPLAY_ERRORS, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ValueError("BOOK_COVER_UNAVAILABLE") from exc

    def _reader_path(self, import_id: str):
        status, asset = self._source(import_id)
        if not asset["validated"] or status.status == "rejected":
            raise ValueError("BOOK_READER_NOT_VALIDATED")
        path = self.core.store.blobs.resolve(asset["blob_path"])
        if sha256(path.read_bytes()).hexdigest() != status.asset_sha256:
            raise ValueError("BOOK_READER_ASSET_CHANGED")
        return path

    def reader(self, import_id: str):
        return reader_manifest(self._reader_path(import_id), import_id)

    def reader_section(self, import_id: str, section_id: str):
        return reader_section(self._reader_path(import_id), import_id, section_id)

    def reader_text(self, import_id: str):
        return reader_text(self._reader_path(import_id), import_id)

    def save_reader_progress(self, import_id: str, progress: float):
        self._reader_path(import_id)
        self.core.store.set_book_reader_progress(user_id=self.user_id, import_id=import_id, progress=progress)
        return {"schema_version": SCHEMA_VERSION, "book_id": import_id, "progress": progress}

    def action(self, import_id: str, action: str) -> dict[str, Any]:
        book = self.book(import_id)
        status = "ready"
        error = ""
        if action == "compile" and not callable(self.core.materialize_book_document):
            status, error = "unsupported", "BOOK_COMPILE_UNSUPPORTED"
        elif not book[f"can_{action}"]:
            status, error = "blocked", f"BOOK_{action.upper()}_NOT_ELIGIBLE"
        else:
            args = dict(user_id=self.user_id, import_id=import_id, run_id=book["run_id"])
            try:
                if action == "process":
                    if book["error_code"] or (book["document_id"] and self.core.get_book_document(user_id=self.user_id, document_id=book["document_id"]).parser_version != self.core.book_documents.parser_version):
                        _, asset = self._source(import_id)
                        upgraded = self.core.import_book_epub(BookImportRequest(user_id=self.user_id,
                            pipeline_version=self._pipeline_version(), rights_attestation_version=RIGHTS_ATTESTATION_VERSION,
                            scan_approved=True, local_only=book["local_only"], requested_by="user"),
                            self.core.store.blobs.resolve(asset["blob_path"]).read_bytes())
                        if upgraded.error_code:
                            return {**self.detail(import_id), "status":upgraded.status, "error_code":upgraded.error_code}
                        args["run_id"] = upgraded.run_id
                    result = self.core.construct_book_document(BookDocumentRequest(**args))
                    if result.document_id:
                        result = self.core.evaluate_book_document_quality(
                            BookQualityRequest(**args, document_id=result.document_id),
                        )
                    status, error = result.status, result.error_code
                else:
                    self.core.materialize_book_document(BookMaterializationRequest(**args, document_id=book["document_id"]))
            except (ValueError, OSError, RuntimeError):
                status, error = "failed", f"BOOK_{action.upper()}_FAILED"
        return {**self.detail(import_id), "status": status, "error_code": error}
