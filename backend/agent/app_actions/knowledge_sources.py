"""Typed App Actions over the canonical Books library owner."""

from __future__ import annotations

from typing import Any, Callable

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.config import get_settings
from agent.knowledge.book_library import BookLibrary
from agent.knowledge.runtime import get_knowledge_core
from agent.tools.registry import CapabilityAccess


BOOK_IMPORT_ACTION_ID = "book.import"
BOOK_PROCESS_ACTION_ID = "book.process"
BOOK_COMPILE_ACTION_ID = "book.compile"
BOOK_READER_PROGRESS_ACTION_ID = "book.reader.progress"
BOOK_REMOVE_ACTION_ID = "book.remove"

KNOWLEDGE_SOURCE_ACTION_IDS = frozenset({
    BOOK_IMPORT_ACTION_ID,
    BOOK_PROCESS_ACTION_ID,
    BOOK_COMPILE_ACTION_ID,
    BOOK_READER_PROGRESS_ACTION_ID,
    BOOK_REMOVE_ACTION_ID,
})
KNOWLEDGE_SOURCE_CONFIRMED_ACTION_IDS = frozenset({
    BOOK_PROCESS_ACTION_ID,
    BOOK_COMPILE_ACTION_ID,
    BOOK_REMOVE_ACTION_ID,
})


class KnowledgeSourceActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


BookLibraryProvider = Callable[[], BookLibrary]


def _default_book_library() -> BookLibrary:
    return BookLibrary(get_knowledge_core(), get_settings().honcho_user_id)


class KnowledgeSourceActionService:
    """Keep action policy thin while canonical modules own every mutation."""

    def __init__(
        self,
        *,
        book_library_provider: BookLibraryProvider | None = None,
    ) -> None:
        self._book_library_provider = book_library_provider or _default_book_library

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            if action_id == BOOK_IMPORT_ACTION_ID:
                return self._import_book(arguments)
            if action_id == BOOK_READER_PROGRESS_ACTION_ID:
                import_id = _required_string(arguments, "import_id")
                result = self._book_library_provider().save_reader_progress(import_id, arguments.get("progress"))
                return {"changed":True, "reader":result, "_target_kind":"book", "_target_id":import_id, "_message":"Reading position saved."}
            if action_id == BOOK_REMOVE_ACTION_ID:
                if not confirmed:
                    raise KnowledgeSourceActionError("CONFIRMATION_REQUIRED", "Confirm removing this book from your shelf.")
                import_id = _required_string(arguments, "import_id")
                result = self._book_library_provider().remove(import_id)
                return {"changed":result["changed"], "library":result, "_target_kind":"book", "_target_id":import_id,
                        "_message":"Removed the book from your shelf." if result["changed"] else "The book is already off your shelf."}
            if action_id in {BOOK_PROCESS_ACTION_ID, BOOK_COMPILE_ACTION_ID}:
                if not confirmed:
                    raise KnowledgeSourceActionError("CONFIRMATION_REQUIRED", "Confirm changing this Book knowledge.")
                return self._book_action(action_id, arguments)
        except KnowledgeSourceActionError:
            raise
        except KeyError as exc:
            raise KnowledgeSourceActionError("KNOWLEDGE_TARGET_NOT_FOUND", "The requested source or book was not found.", unavailable=True) from exc
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("BOOK_"):
                code = "INVALID_ACTION_ARGUMENTS"
            raise KnowledgeSourceActionError(code, _book_error_message(code) if code.startswith("BOOK_") else str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise KnowledgeSourceActionError("KNOWLEDGE_ACTION_FAILED", str(exc)) from exc
        raise KnowledgeSourceActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    def _import_book(self, arguments: dict[str, Any]) -> dict[str, Any]:
        content = arguments.get("_content")
        if content is None:
            return {
                "changed": False,
                "client_effect": {"type": "book.import.picker.open", "accept": ".epub"},
                "requires_user_selection": True,
                "_target_kind": "books_library",
                "_target_id": "books-library",
                "_message": "Choose an EPUB to import.",
            }
        if not isinstance(content, (bytes, bytearray)):
            raise KnowledgeSourceActionError("BOOK_UPLOAD_INVALID", "The EPUB upload is invalid.")
        library = self._book_library_provider()
        result = library.import_epub(
            filename=_required_string(arguments, "file_name"),
            content=bytes(content),
            rights_attestation_version=str(arguments.get("rights_attestation_version") or "local-epub-v1"),
            scan_approved=True,
            local_only=arguments.get("local_only") is True,
            defer_processing=arguments.get("defer_processing") is True,
        )
        if result.get("error_code") and not result.get("book", {}).get("can_read"):
            code = str(result["error_code"])
            raise KnowledgeSourceActionError(code, _book_error_message(code))
        if result.get("error_code"):
            result = {**result, "status": "imported", "error_code": ""}
        return self._book_result(result, message=("This book is already on your shelf." if result.get("already_present") else "Added the book to your shelf."))

    def _book_action(self, action_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        import_id = str(arguments.get("import_id") or arguments.get("reference") or "").strip()
        if not import_id:
            raise KnowledgeSourceActionError("INVALID_ACTION_ARGUMENTS", "Book reference is required.")
        operation = "process" if action_id == BOOK_PROCESS_ACTION_ID else "compile"
        result = self._book_library_provider().action(import_id, operation)
        if result.get("error_code"):
            code = str(result["error_code"])
            raise KnowledgeSourceActionError(code, _book_error_message(code))
        verb = "Processed the EPUB locally." if operation == "process" else "Built the Book skill knowledge."
        return self._book_result(result, message=verb)

    @staticmethod
    def _book_result(result: dict[str, Any], *, message: str) -> dict[str, Any]:
        book = dict(result.get("book") or {})
        import_id = str(book.get("id") or "books-library")
        return {
            "changed": not bool(result.get("already_present")),
            "library": {
                "schema_version": str(result.get("schema_version") or "books-library-v1"),
                "book": book,
                "status": str(result.get("status") or "ready"),
                "error_code": str(result.get("error_code") or ""),
                "already_present": bool(result.get("already_present")),
                "processing_pending": bool(result.get("processing_pending")),
            },
            "_target_kind": "book_document",
            "_target_id": import_id,
            "_message": message,
        }


def knowledge_source_action_definitions() -> list[AppActionDefinition]:
    common = {
        "version": "1",
        "owner": "knowledge-core",
        "scope": "user",
        "access_class": CapabilityAccess.WRITE.value,
        "executor_location": "server",
        "supports_undo": False,
        "idempotent": False,
        "result_schema": {"type": "object", "required": ["changed"]},
    }
    return [
        AppActionDefinition(
            id=BOOK_IMPORT_ACTION_ID,
            title="Import an EPUB",
            description="Import an explicitly selected EPUB through the local Book pipeline.",
            confirmation_rule="none",
            executor_location="server_and_client",
            argument_schema={
                "type": "object",
                "properties": {
                    "file_name": {"type": "string"},
                    "rights_attestation_version": {"type": "string"},
                    "scan_approved": {"type": "boolean"},
                    "local_only": {"type": "boolean"},
                    "defer_processing": {"type":"boolean"},
                },
            },
            ui_reference="books.library",
            audit_label="book.import",
            **{key: value for key, value in common.items() if key != "executor_location"},
        ),
        AppActionDefinition(
            id=BOOK_READER_PROGRESS_ACTION_ID,
            title="Save Book reading position",
            description="Save the user's reading progress in the local Book library.",
            confirmation_rule="none",
            argument_schema={"type":"object", "required":["import_id","progress"], "properties":{
                "import_id":{"type":"string"}, "progress":{"type":"number","minimum":0,"maximum":1}}, "additionalProperties":False},
            ui_reference="books.reader", audit_label="book.reader.progress", **common,
        ),
        *[
            AppActionDefinition(
                id=action_id,
                title=title,
                description=description,
                confirmation_rule="operation_bound",
                argument_schema={
                    "type": "object",
                    "properties": {
                        "import_id": {"type": "string"},
                        "reference": {"type": "string"},
                    },
                },
                ui_reference="books.library",
                audit_label=action_id,
                **common,
            )
            for action_id, title, description in (
                (BOOK_PROCESS_ACTION_ID, "Process a Book EPUB", "Construct and evaluate the canonical BookDocument locally."),
                (BOOK_COMPILE_ACTION_ID, "Build Book skill knowledge", "Compile an eligible BookDocument into canonical Book knowledge."),
                (BOOK_REMOVE_ACTION_ID, "Remove a Book from the shelf", "Remove the book from the user's shelf and active retrieval while retaining its local source and reading progress."),
            )
        ],
    ]


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = str(arguments.get(key) or "").strip()
    if not value:
        raise KnowledgeSourceActionError("INVALID_ACTION_ARGUMENTS", f"{key.replace('_', ' ').title()} is required.")
    return value


def _book_error_message(code: str) -> str:
    return {
        "BOOK_RIGHTS_ATTESTATION_REQUIRED": "Confirm that you have permission to import and process this EPUB.",
        "BOOK_SCAN_APPROVAL_REQUIRED": "Allow the local malware scan before importing this EPUB.",
        "BOOK_EPUB_REQUIRED": "Choose an EPUB file.",
        "BOOK_EPUB_EMPTY": "The EPUB upload is empty.",
        "BOOK_EPUB_TOO_LARGE": "The EPUB exceeds the configured local import limit.",
        "BOOK_UPLOAD_FORMAT_UNSUPPORTED": "Choose an EPUB, TXT or Markdown book file.",
        "BOOK_TEXT_TOO_SHORT": "This file has too little readable text to import.",
        "BOOK_TEXT_ENCODING_INVALID": "Save this text file as UTF-8 and try again.",
        "BOOK_COVER_INVALID": "Choose a valid PNG, JPEG or WebP cover smaller than 6 MB.",
        "BOOK_URL_PROVIDER_UNSUPPORTED": "Use a direct book URL from Project Gutenberg or Standard Ebooks.",
        "BOOK_UPLOAD_INVALID": "This file could not be read as an EPUB, TXT or Markdown book. Choose a readable book file and try again.",
        "BOOK_PROCESS_NOT_ELIGIBLE": "This Book is not eligible for local processing.",
        "BOOK_COMPILE_NOT_ELIGIBLE": "This Book is not eligible for Book skill compilation.",
        "BOOK_QUALITY_DEGRADED": "The EPUB was imported, but its text quality checks found duplicated content, missing resources, or damaged text. Open the book to inspect the findings before building its Book skill.",
        "BOOK_QUALITY_FAILED": "The EPUB was imported, but its structure or source references could not be verified. Open the book to inspect the findings or try another EPUB edition.",
        "BOOK_OCR_REQUIRED": "The EPUB was imported, but some pages contain image-only text. Local OCR is required before Vellum can build a verified Book skill.",
        "BOOK_PROCESS_FAILED": "The EPUB could not be processed.",
        "BOOK_COMPILE_FAILED": "Book skill knowledge could not be built.",
    }.get(code, code.replace("_", " ").title())
