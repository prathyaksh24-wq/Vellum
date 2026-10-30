"""Isolated Books HTTP fixture for browser QA. Never loads the user's profile or data."""

from io import BytesIO
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
import os
import time

os.environ.setdefault("OPENROUTER_API_KEY", "books-qa-unused")
os.environ.setdefault("OBSIDIAN_VAULT_PATH", str(Path(os.environ.get("BOOKS_QA_TEMP", ".")).resolve()))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw

from agent.knowledge import api
from agent.knowledge.models import BookDocumentRequest, BookImportRequest, BookQualityRequest
from agent.knowledge.runtime import set_knowledge_core
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.store import KnowledgeStore
from agent.knowledge.book_library import BookLibrary
from agent.app_actions import api as action_api
from agent.app_actions.knowledge_sources import KnowledgeSourceActionService
from agent.app_actions.runtime import AppActionRuntime
from test_book_library_api import CleanScanner, FixedBookEmbedder, RecordingBookIndex, _epub_bytes


def create_app() -> FastAPI:
    root = Path(mkdtemp(prefix="books-ui-live-", dir=os.environ.get("BOOKS_QA_TEMP")))
    core = KnowledgeCore(KnowledgeStore(root / "core.db", root / "blobs"),
                         conversations_path=root / "ui" / "conversations.json", vault_root=root / "unused",
                         book_malware_scanner=CleanScanner(), book_embedding_provider=FixedBookEmbedder(),
                         book_malware_scan_enabled=False,
                         book_retrieval_index=RecordingBookIndex())
    api.get_settings = lambda: SimpleNamespace(honcho_user_id="books-ui-fixture")
    set_knowledge_core(core)
    action_service = KnowledgeSourceActionService(book_library_provider=lambda: BookLibrary(core, "books-ui-fixture"))
    action_runtime = AppActionRuntime(knowledge_source_handler=action_service.execute)
    action_api.get_app_action_runtime = lambda: action_runtime
    action_api._book_library = lambda: BookLibrary(core, "books-ui-fixture")
    processing_delay = float(os.environ.get("BOOKS_QA_PROCESS_DELAY_SECONDS", "0"))
    if processing_delay:
        materialize = core.materialize_book_document
        def delayed_materialize(request):
            time.sleep(processing_delay)
            return materialize(request)
        core.materialize_book_document = delayed_materialize
    for title, color in [("Library Fixture", "#267267"), ("Field Notes", "#ac423e"),
                         ("A Longer Title About Questions And Understanding", "#335d97")]:
        cover = Image.new("RGB", (360, 540), color)
        ImageDraw.Draw(cover).multiline_text((30, 80), title.replace(" ", "\n") + "\n\nTEST FIXTURE", fill="white", font_size=25)
        output = BytesIO()
        cover.save(output, format="PNG")
        # Replace only the synthetic title inside this test archive.
        from zipfile import ZipFile
        source, target = BytesIO(_epub_bytes(cover=output.getvalue())), BytesIO()
        with ZipFile(source) as original, ZipFile(target, "w") as archive:
            for entry in original.infolist():
                content = original.read(entry)
                if entry.filename.endswith("package.opf"):
                    content = content.replace(b"Library Fixture", title.encode())
                archive.writestr(entry, content)
        asset = target.getvalue()
        (root / (title.split()[0] + ".epub")).write_bytes(asset)
        status = core.import_book_epub(BookImportRequest(user_id="books-ui-fixture", scan_approved=True,
                                                       rights_attestation_version="local-epub-v1", local_only=True), asset)
        args = dict(user_id="books-ui-fixture", import_id=status.import_id, run_id=status.run_id)
        document = core.construct_book_document(BookDocumentRequest(**args))
        core.evaluate_book_document_quality(BookQualityRequest(**args, document_id=document.document_id))
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5175", "http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.include_router(api.router, prefix="/api/knowledge")
    app.include_router(action_api.router, prefix="/api")
    print(f"Books QA data: {root}", flush=True)
    return app
