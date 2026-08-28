from __future__ import annotations

from base64 import b64decode
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_STORED, ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent.knowledge import api as knowledge_api
from agent.knowledge.book_ingestion import MalwareScanResult
from agent.knowledge.models import BookImportRequest
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


class FixedBookEmbedder:
    model_name = "test-book-embedding-v1"

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1), float(len(text))] for index, text in enumerate(texts)]


class RecordingBookIndex:
    collection_name = "test-books"

    def __init__(self) -> None:
        self.points: dict[tuple[str, str], dict[str, object]] = {}

    def upsert(self, **kwargs: object) -> str:
        materialization_id = str(kwargs["materialization_id"])
        chunk_id = str(kwargs["chunk_id"])
        point_id = f"point-{materialization_id}-{chunk_id}"
        self.points[(materialization_id, chunk_id)] = dict(kwargs)
        return point_id

    def delete_materialization(self, *, user_id: str, materialization_id: str) -> None:
        _ = user_id
        for key in list(self.points):
            if key[0] == materialization_id:
                del self.points[key]


def _cover_png() -> bytes:
    return b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _epub_bytes(*, cover: bytes | None = None) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        )
        cover_item = (
            '<item id="cover-image" href="images/cover.png" media-type="image/png" properties="cover-image"/>'
            if cover is not None
            else ""
        )
        archive.writestr(
            "OPS/package.opf",
            f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Library Fixture</dc:title>
    <dc:creator>Example Author</dc:creator>
  </metadata>
  <manifest>
    {cover_item}
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>""",
        )
        archive.writestr(
            "OPS/chapter.xhtml",
            "<html xmlns=\"http://www.w3.org/1999/xhtml\"><body>"
            "<h1>Chapter One</h1><p>Fixture source text.</p></body></html>",
        )
        if cover is not None:
            archive.writestr("OPS/images/cover.png", cover)
    return output.getvalue()


@pytest.fixture
def library_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    conversations = tmp_path / "data" / "ui" / "conversations.json"
    conversations.parent.mkdir(parents=True)
    conversations.write_text("[]", encoding="utf-8")
    core = KnowledgeCore(
        KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs"),
        conversations_path=conversations,
        vault_root=tmp_path / "Vault",
        book_malware_scanner=CleanScanner(),
        book_embedding_provider=FixedBookEmbedder(),
        book_retrieval_index=RecordingBookIndex(),
    )
    monkeypatch.setattr(knowledge_api, "get_settings", lambda: SimpleNamespace(honcho_user_id="tenant-a"))
    set_knowledge_core(core)
    app = FastAPI()
    app.include_router(knowledge_api.router, prefix="/api/knowledge")
    try:
        with TestClient(app) as client:
            yield client, core, tmp_path
    finally:
        set_knowledge_core(None)


def _import(client: TestClient, content: bytes | None = None) -> dict:
    response = client.post(
        "/api/knowledge/core/books/library/import",
        data={
            "rights_attestation_version": "local-epub-v1",
            "scan_approved": "true",
            "local_only": "true",
        },
        files={"file": ("fixture.epub", content or _epub_bytes(cover=_cover_png()), "application/epub+zip")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_library_import_process_detail_and_cover_are_metadata_only(library_client) -> None:
    client, _core, tmp_path = library_client
    imported = _import(client)
    book_id = imported["book"]["id"]
    assert imported["book"]["state"] == "validated"
    assert imported["book"]["local_only"] is True
    assert imported["book"]["can_process"] is True
    assert imported["book"]["can_compile"] is False
    assert imported["book"]["cover_url"].endswith(f"/{book_id}/cover")

    processed = client.post(f"/api/knowledge/core/books/library/{book_id}/process", json={"confirm": True})
    assert processed.status_code == 200, processed.text
    assert processed.json()["book"]["title"] == "Library Fixture"
    assert processed.json()["book"]["authors"] == ["Example Author"]
    assert processed.json()["book"]["can_compile"] is True

    detail = client.get(f"/api/knowledge/core/books/library/{book_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["book"]["sections"]
    assert payload["book"]["sections"][0]["block_count"] == 2
    serialized = json.dumps(payload, sort_keys=True)
    assert "resource_path" not in serialized
    assert "blob_path" not in serialized
    assert "Fixture source text" not in serialized
    assert str(tmp_path) not in serialized

    cover = client.get(f"/api/knowledge/core/books/library/{book_id}/cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/png"
    assert cover.content == _cover_png()


def test_library_tenant_isolation_and_duplicate_assets(library_client) -> None:
    client, core, _tmp_path = library_client
    content = _epub_bytes()
    first = _import(client, content)
    second = _import(client, content)
    assert second["book"]["id"] == first["book"]["id"]
    assert core.store.status()["counts"]["book_assets"] == 1
    assert core.store.status()["counts"]["user_book_imports"] == 1

    other = core.import_book_epub(
        BookImportRequest(
            user_id="tenant-b",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        content,
    )
    assert client.get(f"/api/knowledge/core/books/library/{other.import_id}").status_code == 404
    listed = client.get("/api/knowledge/core/books/library").json()
    assert listed["total"] == 1
    assert [item["id"] for item in listed["items"]] == [first["book"]["id"]]


def test_library_actions_enforce_quality_and_real_compile_capability(library_client) -> None:
    client, core, _tmp_path = library_client
    book_id = _import(client)["book"]["id"]

    early_compile = client.post(f"/api/knowledge/core/books/library/{book_id}/compile", json={"confirm": True})
    assert early_compile.status_code == 200
    assert early_compile.json()["error_code"] == "BOOK_COMPILE_NOT_ELIGIBLE"
    assert core.store.status()["counts"]["book_materializations"] == 0

    client.post(f"/api/knowledge/core/books/library/{book_id}/process", json={"confirm": True})
    compiled = client.post(f"/api/knowledge/core/books/library/{book_id}/compile", json={"confirm": True})
    assert compiled.status_code == 200, compiled.text
    assert compiled.json()["status"] == "ready"
    assert compiled.json()["book"]["skill_status"] == "compiled"
    assert "installed" not in json.dumps(compiled.json()["book"]).casefold()

    core.materialize_book_document = None
    unsupported = client.post(f"/api/knowledge/core/books/library/{book_id}/compile", json={"confirm": True})
    assert unsupported.status_code == 200
    assert unsupported.json()["status"] == "unsupported"
    assert unsupported.json()["error_code"] == "BOOK_COMPILE_UNSUPPORTED"
    assert unsupported.json()["book"]["can_compile"] is False


def test_library_missing_book_and_cover_are_content_free(library_client) -> None:
    client, _core, tmp_path = library_client
    missing = "bki_missing"
    response = client.get(f"/api/knowledge/core/books/library/{missing}")
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "BOOK_NOT_FOUND"}
    action = client.post(f"/api/knowledge/core/books/library/{missing}/process", json={"confirm": True})
    assert action.status_code == 404
    assert action.json()["detail"] == {"code": "BOOK_NOT_FOUND"}

    imported = _import(client, _epub_bytes())
    cover = client.get(f"/api/knowledge/core/books/library/{imported['book']['id']}/cover")
    assert cover.status_code == 404
    assert cover.json()["detail"] == {"code": "BOOK_COVER_UNAVAILABLE"}
    assert str(tmp_path) not in cover.text


def test_library_requires_explicit_approvals_and_bounds_pagination(library_client) -> None:
    client, core, _ = library_client
    for fields in [
        {"scan_approved": "false", "rights_attestation_version": "local-epub-v1"},
        {"scan_approved": "true", "rights_attestation_version": "old-policy"},
    ]:
        response = client.post("/api/knowledge/core/books/library/import", data=fields,
                               files={"file": ("fixture.epub", _epub_bytes())})
        assert response.status_code == 409
    assert core.store.status()["counts"]["user_book_imports"] == 0
    book_id = _import(client)["book"]["id"]
    for payload, expected in [({"confirm": False}, 409), ({"confirm": "true"}, 422),
                              ({"confirm": True, "user_id": "tenant-b"}, 422)]:
        assert client.post(f"/api/knowledge/core/books/library/{book_id}/process", json=payload).status_code == expected
    assert client.get("/api/knowledge/core/books/library?limit=100000").status_code == 422
    assert client.get("/api/knowledge/core/books/library?offset=-1").status_code == 422
    page = client.get("/api/knowledge/core/books/library?offset=1&user_id=tenant-b").json()
    assert page["items"] == [] and page["total"] == 1
    assert page["rights_attestation_version"] == "local-epub-v1"


def test_cover_rejects_non_image_content_and_unscanned_assets(library_client) -> None:
    client, core, _ = library_client
    imported = _import(client, _epub_bytes(cover=b"not a PNG"))
    assert client.get(f"/api/knowledge/core/books/library/{imported['book']['id']}/cover").status_code == 404

    from agent.knowledge.book_ingestion import UnavailableMalwareScanner
    core.book_ingestion.scanner = UnavailableMalwareScanner()
    unscanned = _import(client, _epub_bytes())
    assert unscanned["book"]["state"] == "failed_retryable"
    assert unscanned["book"]["cover_url"] == ""
    assert unscanned["book"]["can_process"] is False
    assert unscanned["book"]["can_compile"] is False
    assert client.get(f"/api/knowledge/core/books/library/{unscanned['book']['id']}/cover").status_code == 404


def test_compile_failure_does_not_leak_exception_or_claim_a_skill(library_client) -> None:
    client, core, tmp_path = library_client
    book_id = _import(client)["book"]["id"]
    client.post(f"/api/knowledge/core/books/library/{book_id}/process", json={"confirm": True})

    def fail(_request):
        raise RuntimeError(f"private processing path {tmp_path}")

    core.materialize_book_document = fail
    response = client.post(f"/api/knowledge/core/books/library/{book_id}/compile", json={"confirm": True})
    assert response.json()["error_code"] == "BOOK_COMPILE_FAILED"
    assert response.json()["book"]["skill_status"] == "not_compiled"
    assert str(tmp_path) not in response.text


@pytest.mark.parametrize("same_content", [True, False])
def test_concurrent_artifact_publication_accepts_only_identical_bytes(tmp_path, monkeypatch, same_content):
    from agent.knowledge import store
    blobs = store.BlobStore(tmp_path)

    def competing_writer(_source, target):
        target.write_bytes(b"same content" if same_content else b"different content")
        raise PermissionError("Windows target is open")

    monkeypatch.setattr(store.os, "replace", competing_writer)
    if same_content:
        blobs.put_book_artifact(b"same content", tenant_scope="test_user", category="quality", suffix="json")
    else:
        with pytest.raises(PermissionError):
            blobs.put_book_artifact(b"same content", tenant_scope="test_user", category="quality", suffix="json")
