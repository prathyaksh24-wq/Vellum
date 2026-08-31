"""Metadata-only presentation of canonical Books, with no separate library store."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any
from zipfile import BadZipFile

from PIL import Image, UnidentifiedImageError

from agent.knowledge.book_documents import BookDocumentError, read_epub_presentation
from agent.knowledge.models import BookDocumentRequest, BookMaterializationRequest, BookQualityRequest

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

    def _source(self, import_id: str):
        status = self.core.get_book_ingestion_status(user_id=self.user_id, import_id=import_id)
        asset = self.core.store.get_book_library_asset(
            user_id=self.user_id, import_id=import_id, run_id=status.run_id,
        )
        return status, asset

    def book(self, import_id: str, *, detail: bool = False) -> dict[str, Any]:
        status, asset = self._source(import_id)
        usable = bool(asset["validated"]) and status.status not in {"rejected", "failed_permanent"}
        expected_compiler = str(self.core.book_materializations.compiler_version)
        compiled_current = bool(asset["compiled"]) and str(asset["active_compiler_version"]) == expected_compiler
        book = {
            "id": import_id, "title": "Untitled book", "authors": [], "published_at": "",
            "document_id": status.document_id, "run_id": status.run_id, "state": status.status,
            "error_code": status.error_code, "local_only": status.local_only, "cover_url": "",
            "can_process": usable and not status.quality_evaluated,
            "can_compile": usable and status.quality_outcome == "PASS" and not compiled_current
            and callable(self.core.materialize_book_document),
            "skill_status": "compiled" if compiled_current else "not_compiled",
        }
        if usable:
            try:
                metadata, _, cover_type = read_epub_presentation(self.core.store.blobs.resolve(asset["blob_path"]))
                book.update(title=metadata.title[:1000] or "Untitled book", authors=[a[:300] for a in metadata.creators[:20]],
                            published_at=metadata.published_at[:100])
                if cover_type:
                    book["cover_url"] = f"/api/knowledge/core/books/library/{import_id}/cover"
            except DISPLAY_ERRORS:
                book["display_error"] = "BOOK_METADATA_UNAVAILABLE"
        if detail:
            book.update(sections=[], section_count=0)
            if status.document_id:
                try:
                    document = self.core.get_book_document(user_id=self.user_id, document_id=status.document_id)
                    book["section_count"] = len(document.sections)
                    book["sections"] = [{"id": s.id, "title": s.title[:1000], "block_count": len(s.blocks)}
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
            status, error = "blocked", "BOOK_COMPILE_NOT_ELIGIBLE"
        return {**self.detail(import_id), "status": status, "error_code": error}

    def cover(self, import_id: str) -> tuple[bytes, str]:
        status, asset = self._source(import_id)
        if not asset["validated"] or status.status in {"rejected", "failed_permanent"}:
            raise ValueError("BOOK_COVER_UNAVAILABLE")
        try:
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
