from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.knowledge.book_ingestion import MalwareScanResult
from agent.knowledge.api import router as knowledge_core_router
from agent.knowledge.book_documents import BookDocumentError
from agent.knowledge.book_quality import BookQualityPipeline, EpubParseQualityPolicy
from agent.knowledge.models import (
    BookDocumentRequest,
    BookImportRequest,
    BookImportStatus,
    BookQualityRequest,
    ContextPackRequest,
)
from agent.knowledge.service import KnowledgeCore
from agent.knowledge.runtime import set_knowledge_core
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


def import_and_construct(
    core: KnowledgeCore,
    content: bytes,
    *,
    user_id: str = "user-1",
) -> tuple[BookImportStatus, BookImportStatus]:
    imported = core.import_book_epub(
        BookImportRequest(
            user_id=user_id,
            rights_attestation_version="local-epub-v1",
            scan_approved=True,
        ),
        content,
    )
    structured = core.construct_book_document(
        BookDocumentRequest(
            user_id=user_id,
            import_id=imported.import_id,
            run_id=imported.run_id,
        )
    )
    assert structured.document_id, structured.model_dump(mode="json")
    return imported, structured


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


def test_structured_epub_passes_the_current_quality_policy(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, structured_epub_bytes())

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    approved = core.get_book_document_for_materialization(
        user_id="user-1",
        document_id=structured.document_id,
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )
    pack = core.create_context_pack(
        ContextPackRequest(
            query="Truth needs evidence",
            purpose="specialist",
            destination="external",
            token_budget=512,
            source_kinds=["book", "book_document", "book_page", "book_skill"],
        )
    )

    assert assessed.status == "structured"
    assert assessed.quality_evaluated is True
    assert assessed.quality_outcome == "PASS"
    assert approved.document_id == structured.document_id
    assert approved.metadata.title == "Structured Fixture"
    assert quality.policy.version == "epub-parse-quality-v1"
    assert quality.policy.native_parser_version == "epub-native-v1"
    assert quality.policy.approved_alternate_parser_versions == ()
    assert quality.policy.ocr_trigger == "empty_native_spine_text"
    assert quality.policy.allowed_exclusion_codes == ("NOT_EXTRACTED_TEXT_RESOURCE",)
    assert quality.policy_snapshot_hash == quality.policy.snapshot_hash
    assert quality.parser_version == "epub-native-v1"
    assert quality.document_schema_version == "book-document-v1"
    safe_metadata = json.dumps(
        {
            "status": assessed.model_dump(mode="json"),
            "quality": quality.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    assert "Structured Fixture" not in safe_metadata
    assert "Truth needs evidence" not in safe_metadata
    assert str(tmp_path) not in safe_metadata
    assert pack["evidence"] == []


def test_empty_native_spine_content_requires_ocr_without_fabricating_text(tmp_path: Path) -> None:
    content = rewrite_zip_entries(
        structured_epub_bytes(),
        replacements={
            "OPS/chapter-two.xhtml": """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body id="second"><img src="lamp.jpg" alt=""/></body></html>""",
        },
    )
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, content)

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    document = core.get_book_document(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert structured.status == "structured"
    assert assessed.quality_evaluated is True
    assert assessed.quality_outcome == "OCR_REQUIRED"
    assert document.sections[1].blocks == []
    assert all("fabricated" not in block.text.casefold() for section in document.sections for block in section.blocks)
    with pytest.raises(ValueError, match="BOOK_QUALITY_NOT_PASSED"):
        core.get_book_document_for_materialization(
            user_id="user-1",
            document_id=structured.document_id,
        )


def test_duplicate_spine_content_is_degraded_and_not_eligible_for_materialization(
    tmp_path: Path,
) -> None:
    chapter = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
  <h1 id="{fragment}">Repeated chapter</h1>
  <p>The same chapter body appears twice.</p>
</body></html>"""
    content = rewrite_zip_entries(
        structured_epub_bytes(),
        replacements={
            "OPS/chapter-one.xhtml": chapter.format(fragment="first"),
            "OPS/chapter-two.xhtml": chapter.format(fragment="second"),
        },
    )
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, content)

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert assessed.quality_outcome == "DEGRADED"
    assert quality.finding_codes == ["EPUB_QUALITY_DUPLICATE_SPINE_CONTENT"]
    assert quality.metrics["duplicate_spine_items"] == 1
    with pytest.raises(ValueError, match="BOOK_QUALITY_NOT_PASSED"):
        core.get_book_document_for_materialization(
            user_id="user-1",
            document_id=structured.document_id,
        )


def test_missing_non_spine_resource_is_degraded(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(
        core,
        without_zip_entry(structured_epub_bytes(), "OPS/lamp.jpg"),
    )

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert assessed.quality_outcome == "DEGRADED"
    assert quality.finding_codes == ["EPUB_QUALITY_RESOURCE_MISSING"]
    assert quality.metrics["missing_resources"] == 1


def test_repeated_long_boilerplate_across_spine_items_is_degraded(tmp_path: Path) -> None:
    boilerplate = (
        "This publication notice is repeated across every chapter and contains enough text "
        "to distinguish substantial boilerplate from a short running label or heading."
    )
    chapter = """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<section id="{fragment}"><h1>{title}</h1><p>{boilerplate}</p></section>
</body></html>"""
    content = rewrite_zip_entries(
        structured_epub_bytes(),
        replacements={
            "OPS/chapter-one.xhtml": chapter.format(
                fragment="first",
                title="First unique chapter",
                boilerplate=boilerplate,
            ),
            "OPS/chapter-two.xhtml": chapter.format(
                fragment="second",
                title="Second unique chapter",
                boilerplate=boilerplate,
            ),
        },
    )
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, content)

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert assessed.quality_outcome == "DEGRADED"
    assert quality.finding_codes == ["EPUB_QUALITY_REPEATED_BOILERPLATE"]
    assert quality.metrics["repeated_boilerplate_blocks"] == 1


def test_quality_gate_is_exposed_through_the_existing_knowledge_core_api(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, structured_epub_bytes())
    app = FastAPI()
    app.include_router(knowledge_core_router, prefix="/api/knowledge")
    set_knowledge_core(core)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/knowledge/core/books/documents/{structured.document_id}/quality",
                json={
                    "user_id": "user-1",
                    "import_id": imported.import_id,
                    "run_id": imported.run_id,
                },
            )
            unauthorized = client.post(
                f"/api/knowledge/core/books/documents/{structured.document_id}/quality",
                json={
                    "user_id": "user-2",
                    "import_id": imported.import_id,
                    "run_id": imported.run_id,
                },
            )
    finally:
        set_knowledge_core(None)

    assert response.status_code == 200
    assert response.json()["quality_evaluated"] is True
    assert response.json()["quality_outcome"] == "PASS"
    assert unauthorized.status_code == 404
    assert unauthorized.json() == {"detail": {"code": "BOOK_DOCUMENT_NOT_FOUND"}}


def test_quality_evaluation_is_idempotent_under_concurrent_execution(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, structured_epub_bytes())
    request = BookQualityRequest(
        user_id="user-1",
        import_id=imported.import_id,
        run_id=imported.run_id,
        document_id=structured.document_id,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(core.evaluate_book_document_quality, [request, request]))

    assert [status.quality_outcome for status in statuses] == ["PASS", "PASS"]
    assert core.store.status()["counts"]["book_quality_assessments"] == 1


def test_quality_gate_binds_tenant_import_run_and_document(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, structured_epub_bytes())

    with pytest.raises(ValueError, match="BOOK_QUALITY_NOT_PASSED"):
        core.get_book_document_for_materialization(
            user_id="user-1",
            document_id=structured.document_id,
        )
    with pytest.raises(KeyError, match="Unknown structured BookDocument"):
        core.evaluate_book_document_quality(
            BookQualityRequest(
                user_id="user-2",
                import_id=imported.import_id,
                run_id=imported.run_id,
                document_id=structured.document_id,
            )
        )
    with pytest.raises(KeyError, match="Unknown structured BookDocument"):
        core.evaluate_book_document_quality(
            BookQualityRequest(
                user_id="user-1",
                import_id=imported.import_id,
                run_id="wrong-run",
                document_id=structured.document_id,
            )
        )
    with pytest.raises(KeyError, match="Unknown BookDocument"):
        core.get_book_document_for_materialization(
            user_id="user-2",
            document_id=structured.document_id,
        )


def test_quality_policy_upgrade_retains_the_prior_assessment(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(
        core,
        without_zip_entry(structured_epub_bytes(), "OPS/lamp.jpg"),
    )
    request = BookQualityRequest(
        user_id="user-1",
        import_id=imported.import_id,
        run_id=imported.run_id,
        document_id=structured.document_id,
    )
    first_status = core.evaluate_book_document_quality(request)
    first = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )
    upgraded = BookQualityPipeline(
        core.store,
        core.book_documents,
        policy=EpubParseQualityPolicy(
            version="epub-parse-quality-v2",
            require_declared_resources=False,
        ),
    )

    second_status = upgraded.evaluate(request)
    second = upgraded.load_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    restored_status = core.evaluate_book_document_quality(request)

    assert first_status.quality_outcome == "DEGRADED"
    assert second_status.quality_outcome == "PASS"
    assert restored_status.quality_outcome == "DEGRADED"
    assert first.policy_version == "epub-parse-quality-v1"
    assert second.policy_version == "epub-parse-quality-v2"
    assert first.assessment_id != second.assessment_id
    assert core.store.status()["counts"]["book_quality_assessments"] == 2


def test_quality_evaluation_rejects_a_document_digest_mismatch(tmp_path: Path) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, structured_epub_bytes())
    with sqlite3.connect(core.store.db_path) as connection:
        connection.execute(
            "UPDATE book_documents SET digest = ? WHERE id = ?",
            ("0" * 64, structured.document_id),
        )

    with pytest.raises(BookDocumentError, match="BOOK_DOCUMENT_DIGEST_MISMATCH"):
        core.evaluate_book_document_quality(
            BookQualityRequest(
                user_id="user-1",
                import_id=imported.import_id,
                run_id=imported.run_id,
                document_id=structured.document_id,
            )
        )


def test_quality_gate_fails_impossible_spine_accounting_and_invalid_offsets(
    tmp_path: Path,
) -> None:
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, structured_epub_bytes())
    document = core.get_book_document(user_id="user-1", document_id=structured.document_id)
    first_section = document.sections[0]
    first_block = first_section.blocks[0]
    invalid_anchor = first_block.anchor.model_copy(
        update={
            "block_fingerprint": "0" * 64,
            "normalized_end": first_block.anchor.normalized_start,
        },
    )
    invalid_block = first_block.model_copy(update={"anchor": invalid_anchor})
    invalid_section = first_section.model_copy(
        update={"blocks": [invalid_block, *first_section.blocks[1:]]},
    )
    invalid_quality = document.quality_report.model_copy(
        update={
            "navigation_targets_total": document.quality_report.navigation_targets_total - 1,
            "spine_items_accounted": document.quality_report.spine_items_total - 1,
            "text_characters": document.quality_report.text_characters - 1,
        },
    )
    invalid_document = document.model_copy(
        update={
            "sections": [invalid_section, *document.sections[1:]],
            "quality_report": invalid_quality,
        },
    )
    payload = json.dumps(
        invalid_document.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest, blob_path, _ = core.store.blobs.put_book_artifact(
        payload,
        tenant_scope=core.store.book_tenant_scope("user-1"),
        category="documents",
        suffix="json",
    )
    with sqlite3.connect(core.store.db_path) as connection:
        connection.execute(
            "UPDATE book_documents SET digest = ?, blob_path = ? WHERE id = ?",
            (digest, blob_path, structured.document_id),
        )

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert assessed.quality_outcome == "FAILED_PERMANENT"
    assert quality.finding_codes == [
        "EPUB_QUALITY_ANCHOR_INVALID",
        "EPUB_QUALITY_NAVIGATION_INVALID",
        "EPUB_QUALITY_SPINE_INCOMPLETE",
        "EPUB_QUALITY_TEXT_ACCOUNTING_INVALID",
    ]


def test_encoding_replacement_characters_are_degraded(tmp_path: Path) -> None:
    content = rewrite_zip_entries(
        structured_epub_bytes(),
        replacements={
            "OPS/chapter-one.xhtml": """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<section id="first"><h1>Opening</h1><p>Damaged text &#xfffd; &#xfffd; remains attributable.</p></section>
</body></html>""",
        },
    )
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, content)

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert assessed.quality_outcome == "DEGRADED"
    assert quality.finding_codes == ["EPUB_QUALITY_ENCODING_CORRUPTION"]
    assert quality.metrics["encoding_replacement_characters"] == 2


def test_orphan_caption_fails_typed_structure_validation(tmp_path: Path) -> None:
    content = rewrite_zip_entries(
        structured_epub_bytes(),
        replacements={
            "OPS/chapter-one.xhtml": """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<section id="first"><h1>Opening</h1><figcaption>Orphan caption</figcaption>
<p>Body text remains available.</p></section></body></html>""",
        },
    )
    core = build_core(tmp_path)
    imported, structured = import_and_construct(core, content)

    assessed = core.evaluate_book_document_quality(
        BookQualityRequest(
            user_id="user-1",
            import_id=imported.import_id,
            run_id=imported.run_id,
            document_id=structured.document_id,
        )
    )
    quality = core.get_book_quality_assessment(
        user_id="user-1",
        document_id=structured.document_id,
    )

    assert assessed.quality_outcome == "FAILED_PERMANENT"
    assert quality.finding_codes == ["EPUB_QUALITY_CAPTION_RELATION_INVALID"]


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

    assert statuses[0].document_id == statuses[1].document_id, [
        status.model_dump(mode="json")
        for status in statuses
    ]
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
