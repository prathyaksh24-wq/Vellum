from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import zipfile

import pytest

from agent.knowledge.book_ingestion import MalwareScanResult
from agent.knowledge.models import BookDocumentRequest, BookImportRequest, ContextPackRequest
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


def build_core(tmp_path: Path) -> KnowledgeCore:
    conversations = tmp_path / "data" / "ui" / "conversations.json"
    conversations.parent.mkdir(parents=True)
    conversations.write_text("[]", encoding="utf-8")
    vault = tmp_path / "Vault"
    vault.mkdir()
    return KnowledgeCore(
        KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs"),
        conversations_path=conversations,
        vault_root=vault,
        book_malware_scanner=CleanScanner(),
    )


def structured_epub_bytes() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        )
        archive.writestr(
            "OPS/chapter-two.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<section id="second"><h2>Second</h2><blockquote>Question assumptions.</blockquote>
<ul><li>Keep evidence attached.</li></ul></section></body></html>""",
        )
        archive.writestr(
            "OPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol>
<li><a href="chapter-one.xhtml#first">Opening</a></li>
<li><a href="chapter-two.xhtml#second">Second</a></li>
</ol></nav></body></html>""",
        )
        archive.writestr(
            "OPS/chapter-one.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<section id="first"><h1 data-epub-cfi="epubcfi(/6/2[one])">Opening</h1>
<p>Truth   needs
 evidence.</p><figure><img src="lamp.jpg" alt="A lamp"/><figcaption>Light</figcaption></figure>
</section></body></html>""",
        )
        archive.writestr("OPS/lamp.jpg", b"\xff\xd8\xff\xe0test-image")
        archive.writestr(
            "OPS/package.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:test:structured</dc:identifier>
    <dc:title>Structured Fixture</dc:title>
    <dc:creator>Example Author</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="two" href="chapter-two.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="one" href="chapter-one.xhtml" media-type="application/xhtml+xml"/>
    <item id="lamp" href="lamp.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine><itemref idref="one"/><itemref idref="two"/></spine>
</package>""",
        )
    return output.getvalue()


def without_zip_entry(content: bytes, removed_name: str) -> bytes:
    source = BytesIO(content)
    output = BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w") as rewritten:
        for info in original.infolist():
            if info.filename != removed_name:
                rewritten.writestr(info, original.read(info.filename))
    return output.getvalue()


def rewrite_zip_entries(
    content: bytes,
    *,
    replacements: dict[str, str],
    removed: set[str] | None = None,
) -> bytes:
    removed = removed or set()
    source = BytesIO(content)
    output = BytesIO()
    written: set[str] = set()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w") as rewritten:
        for info in original.infolist():
            if info.filename in removed:
                continue
            payload = replacements.get(info.filename)
            rewritten.writestr(
                info,
                payload.encode("utf-8") if payload is not None else original.read(info.filename),
            )
            written.add(info.filename)
        for name, payload in replacements.items():
            if name not in written:
                rewritten.writestr(name, payload)
    return output.getvalue()


def test_validated_epub_builds_canonical_source_anchored_document(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported = core.import_book_epub(
        BookImportRequest(
            user_id="user-1",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        structured_epub_bytes(),
    )

    status = core.construct_book_document(
        BookDocumentRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
        )
    )
    document = core.get_book_document(user_id="user-1", document_id=status.document_id)

    assert status.status == "structured"
    assert status.current_stage == "structured"
    assert status.quality_outcome == ""
    assert status.quality_evaluated is False
    assert [receipt.stage for receipt in status.receipts] == [
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
    ]
    assert document.metadata.title == "Structured Fixture"
    assert document.metadata.creators == ["Example Author"]
    assert document.metadata.languages == ["en"]
    assert [item.resource_path for item in document.reading_order] == [
        "OPS/chapter-one.xhtml",
        "OPS/chapter-two.xhtml",
    ]
    assert [item.label for item in document.navigation] == ["Opening", "Second"]
    blocks = [block for section in document.sections for block in section.blocks]
    assert [block.type for block in blocks] == [
        "heading",
        "paragraph",
        "figure",
        "caption",
        "heading",
        "quotation",
        "list_item",
    ]
    assert blocks[0].anchor.epub_cfi == "epubcfi(/6/2[one])"
    assert blocks[1].text == "Truth needs evidence."
    assert blocks[1].anchor.resource_path == "OPS/chapter-one.xhtml"
    assert blocks[1].anchor.source_element == "p"
    assert blocks[1].anchor.normalized_end > blocks[1].anchor.normalized_start
    assert blocks[1].anchor.source_start < blocks[1].anchor.offset_map[0][2]
    assert blocks[1].anchor.source_end > blocks[1].anchor.offset_map[-1][3]
    assert blocks[1].anchor.offset_map[0][0] == blocks[1].anchor.normalized_start
    assert blocks[1].anchor.offset_map[-1][1] == blocks[1].anchor.normalized_end
    assert any(
        normalized_end - normalized_start < source_end - source_start
        for normalized_start, normalized_end, source_start, source_end in blocks[1].anchor.offset_map
    )
    assert blocks[1].anchor.block_fingerprint
    assert document.normalizer_version == "book-normalizer-v1"
    assert document.quality_report.outcome is None
    assert document.quality_report.evaluated is False
    assert document.quality_report.spine_items_total == 2
    assert document.quality_report.spine_items_accounted == 2
    assert document.quality_report.navigation_targets_unresolved == 0
    assert document.quality_report.block_count == 7
    lamp = next(resource for resource in document.resources if resource.manifest_id == "lamp")
    assert lamp.disposition == "excluded"
    assert lamp.exclusion_code == "NOT_EXTRACTED_TEXT_RESOURCE"
    assert lamp.source_sha256
    assert document.quality_report.exclusions == ["lamp:NOT_EXTRACTED_TEXT_RESOURCE"]
    assert not hasattr(blocks[0].anchor, "printed_page")

    serialized_status = json.dumps(status.model_dump(mode="json"), sort_keys=True)
    assert "Structured Fixture" not in serialized_status
    assert "Truth needs evidence" not in serialized_status
    assert str(tmp_path) not in serialized_status
    counts = core.store.status()["counts"]
    assert counts["book_documents"] == 1
    assert counts["book_document_resources"] == 4
    pack = core.create_context_pack(
        ContextPackRequest(
            query="Truth needs evidence",
            purpose="specialist",
            destination="external",
            token_budget=512,
            source_kinds=["book", "book_document", "book_page", "book_skill"],
        )
    )
    assert pack["evidence"] == []


def test_book_document_construction_is_idempotent_and_tenant_scoped(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported = core.import_book_epub(
        BookImportRequest(
            user_id="user-1",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        structured_epub_bytes(),
    )
    request = BookDocumentRequest(
        user_id="user-1",
        import_id=imported.import_id,
        run_id=imported.run_id,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(core.construct_book_document, [request, request]))

    assert statuses[0].document_id == statuses[1].document_id
    assert [receipt.stage for receipt in statuses[0].receipts] == [
        "received",
        "quarantined",
        "validated",
        "extracted",
        "identified",
        "structured",
    ]
    counts = core.store.status()["counts"]
    assert counts["book_documents"] == 1
    assert counts["book_document_resources"] == 4
    with pytest.raises(KeyError, match="Unknown BookDocument"):
        core.get_book_document(
            user_id="user-2",
            document_id=statuses[0].document_id,
        )
    with pytest.raises(KeyError, match="Unknown Book import"):
        core.construct_book_document(
            BookDocumentRequest(
                user_id="user-2",
                import_id=imported.import_id,
                run_id=imported.run_id,
            )
        )


def test_missing_spine_resource_fails_without_publishing_partial_document(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported = core.import_book_epub(
        BookImportRequest(
            user_id="user-1",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        without_zip_entry(structured_epub_bytes(), "OPS/chapter-two.xhtml"),
    )

    status = core.construct_book_document(
        BookDocumentRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
        )
    )

    assert status.status == "failed_permanent"
    assert status.current_stage == "extracted"
    assert status.error_code == "EPUB_SPINE_RESOURCE_MISSING"
    assert status.document_id == ""
    assert status.receipts[-1].stage == "extracted"
    assert status.receipts[-1].status == "failed_permanent"
    counts = core.store.status()["counts"]
    assert counts["book_documents"] == 0
    assert counts["book_document_resources"] == 0


@pytest.mark.parametrize(("navigation_kind", "expected_labels"), [
    ("inferred", ["Opening", "Second"]),
    ("ncx", ["NCX Opening", "NCX Second"]),
])
def test_navigation_fallbacks_are_deterministic(
    tmp_path: Path,
    navigation_kind: str,
    expected_labels: list[str],
) -> None:
    package = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="book-id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:test:fallback</dc:identifier>
    <dc:title>Fallback Fixture</dc:title><dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="one" href="chapter-one.xhtml" media-type="application/xhtml+xml"/>
    <item id="two" href="chapter-two.xhtml" media-type="application/xhtml+xml"/>
    {ncx_manifest}
  </manifest>
  <spine{toc}><itemref idref="one"/><itemref idref="two"/></spine>
</package>""".format(
        ncx_manifest=(
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            if navigation_kind == "ncx"
            else ""
        ),
        toc=' toc="ncx"' if navigation_kind == "ncx" else "",
    )
    replacements = {"OPS/package.opf": package}
    if navigation_kind == "ncx":
        replacements["OPS/toc.ncx"] = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
  <navPoint id="one"><navLabel><text>NCX Opening</text></navLabel><content src="chapter-one.xhtml#first"/></navPoint>
  <navPoint id="two"><navLabel><text>NCX Second</text></navLabel><content src="chapter-two.xhtml#second"/></navPoint>
</navMap></ncx>"""
    content = rewrite_zip_entries(
        structured_epub_bytes(),
        replacements=replacements,
        removed={"OPS/nav.xhtml"},
    )
    core = build_core(tmp_path)
    imported = core.import_book_epub(
        BookImportRequest(
            user_id="user-1",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        content,
    )

    status = core.construct_book_document(
        BookDocumentRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
        )
    )
    document = core.get_book_document(user_id="user-1", document_id=status.document_id)

    assert document.quality_report.navigation_source == navigation_kind
    assert [item.label for item in document.navigation] == expected_labels


def test_publication_failure_rolls_back_all_visible_document_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = build_core(tmp_path)
    imported = core.import_book_epub(
        BookImportRequest(
            user_id="user-1",
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        structured_epub_bytes(),
    )

    def fail_receipt(*_args, **_kwargs) -> None:
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(core.store, "_record_book_receipt", fail_receipt)
    with pytest.raises(RuntimeError, match="injected publication failure"):
        core.construct_book_document(
            BookDocumentRequest(
                user_id="user-1",
                import_id=imported.import_id,
                run_id=imported.run_id,
            )
        )

    counts = core.store.status()["counts"]
    assert counts["book_documents"] == 0
    assert counts["book_document_resources"] == 0
    status = core.get_book_ingestion_status(
        user_id="user-1",
        import_id=imported.import_id,
        run_id=imported.run_id,
    )
    assert status.status == "validated"
    assert [receipt.stage for receipt in status.receipts] == [
        "received",
        "quarantined",
        "validated",
    ]
