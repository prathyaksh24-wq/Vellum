from pathlib import Path

from agent.app_actions.knowledge_sources import (
    BOOK_COMPILE_ACTION_ID,
    BOOK_IMPORT_ACTION_ID,
    BOOK_PROCESS_ACTION_ID,
    KNOWLEDGE_HEALTH_CHECK_ACTION_ID,
    KNOWLEDGE_INDEX_REBUILD_ACTION_ID,
    KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
    KnowledgeSourceActionService,
)
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins.registry import PluginRegistry
from agent.plugins.youtube_contract import (
    YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
    YOUTUBE_CONNECTION_START_ACTION_ID,
    YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID,
    YOUTUBE_SYNC_ACTION_ID,
)
from agent.plugins.youtube_controls import youtube_plugin_contribution


class _Wiki:
    def __init__(self) -> None:
        self.imports = []
        self.lints = []

    def rebuild_index(self):
        return {"path": "Knowledge/index.md", "page_count": 4}

    def ingest_source(self, **payload):
        self.imports.append(payload)
        return {
            "source_trust": "approved_path",
            "source_page": {
                "created": True,
                "ref": "source:opaque-1",
                "page": {"title": "Private source", "status": "draft", "sensitivity": "private"},
            },
        }

    def lint(self, **payload):
        self.lints.append(payload)
        return {"health": "healthy", "stale_days": payload["stale_days"], "issues": []}


class _Books:
    def __init__(self) -> None:
        self.imports = []
        self.actions = []

    def import_epub(self, **payload):
        self.imports.append(payload)
        return {
            "schema_version": "books-library-v1",
            "status": "ready",
            "error_code": "",
            "book": {
                "id": "book-1",
                "title": "The Book",
                "local_only": payload["local_only"],
                "skill_status": "compiled",
            },
        }

    def action(self, import_id, operation):
        self.actions.append((import_id, operation))
        return {
            "schema_version": "books-library-v1",
            "status": "ready",
            "error_code": "",
            "book": {"id": import_id, "title": "The Book", "skill_status": "compiled"},
        }


class _YouTubeControls:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, action_id, arguments, *, confirmed=False):
        self.calls.append((action_id, arguments, confirmed))
        return {
            "changed": True,
            "_target_kind": "connector_connection",
            "_target_id": "youtube",
            "_message": "YouTube action completed.",
        }


def _context(source="nlp"):
    return AppActionContext(source=source, invocation_conversation_id="chat-1")


def _knowledge_runtime():
    wiki = _Wiki()
    books = _Books()
    service = KnowledgeSourceActionService(
        book_library_provider=lambda: books,
        knowledge_wiki_provider=lambda: wiki,
    )
    runtime = AppActionRuntime(knowledge_source_handler=service.execute)
    return runtime, wiki, books


def _youtube_runtime(tmp_path: Path, *, connected: bool = True):
    root = tmp_path / "plugins"
    plugin = root / "connectors" / "youtube"
    plugin.mkdir(parents=True)
    capabilities = "\n".join(
        f"  - {item}"
        for item in (
            YOUTUBE_CONNECTION_START_ACTION_ID,
            YOUTUBE_SYNC_ACTION_ID,
            YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID,
            "youtube.intelligence.rebuild",
        )
    )
    (plugin / "plugin.yaml").write_text(
        "id: youtube\nname: YouTube\ntype: connector\ncategory: Test\ncapabilities:\n"
        + capabilities
        + "\n",
        encoding="utf-8",
    )
    registry = PluginRegistry(root, state_path=tmp_path / "plugin-state.json")
    controls = _YouTubeControls()
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(
        youtube_plugin_contribution(
            controls,
            status_provider=lambda: {"configured": True, "connected": connected},
        )
    )
    return runtime, registry, controls


def test_knowledge_index_and_epub_import_use_canonical_owners_without_user_claims():
    runtime, wiki, books = _knowledge_runtime()

    rebuilt = runtime.dispatch(AppActionRequest(action_id=KNOWLEDGE_INDEX_REBUILD_ACTION_ID), _context())
    imported = runtime.dispatch(
        AppActionRequest(
            action_id=BOOK_IMPORT_ACTION_ID,
            arguments={
                "file_name": "book.epub",
                "rights_attestation_version": "book-rights-v1",
                "scan_approved": True,
                "local_only": True,
                "_content": b"epub-fixture",
            },
        ),
        _context("ui"),
    )

    assert rebuilt.status == "applied"
    assert rebuilt.result["index"] == {"path": "Knowledge/index.md", "page_count": 4}
    assert wiki.imports == []
    assert imported.status == "applied"
    assert imported.result["library"]["book"]["local_only"] is True
    assert books.imports[0]["content"] == b"epub-fixture"
    assert "_content" not in imported.model_dump_json()
    assert "reading_status" not in imported.model_dump_json()
    assert "belief" not in imported.model_dump_json()


def test_knowledge_health_check_uses_the_canonical_wiki_linter():
    runtime, wiki, _books = _knowledge_runtime()

    receipt = runtime.dispatch(
        AppActionRequest(action_id=KNOWLEDGE_HEALTH_CHECK_ACTION_ID, arguments={"stale_days": 45}),
        _context("ui"),
    )

    assert receipt.status == "applied"
    assert receipt.result["lint"] == {"health": "healthy", "stale_days": 45, "issues": []}
    assert wiki.lints == [{"stale_days": 45, "write_report": True}]


def test_source_path_is_withheld_from_confirmation_and_only_used_after_confirmation():
    runtime, wiki, _books = _knowledge_runtime()
    source_path = r"D:\Private\identity-notes.md"
    request = AppActionRequest(
        action_id=KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
        arguments={
            "source_path": source_path,
            "title": "Private source",
            "content": "Maintained synthesis only.",
            "provenance": [{"kind": "approved_path", "ref": "private-source"}],
        },
    )

    review = runtime.dispatch(request, _context())

    assert review.status == "confirmation_required"
    assert source_path not in review.model_dump_json()
    assert "Maintained synthesis only" not in review.model_dump_json()
    assert wiki.imports == []
    applied = runtime.confirm(review.confirmation.token, request, _context())
    assert applied.status == "applied"
    assert applied.target.id == "source:opaque-1"
    assert source_path not in applied.model_dump_json()
    assert wiki.imports[0]["source_path"] == source_path
    assert wiki.imports[0]["synthesis"] == "Maintained synthesis only."
    assert wiki.imports[0]["provenance"] == [{"kind": "approved_path", "ref": "private-source"}]


def test_source_import_rejects_a_raw_path_without_maintained_synthesis():
    runtime, wiki, _books = _knowledge_runtime()

    review = runtime.dispatch(
        AppActionRequest(
            action_id=KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
            arguments={"source_path": "Library/Research/raw.md"},
        ),
        _context(),
    )
    request = AppActionRequest(
        action_id=KNOWLEDGE_SOURCE_IMPORT_ACTION_ID,
        arguments={"source_path": "Library/Research/raw.md"},
    )
    receipt = runtime.confirm(review.confirmation.token, request, _context())

    assert review.status == "confirmation_required"
    assert receipt.status == "failed"
    assert receipt.error_code == "INVALID_ACTION_ARGUMENTS"
    assert wiki.imports == []


def test_book_process_and_compile_require_bound_confirmation():
    runtime, _wiki, books = _knowledge_runtime()

    for action_id, operation in (
        (BOOK_PROCESS_ACTION_ID, "process"),
        (BOOK_COMPILE_ACTION_ID, "compile"),
    ):
        request = AppActionRequest(action_id=action_id, arguments={"import_id": "book-1"})
        review = runtime.dispatch(request, _context("ui"))
        assert review.status == "confirmation_required"
        assert ("book-1", operation) not in books.actions
        applied = runtime.confirm(review.confirmation.token, request, _context("ui"))
        assert applied.status == "applied"
        assert ("book-1", operation) in books.actions


def test_youtube_actions_follow_plugin_state_and_disconnect_confirmation(tmp_path):
    runtime, registry, controls = _youtube_runtime(tmp_path)
    action_ids = {item.id for item in runtime.catalog(_context()).actions}
    assert {YOUTUBE_CONNECTION_START_ACTION_ID, YOUTUBE_SYNC_ACTION_ID}.issubset(action_ids)

    request = AppActionRequest(action_id=YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID)
    review = runtime.dispatch(request, _context())
    assert review.status == "confirmation_required"
    assert controls.calls == []
    applied = runtime.confirm(review.confirmation.token, request, _context())
    assert applied.status == "applied"
    assert controls.calls == [(YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID, {}, True)]

    registry.set_enabled("youtube", False)
    assert YOUTUBE_SYNC_ACTION_ID not in {item.id for item in runtime.catalog(_context()).actions}
    unavailable = runtime.dispatch(AppActionRequest(action_id=YOUTUBE_SYNC_ACTION_ID), _context())
    assert (unavailable.status, unavailable.error_code) == ("unavailable", "ACTION_UNAVAILABLE")


def test_youtube_intelligence_rebuild_remains_available_without_oauth(tmp_path):
    runtime, _registry, _controls = _youtube_runtime(tmp_path, connected=False)

    action_ids = {item.id for item in runtime.catalog(_context()).actions}

    assert YOUTUBE_CONNECTION_START_ACTION_ID in action_ids
    assert YOUTUBE_INTELLIGENCE_REBUILD_ACTION_ID in action_ids
    assert YOUTUBE_SYNC_ACTION_ID not in action_ids
    assert YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID not in action_ids


def test_nlp_matches_explicit_knowledge_and_youtube_controls_without_catching_questions():
    runtime, _wiki, _books = _knowledge_runtime()

    assert runtime.match_submission("rebuild the knowledge index").action_id == KNOWLEDGE_INDEX_REBUILD_ACTION_ID
    assert runtime.match_submission("check knowledge health").action_id == KNOWLEDGE_HEALTH_CHECK_ACTION_ID
    assert runtime.match_submission("import a book").action_id == BOOK_IMPORT_ACTION_ID
    assert runtime.match_submission("process book book-1").action_id == BOOK_PROCESS_ACTION_ID
    assert runtime.match_submission("build book skill book-1").action_id == BOOK_COMPILE_ACTION_ID
    assert runtime.match_submission("connect YouTube").action_id == YOUTUBE_CONNECTION_START_ACTION_ID
    assert runtime.match_submission("sync YouTube").action_id == YOUTUBE_SYNC_ACTION_ID
    assert runtime.match_submission("disconnect YouTube").action_id == YOUTUBE_CONNECTION_DISCONNECT_ACTION_ID
    assert runtime.match_submission("How does YouTube synchronization work?") is None
    assert runtime.match_submission("import knowledge source at Library/Research/raw.md") is None
