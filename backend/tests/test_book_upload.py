from io import BytesIO
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from agent.app_actions import api as action_api
from agent.app_actions.knowledge_sources import KnowledgeSourceActionService
from agent.app_actions.runtime import AppActionRuntime
from agent.knowledge.book_library import BookLibrary
from agent.knowledge.book_upload import prepare_book_upload, download_book_upload
from test_book_library_api import library_client, _epub_bytes


def test_text_and_markdown_imports_are_deterministic_epubs_with_complete_text(library_client):
    client, core, _ = library_client
    text = "CHAPTER I\n\nThe first chapter is complete.\n\nCHAPTER II\n\nThe final chapter is complete."
    for suffix in ("txt", "md"):
        name, content = prepare_book_upload("book." + suffix, text.encode(), title="A real title", author="An author")
        assert name.endswith(".epub")
        assert content == prepare_book_upload("book." + suffix, text.encode(), title="A real title", author="An author")[1]
        result = BookLibrary(core,"tenant-a").import_epub(filename=name,content=content,rights_attestation_version="local-epub-v1",scan_approved=True,local_only=True)
        assert result["book"]["skill_status"] == "compiled"
        assert result["book"]["title"] == "A real title"
        full = client.get(f'/api/knowledge/core/books/library/{result["book"]["id"]}/reader/full').json()
        assert "The first chapter is complete." in full["content"]
        assert "The final chapter is complete." in full["content"]


def test_custom_cover_keeps_real_aspect_and_extracts_palette(library_client):
    _, core, _ = library_client
    image = BytesIO(); Image.new("RGB",(200,300),"#ae3329").save(image,format="PNG")
    filename, content = prepare_book_upload("book.epub",_epub_bytes(),title="Chosen title",author="Chosen author",cover=image.getvalue())
    result=BookLibrary(core,"tenant-a").import_epub(filename=filename,content=content,rights_attestation_version="local-epub-v1",scan_approved=True,local_only=True)
    book=result["book"]
    assert book["title"] == "Chosen title"
    assert book["authors"] == ["Chosen author"]
    assert book["cover_aspect"] == pytest.approx(2/3)
    assert all(book["cover_palette"][key].startswith("#") for key in ("spineColor","accentColor","inkColor"))
    cover, media_type=BookLibrary(core,"tenant-a").cover(book["id"])
    assert cover == image.getvalue() and media_type == "image/png"


def test_user_disabled_scan_is_never_called_and_is_not_recorded_as_clean(library_client):
    _, core, _ = library_client
    calls=[]
    class ForbiddenScanner:
        def scan(self,path):
            calls.append(path)
            raise AssertionError("The user removed malware scanning from book intake")
    core.book_ingestion.scanner=ForbiddenScanner()
    core.book_ingestion.policy=core.book_ingestion.policy.model_copy(update={"malware_scan_enabled":False})
    library=BookLibrary(core,"tenant-a")
    result=library.import_epub(filename="book.epub",content=_epub_bytes(),rights_attestation_version="local-epub-v1",scan_approved=True,local_only=True)
    assert calls==[]
    assert result["book"]["skill_status"]=="compiled"
    assert result["book"]["scan_status"]=="skipped"
    status=core.get_book_ingestion_status(user_id="tenant-a",import_id=result["book"]["id"])
    assert any(receipt.reason_code=="VALIDATED_SCAN_SKIPPED" for receipt in status.receipts)
    rejected=library.import_epub(filename="bad.epub",content=b"not an EPUB archive",rights_attestation_version="local-epub-v1",scan_approved=True,local_only=True)
    assert rejected["status"]=="rejected"
    assert calls==[]


def test_desktop_book_runtime_does_not_install_a_malware_scanner(monkeypatch):
    from agent.knowledge import runtime
    monkeypatch.setattr(runtime,"KnowledgeCore",lambda *args,**kwargs:kwargs)
    options=runtime.build_knowledge_core()
    assert options["book_malware_scan_enabled"] is False
    assert "book_malware_scanner" not in options


def test_supplied_import_api_and_progress_use_canonical_actions(library_client, monkeypatch):
    _, core, _ = library_client
    service=KnowledgeSourceActionService(book_library_provider=lambda:BookLibrary(core,"tenant-a"))
    runtime=AppActionRuntime(knowledge_source_handler=service.execute)
    monkeypatch.setattr(action_api,"get_app_action_runtime",lambda:runtime)
    monkeypatch.setattr(action_api,"_book_library",lambda:BookLibrary(core,"tenant-a"))
    app=FastAPI();app.include_router(action_api.router,prefix="/api")
    text=b"A complete book of sufficient length for the canonical EPUB import pipeline."
    with TestClient(app) as client:
        payload={"rights_attestation_version":"local-epub-v1","scan_approved":"true","local_only":"true","title":"Uploaded text","author":"Real author"}
        response=client.post("/api/app-actions/books/import",data=payload,files={"file":("book.txt",text,"text/plain")})
        assert response.status_code==200,response.text
        receipt=response.json();assert receipt["action_id"]=="book.import" and receipt["status"]=="applied",receipt
        book_id=receipt["result"]["library"]["book"]["id"]
        progress=client.post("/api/app-actions/dispatch",json={"request":{"action_id":"book.reader.progress","arguments":{"import_id":book_id,"progress":.43}},"context":{"source":"ui"}})
        assert progress.json()["status"]=="applied",progress.text
        assert BookLibrary(core,"tenant-a").detail(book_id)["book"]["reader_progress"]==.43
        with pytest.raises(KeyError):
            BookLibrary(core,"tenant-b").save_reader_progress(book_id,.9)
        assert BookLibrary(core,"tenant-a").detail(book_id)["book"]["reader_progress"]==.43
        for value in (-1,2,True):
            rejected=client.post("/api/app-actions/dispatch",json={"request":{"action_id":"book.reader.progress","arguments":{"import_id":book_id,"progress":value}},"context":{"source":"ui"}})
            assert rejected.json()["status"]!="applied"
        assert client.post("/api/app-actions/books/import",data={**payload,"scan_approved":"false"},files={"file":("book.txt",text,"text/plain")}).status_code==200
        assert client.post("/api/app-actions/books/import",files={"file":("book.txt",text,"text/plain")}).status_code==200
        invalid = client.post("/api/app-actions/books/import", data=payload,
                              files={"file": ("broken.epub", b"unreadable archive", "application/epub+zip")})
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "BOOK_UPLOAD_INVALID"
        assert "could not be read" in invalid.json()["detail"]["message"]


def test_duplicate_book_detected_after_title_edit_and_zip_repack_without_losing_progress(library_client):
    _, core, _ = library_client
    library = BookLibrary(core, "tenant-a")
    raw = _epub_bytes()
    args = dict(rights_attestation_version="local-epub-v1", scan_approved=True, local_only=True)
    first = library.import_epub(filename="original.epub", content=raw, **args)
    first_id = first["book"]["id"]
    library.save_reader_progress(first_id, .42)
    _, edited = prepare_book_upload("renamed.epub", raw, title="A different file-picker title")
    duplicate = library.import_epub(filename="renamed.epub", content=edited, **args)
    assert duplicate["already_present"] is True
    assert duplicate["book"]["id"] == first_id
    assert duplicate["book"]["reader_progress"] == .42
    assert library.list(limit=40, offset=0)["total"] == 1
    # A different user's library remains independent.
    other = BookLibrary(core, "tenant-b").import_epub(filename="book.epub", content=raw, **args)
    assert other["book"]["id"] != first_id


def test_readable_import_is_applied_even_when_optional_skill_processing_is_blocked(library_client, monkeypatch):
    _, core, _ = library_client
    def blocked(library, import_id):
        return {**library.detail(import_id), "status":"blocked", "error_code":"EPUB_SOURCE_ANCHOR_INVALID"}
    monkeypatch.setattr(BookLibrary, "materialize", blocked)
    service=KnowledgeSourceActionService(book_library_provider=lambda:BookLibrary(core,"tenant-a"))
    runtime=AppActionRuntime(knowledge_source_handler=service.execute)
    from agent.app_actions.models import AppActionRequest, AppActionContext
    receipt=runtime.dispatch(AppActionRequest(action_id="book.import",arguments={"file_name":"book.epub","_content":_epub_bytes()}),AppActionContext(source="ui"))
    assert receipt.status == "applied"
    assert receipt.result["library"]["book"]["can_read"] is True
    assert receipt.result["library"]["error_code"] == ""


def test_book_presentation_cover_is_local_and_keeps_original_epub_unchanged(library_client):
    client, core, _ = library_client
    library=BookLibrary(core,"tenant-a")
    result=library.import_epub(filename="book.epub",content=_epub_bytes(),rights_attestation_version="",scan_approved=False,local_only=True)
    book_id=result["book"]["id"]
    _, before=library._source(book_id)
    cover=BytesIO();Image.new("RGB",(267,400),"#222222").save(cover,format="JPEG")
    _, path, _=core.store.blobs.put_book_artifact(cover.getvalue(),tenant_scope=core.store.book_tenant_scope("tenant-a"),category="covers",suffix="jpg")
    core.store.set_book_presentation(user_id="tenant-a",import_id=book_id,values={"cover_blob_path":path,"cover_media_type":"image/jpeg"})
    response=client.get(f"/api/knowledge/core/books/library/{book_id}/cover")
    assert response.status_code==200 and response.content==cover.getvalue()
    assert library.detail(book_id)["book"]["cover_aspect"]==pytest.approx(267/400)
    _, after=library._source(book_id)
    assert before["sha256"]==after["sha256"]


def test_readable_epub_with_compressed_mimetype_is_normalized_instead_of_rejected():
    from zipfile import ZIP_DEFLATED
    from agent.knowledge.book_ingestion import validate_epub_archive, BookIngestionPolicy
    original=_epub_bytes()
    repacked=BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(repacked,"w",compression=ZIP_DEFLATED) as target:
        for info in reversed(source.infolist()):
            target.writestr(info.filename,source.read(info))
    _, normalized=prepare_book_upload("book.epub",repacked.getvalue())
    validate_epub_archive(normalized,BookIngestionPolicy())
    with ZipFile(BytesIO(original)) as source, ZipFile(BytesIO(normalized)) as target:
        assert target.read("OPS/chapter.xhtml")==source.read("OPS/chapter.xhtml")


def test_upload_returns_readable_book_before_background_skill_work_and_skips_work_for_duplicates(library_client, monkeypatch):
    import asyncio
    from fastapi import BackgroundTasks, UploadFile
    _, core, _ = library_client
    library=BookLibrary(core,"tenant-a")
    service=KnowledgeSourceActionService(book_library_provider=lambda:library)
    runtime=AppActionRuntime(knowledge_source_handler=service.execute)
    monkeypatch.setattr(action_api,"get_app_action_runtime",lambda:runtime)
    monkeypatch.setattr(action_api,"_book_library",lambda:library)
    calls=[];original=BookLibrary.materialize
    def processing(owner, import_id):
        calls.append(import_id)
        return original(owner,import_id)
    monkeypatch.setattr(BookLibrary,"materialize",processing)
    content=_epub_bytes()
    def upload(tasks):
        return asyncio.run(action_api.import_book_action(background_tasks=tasks,
            file=UploadFile(filename="book.epub",file=BytesIO(content))))
    tasks=BackgroundTasks();receipt=upload(tasks)
    book_id=receipt.result["library"]["book"]["id"]
    assert receipt.status=="applied" and receipt.result["library"]["processing_pending"] is True
    assert calls==[] and len(tasks.tasks)==1
    assert library.detail(book_id)["book"]["can_read"] is True
    assert library.reader_text(book_id).content
    assert core.store.status()["counts"]["book_documents"]==0
    asyncio.run(tasks())
    assert calls==[book_id]
    assert library.detail(book_id)["book"]["skill_status"]=="compiled"
    duplicate_tasks=BackgroundTasks();duplicate=upload(duplicate_tasks)
    assert duplicate.result["library"]["already_present"] is True
    assert duplicate_tasks.tasks==[] and calls==[book_id]


@pytest.mark.parametrize("url",["http://localhost:8000/private","https://127.0.0.1/book.txt","https://gutenberg.org.evil.example/book.txt","https://www.gutenberg.org@evil.example/book.txt"])
def test_book_url_import_rejects_non_provider_targets_without_network(url):
    with pytest.raises(ValueError,match="BOOK_URL_PROVIDER_UNSUPPORTED"):
        download_book_upload(url)
