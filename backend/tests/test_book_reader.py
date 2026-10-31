from io import BytesIO
import json
from zipfile import ZipFile

from agent.knowledge.models import BookImportRequest
from test_book_library_api import _epub_bytes, _cover_png, library_client


def _rewrite(content, replacements, additions=None):
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, replacements.get(info.filename, source.read(info)))
        for name, data in (additions or {}).items():
            target.writestr(name, data)
    return output.getvalue()


def _validated(core, content):
    return core.import_book_epub(BookImportRequest(user_id="tenant-a", scan_approved=True,
        rights_attestation_version="local-epub-v1", local_only=True), content)


def test_numeric_isbn_title_uses_internal_book_title_in_library_and_reader(library_client):
    client, core, _ = library_client
    raw = _epub_bytes()
    with ZipFile(BytesIO(raw)) as archive:
        package = archive.read("OPS/package.opf").decode().replace("Library Fixture", "9781524704551")
    chapter = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ikigai</title></head><body><h1>Chapter One</h1><p>Complete book text.</p></body></html>'
    imported = _validated(core, _rewrite(raw, {"OPS/package.opf": package, "OPS/chapter.xhtml": chapter}))
    url = f"/api/knowledge/core/books/library/{imported.import_id}"
    assert client.get(url).json()["book"]["title"] == "Ikigai"
    assert client.get(url + "/reader").json()["title"] == "Ikigai"


def test_standard_xhtml_doctype_and_nested_blocks_remain_readable_and_source_anchored(library_client):
    from agent.knowledge.models import BookDocumentRequest
    client, core, _ = library_client
    chapter = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Complete book</title></head><body>
<h1>Chapter One</h1><ul><li>Outer list<ul><li>Inner list</li></ul></li><li>Next item</li></ul>
<blockquote>Outer quotation<blockquote>Inner quotation</blockquote></blockquote><blockquote>Next quotation</blockquote>
<p>A complete paragraph with&nbsp;ordinary EPUB entities.</p></body></html>'''
    status = _validated(core, _rewrite(_epub_bytes(), {"OPS/chapter.xhtml": chapter}))
    result = core.construct_book_document(BookDocumentRequest(user_id="tenant-a", import_id=status.import_id, run_id=status.run_id))
    assert not result.error_code
    document = core.get_book_document(user_id="tenant-a", document_id=result.document_id)
    assert any("Outer list" in b.text for s in document.sections for b in s.blocks)
    full = client.get(f"/api/knowledge/core/books/library/{status.import_id}/reader/full")
    assert full.status_code == 200
    assert "Next quotation" in full.json()["content"]


def test_reader_serves_all_spine_sections_without_skill_compilation(library_client):
    client, core, _ = library_client
    raw = _epub_bytes()
    with ZipFile(BytesIO(raw)) as archive:
        package = archive.read("OPS/package.opf").decode()
    package = package.replace('</manifest>', '<item id="last" href="last.xhtml" media-type="application/xhtml+xml"/></manifest>')
    package = package.replace('</spine>', '<itemref idref="last" linear="no"/></spine>')
    last_text = "Unabridged text. " * 5000 + "THE FINAL SENTENCE."
    raw = _rewrite(raw, {"OPS/package.opf":package}, {"OPS/last.xhtml":f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Appendix</h1><p>{last_text}</p></body></html>'})
    imported = _validated(core, raw)
    url = f"/api/knowledge/core/books/library/{imported.import_id}/reader"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    manifest = response.json()
    assert manifest["schema_version"] == "books-reader-v1"
    assert [item["title"] for item in manifest["sections"]] == ["Chapter One", "Appendix"]
    assert "resource_path" not in json.dumps(manifest)
    assert "blob_path" not in json.dumps(manifest)
    final = client.get(url + "/" + manifest["sections"][-1]["id"])
    assert final.status_code == 200
    assert last_text in final.json()["html"]
    assert final.headers["cache-control"] == "private, no-store"
    assert core.store.status()["counts"]["book_materializations"] == 0
    assert client.get(f"/api/knowledge/core/books/library/{imported.import_id}").json()["book"]["can_read"] is True


def test_reader_removes_active_content_and_embeds_only_valid_local_images(library_client):
    client, core, _ = library_client
    chapter = '''<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Safe chapter</h1>
      <p onclick="steal()">All readable text <em>survives</em>.</p>
      <script>steal()</script><style>body{display:none}</style><iframe src="https://evil.example"/>
      <a href="javascript:steal()">Unsafe link text</a><a href="#note">Footnote</a>
      <img src="https://evil.example/tracker" alt="Remote image"/><img src="images/cover.png" alt="Local image"/>
      <svg><foreignObject><script>steal()</script></foreignObject></svg>
      <p id="note">Final footnote.</p></body></html>'''
    imported = _validated(core, _rewrite(_epub_bytes(cover=_cover_png()), {"OPS/chapter.xhtml":chapter}))
    url = f"/api/knowledge/core/books/library/{imported.import_id}/reader"
    manifest = client.get(url).json()
    rendered = client.get(url + "/" + manifest["sections"][0]["id"]).json()["html"]
    for forbidden in ("<script", "<iframe", "<style", "onclick", "javascript:", "https://evil.example", "foreignObject"):
        assert forbidden not in rendered
    assert 'href="#note"' in rendered
    assert "All readable text <em>survives</em>." in rendered
    assert "data:image/png;base64," in rendered
    assert "Final footnote." in rendered


def test_reader_checks_tenant_scan_and_asset_integrity(library_client, monkeypatch):
    from types import SimpleNamespace
    from agent.knowledge import api
    client, core, _ = library_client
    imported = _validated(core, _epub_bytes())
    url = f"/api/knowledge/core/books/library/{imported.import_id}/reader"
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(honcho_user_id="tenant-b"))
    assert client.get(url).status_code == 404
    monkeypatch.setattr(api, "get_settings", lambda: SimpleNamespace(honcho_user_id="tenant-a"))
    manifest = client.get(url).json()
    assert client.get(url + "/not-a-section").status_code == 404
    from agent.knowledge.book_ingestion import UnavailableMalwareScanner
    core.book_ingestion.scanner = UnavailableMalwareScanner()
    pending = _validated(core, _rewrite(_epub_bytes(), {"OPS/chapter.xhtml":'<html><body><p>Not scanned</p></body></html>'}))
    assert client.get(f"/api/knowledge/core/books/library/{pending.import_id}/reader").status_code == 409
    asset = core.store.get_book_library_asset(user_id="tenant-a", import_id=imported.import_id, run_id=imported.run_id)
    core.store.blobs.resolve(asset["blob_path"]).write_bytes(b"changed after validation")
    assert client.get(url).status_code == 409
    assert client.get(url + "/" + manifest["sections"][0]["id"]).status_code == 409
