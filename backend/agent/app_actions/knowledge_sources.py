"""Typed App Actions over the canonical Knowledge Wiki and Books library owners."""

from __future__ import annotations

from typing import Any, Callable

from agent.app_actions.models import AppActionContext, AppActionDefinition
from agent.config import get_settings
from agent.knowledge.book_library import BookLibrary
from agent.knowledge.runtime import get_knowledge_core
from agent.obsidian.wiki import KnowledgeWikiError
from agent.obsidian.wiki_runtime import get_knowledge_wiki
from agent.tools.registry import CapabilityAccess


KNOWLEDGE_SOURCE_IMPORT_ACTION_ID = "knowledge.source.import"
KNOWLEDGE_HEALTH_CHECK_ACTION_ID = "knowledge.health.check"
KNOWLEDGE_INDEX_REBUILD_ACTION_ID = "knowledge.index.rebuild"
BOOK_IMPORT_ACTION_ID = "book.import"
BOOK_PROCESS_ACTION_ID = "book.process"
BOOK_COMPILE_ACTION_ID = "book.compile"

KNOWLEDGE_SOURCE_ACTION_IDS = frozenset({
    KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
    KNOWLEDGE_HEALTH_CHECK_ACTION_ID,
    KNOWLEDGE_INDEX_REBUILD_ACTION_ID,
    BOOK_IMPORT_ACTION_ID,
    BOOK_PROCESS_ACTION_ID,
    BOOK_COMPILE_ACTION_ID,
})
KNOWLEDGE_SOURCE_CONFIRMED_ACTION_IDS = frozenset({
    KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
    BOOK_PROCESS_ACTION_ID,
    BOOK_COMPILE_ACTION_ID,
})


class KnowledgeSourceActionError(ValueError):
    def __init__(self, code: str, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.unavailable = unavailable


BookLibraryProvider = Callable[[], BookLibrary]
KnowledgeWikiProvider = Callable[[], Any]


def _default_book_library() -> BookLibrary:
    return BookLibrary(get_knowledge_core(), get_settings().honcho_user_id)


class KnowledgeSourceActionService:
    """Keep action policy thin while canonical modules own every mutation."""

    def __init__(
        self,
        *,
        book_library_provider: BookLibraryProvider | None = None,
        knowledge_wiki_provider: KnowledgeWikiProvider | None = None,
    ) -> None:
        self._book_library_provider = book_library_provider or _default_book_library
        self._knowledge_wiki_provider = knowledge_wiki_provider or get_knowledge_wiki

    def execute(
        self,
        action_id: str,
        arguments: dict[str, Any],
        _context: AppActionContext,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        try:
            if action_id == KNOWLEDGE_HEALTH_CHECK_ACTION_ID:
                return self._check_health(arguments)
            if action_id == KNOWLEDGE_INDEX_REBUILD_ACTION_ID:
                return self._rebuild_index()
            if action_id == KNOWLEDGE_SOURCE_IMPORT_ACTION_ID:
                if not confirmed:
                    raise KnowledgeSourceActionError("CONFIRMATION_REQUIRED", "Confirm importing this source into Knowledge.")
                return self._import_source(arguments)
            if action_id == BOOK_IMPORT_ACTION_ID:
                return self._import_book(arguments)
            if action_id in {BOOK_PROCESS_ACTION_ID, BOOK_COMPILE_ACTION_ID}:
                if not confirmed:
                    raise KnowledgeSourceActionError("CONFIRMATION_REQUIRED", "Confirm changing this Book knowledge.")
                return self._book_action(action_id, arguments)
        except KnowledgeSourceActionError:
            raise
        except KeyError as exc:
            raise KnowledgeSourceActionError("KNOWLEDGE_TARGET_NOT_FOUND", "The requested source or book was not found.", unavailable=True) from exc
        except KnowledgeWikiError as exc:
            raise KnowledgeSourceActionError("KNOWLEDGE_POLICY_BLOCKED", str(exc)) from exc
        except ValueError as exc:
            code = str(exc)
            if not code.startswith("BOOK_"):
                code = "INVALID_ACTION_ARGUMENTS"
            raise KnowledgeSourceActionError(code, _book_error_message(code) if code.startswith("BOOK_") else str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise KnowledgeSourceActionError("KNOWLEDGE_ACTION_FAILED", str(exc)) from exc
        raise KnowledgeSourceActionError("ACTION_UNAVAILABLE", f"{action_id} is unavailable.", unavailable=True)

    def _check_health(self, arguments: dict[str, Any]) -> dict[str, Any]:
        stale_days = arguments.get("stale_days", 120)
        if isinstance(stale_days, bool) or not isinstance(stale_days, int) or not 0 <= stale_days <= 3650:
            raise KnowledgeSourceActionError(
                "INVALID_ACTION_ARGUMENTS",
                "Stale days must be an integer between 0 and 3650.",
            )
        result = dict(self._knowledge_wiki_provider().lint(stale_days=stale_days, write_report=True))
        return {
            "changed": True,
            "lint": result,
            "_target_kind": "knowledge_health",
            "_target_id": "knowledge-health",
            "_message": "Checked Knowledge health.",
        }

    def _rebuild_index(self) -> dict[str, Any]:
        result = dict(self._knowledge_wiki_provider().rebuild_index())
        return {
            "changed": True,
            "index": {
                "path": str(result.get("path") or "Knowledge/index.md"),
                "page_count": int(result.get("page_count") or 0),
            },
            "_target_kind": "knowledge_index",
            "_target_id": "knowledge-index",
            "_message": f"Rebuilt the Knowledge index for {int(result.get('page_count') or 0)} pages.",
        }

    def _import_source(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source_path = _required_string(arguments, "source_path")
        synthesis = _required_string(arguments, "content")
        result = dict(self._knowledge_wiki_provider().ingest_source(
            source_path=source_path,
            title=str(arguments.get("title") or "").strip(),
            synthesis=synthesis,
            description=str(arguments.get("description") or "").strip(),
            links=_string_list(arguments.get("links")),
            tags=_string_list(arguments.get("tags")),
            related_pages=_dictionary_list(arguments.get("related_pages")),
            source_trust=str(arguments.get("source_trust") or "approved_path").strip(),
            provenance=_provenance_list(arguments.get("provenance")),
            approved_source=True,
        ))
        source_page = dict(result.get("source_page") or {})
        page = dict(source_page.get("page") or {})
        target_id = str(source_page.get("ref") or page.get("id") or "knowledge-source")
        return {
            "changed": bool(source_page.get("created") or source_page.get("updated")),
            "source_import": {
                "ref": target_id,
                "title": str(page.get("title") or arguments.get("title") or "Imported source"),
                "status": str(page.get("status") or "draft"),
                "sensitivity": str(page.get("sensitivity") or "private"),
                "source_trust": str(result.get("source_trust") or "approved_path"),
            },
            "_target_kind": "knowledge_source",
            "_target_id": target_id,
            "_message": f"Imported {str(page.get('title') or 'the source')} into Knowledge.",
        }

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
            rights_attestation_version=_required_string(arguments, "rights_attestation_version"),
            scan_approved=arguments.get("scan_approved") is True,
            local_only=arguments.get("local_only") is True,
        )
        if result.get("error_code"):
            code = str(result["error_code"])
            raise KnowledgeSourceActionError(code, _book_error_message(code))
        return self._book_result(result, message="Imported the EPUB and built its Book knowledge.")

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
            "changed": True,
            "library": {
                "schema_version": str(result.get("schema_version") or "books-library-v1"),
                "book": book,
                "status": str(result.get("status") or "ready"),
                "error_code": str(result.get("error_code") or ""),
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
            id=KNOWLEDGE_HEALTH_CHECK_ACTION_ID,
            title="Check Knowledge health",
            description="Lint the maintained Knowledge Wiki and write its local health report.",
            confirmation_rule="none",
            argument_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "stale_days": {"type": "integer", "minimum": 0, "maximum": 3650},
                },
            },
            ui_reference="knowledge",
            audit_label="knowledge.health.check",
            **common,
        ),
        AppActionDefinition(
            id=KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
            title="Import a source into Knowledge",
            description="Import a maintained synthesis of one explicitly approved Vault source.",
            confirmation_rule="operation_bound",
            argument_schema={
                "type": "object",
                "required": ["source_path", "content"],
                "additionalProperties": False,
                "properties": {
                    "source_path": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "description": {"type": "string"},
                    "links": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "related_pages": {"type": "array", "items": {"type": "object"}},
                    "source_trust": {"type": "string"},
                    "provenance": {
                        "type": "array",
                        "items": {"anyOf": [{"type": "object"}, {"type": "string"}]},
                    },
                },
            },
            ui_reference="knowledge.sources",
            audit_label="knowledge.source.import",
            **common,
        ),
        AppActionDefinition(
            id=KNOWLEDGE_INDEX_REBUILD_ACTION_ID,
            title="Rebuild the Knowledge index",
            description="Regenerate the derived Knowledge Wiki index from canonical pages.",
            confirmation_rule="none",
            idempotent=True,
            argument_schema={"type": "object", "additionalProperties": False},
            ui_reference="knowledge",
            audit_label="knowledge.index.rebuild",
            **{key: value for key, value in common.items() if key != "idempotent"},
        ),
        AppActionDefinition(
            id=BOOK_IMPORT_ACTION_ID,
            title="Import an EPUB",
            description="Import an explicitly selected EPUB through the local Book pipeline.",
            confirmation_rule="existing_import_consent",
            executor_location="server_and_client",
            argument_schema={
                "type": "object",
                "properties": {
                    "file_name": {"type": "string"},
                    "rights_attestation_version": {"type": "string"},
                    "scan_approved": {"type": "boolean"},
                    "local_only": {"type": "boolean"},
                },
            },
            ui_reference="books.library",
            audit_label="book.import",
            **{key: value for key, value in common.items() if key != "executor_location"},
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
            )
        ],
    ]


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = str(arguments.get(key) or "").strip()
    if not value:
        raise KnowledgeSourceActionError("INVALID_ACTION_ARGUMENTS", f"{key.replace('_', ' ').title()} is required.")
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dictionary_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _provenance_list(value: Any) -> list[dict[str, Any] | str]:
    if not isinstance(value, list):
        return []
    return [
        dict(item) if isinstance(item, dict) else str(item).strip()
        for item in value
        if isinstance(item, dict) or str(item).strip()
    ]


def _book_error_message(code: str) -> str:
    return {
        "BOOK_RIGHTS_ATTESTATION_REQUIRED": "Confirm that you have permission to import and process this EPUB.",
        "BOOK_SCAN_APPROVAL_REQUIRED": "Allow the local malware scan before importing this EPUB.",
        "BOOK_EPUB_REQUIRED": "Choose an EPUB file.",
        "BOOK_EPUB_EMPTY": "The EPUB upload is empty.",
        "BOOK_EPUB_TOO_LARGE": "The EPUB exceeds the configured local import limit.",
        "BOOK_UPLOAD_INVALID": "The EPUB upload is invalid.",
        "BOOK_PROCESS_NOT_ELIGIBLE": "This Book is not eligible for local processing.",
        "BOOK_COMPILE_NOT_ELIGIBLE": "This Book is not eligible for Book skill compilation.",
        "BOOK_PROCESS_FAILED": "The EPUB could not be processed.",
        "BOOK_COMPILE_FAILED": "Book skill knowledge could not be built.",
    }.get(code, code.replace("_", " ").title())
