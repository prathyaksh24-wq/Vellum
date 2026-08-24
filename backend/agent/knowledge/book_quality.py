"""Versioned quality assessment for canonical EPUB BookDocuments."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.knowledge.book_documents import (
    BookDocument,
    BookDocumentPipeline,
    BookNavigationItem,
)
from agent.knowledge.models import BookImportStatus, BookQualityRequest
from agent.knowledge.store import BookQualityAssessmentPublication, KnowledgeStore


BOOK_QUALITY_ASSESSMENT_SCHEMA_VERSION = "book-quality-assessment-v1"


class BookQualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EpubParseQualityPolicy(BookQualityModel):
    version: str = Field(
        default="epub-parse-quality-v1",
        pattern=r"^[A-Za-z0-9._-]{1,120}$",
    )
    native_parser_version: str = "epub-native-v1"
    approved_alternate_parser_versions: tuple[str, ...] = ()
    ocr_trigger: Literal["empty_native_spine_text"] = "empty_native_spine_text"
    allowed_exclusion_codes: tuple[str, ...] = ("NOT_EXTRACTED_TEXT_RESOURCE",)
    require_complete_spine: bool = True
    require_resolved_navigation: bool = True
    require_valid_anchors: bool = True
    require_native_text_per_spine_item: bool = True
    reject_duplicate_spine_content: bool = True
    require_declared_resources: bool = True
    repeated_boilerplate_min_characters: int = Field(default=80, ge=1)
    repeated_boilerplate_min_occurrences: int = Field(default=2, ge=2)
    max_encoding_replacement_characters: int = Field(default=0, ge=0)
    require_caption_figure_relationship: bool = True

    @property
    def snapshot_hash(self) -> str:
        return sha256(_canonical_json(self.model_dump(mode="json"))).hexdigest()


class BookQualityAssessment(BookQualityModel):
    schema_version: str = BOOK_QUALITY_ASSESSMENT_SCHEMA_VERSION
    assessment_id: str
    document_id: str
    document_digest: str
    document_schema_version: str
    parser_version: str
    normalizer_version: str
    policy: EpubParseQualityPolicy
    policy_version: str
    policy_snapshot_hash: str
    outcome: Literal[
        "PASS",
        "DEGRADED",
        "OCR_REQUIRED",
        "FAILED_RETRYABLE",
        "FAILED_PERMANENT",
    ]
    finding_codes: list[str] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)


class BookQualityPipeline:
    """Evaluate immutable BookDocuments and expose the PASS-only handoff."""

    def __init__(
        self,
        store: KnowledgeStore,
        documents: BookDocumentPipeline,
        *,
        policy: EpubParseQualityPolicy | None = None,
    ) -> None:
        self.store = store
        self.documents = documents
        self.policy = policy or EpubParseQualityPolicy()

    def evaluate(self, request: BookQualityRequest) -> BookImportStatus:
        source = self.store.begin_book_quality_assessment(
            user_id=request.user_id,
            import_id=request.import_id,
            run_id=request.run_id,
            document_id=request.document_id,
        )
        assessment_id = self.store.book_quality_assessment_id(
            document_id=request.document_id,
            document_digest=str(source["digest"]),
            policy_version=self.policy.version,
            policy_snapshot_hash=self.policy.snapshot_hash,
        )
        existing = self.store.select_book_quality_assessment_status(
            user_id=request.user_id,
            import_id=request.import_id,
            run_id=request.run_id,
            assessment_id=assessment_id,
        )
        if existing is not None:
            return BookImportStatus.model_validate(existing)

        document = self.documents.load(
            user_id=request.user_id,
            document_id=request.document_id,
        )
        assessment = assess_epub_document(
            document,
            document_digest=str(source["digest"]),
            assessment_id=assessment_id,
            policy=self.policy,
        )
        payload = _canonical_json(assessment.model_dump(mode="json"))
        report_digest, report_path, _ = self.store.blobs.put_book_artifact(
            payload,
            tenant_scope=self.store.book_tenant_scope(request.user_id),
            category="quality",
            suffix="json",
        )
        status = self.store.publish_book_quality_assessment(
            BookQualityAssessmentPublication(
                assessment_id=assessment.assessment_id,
                user_id=request.user_id,
                import_id=request.import_id,
                run_id=request.run_id,
                document_id=request.document_id,
                document_digest=assessment.document_digest,
                policy_version=assessment.policy_version,
                policy_snapshot_hash=assessment.policy_snapshot_hash,
                outcome=assessment.outcome,
                report_digest=report_digest,
                report_blob_path=report_path,
            )
        )
        return BookImportStatus.model_validate(status)

    def load_for_materialization(
        self,
        *,
        user_id: str,
        document_id: str,
    ) -> BookDocument:
        self.store.require_passed_book_document(
            user_id=user_id,
            document_id=document_id,
            policy_version=self.policy.version,
            policy_snapshot_hash=self.policy.snapshot_hash,
        )
        return self.documents.load(user_id=user_id, document_id=document_id)

    def load_assessment(
        self,
        *,
        user_id: str,
        document_id: str,
    ) -> BookQualityAssessment:
        record = self.store.get_book_quality_assessment_record(
            user_id=user_id,
            document_id=document_id,
            policy_version=self.policy.version,
            policy_snapshot_hash=self.policy.snapshot_hash,
        )
        payload = self.store.blobs.read_book_artifact(str(record["blob_path"]))
        if sha256(payload).hexdigest() != str(record["report_digest"]):
            raise ValueError("BOOK_QUALITY_ASSESSMENT_DIGEST_MISMATCH")
        try:
            return BookQualityAssessment.model_validate_json(payload)
        except ValueError as exc:
            raise ValueError("BOOK_QUALITY_ASSESSMENT_INVALID") from exc


def assess_epub_document(
    document: BookDocument,
    *,
    document_digest: str,
    assessment_id: str,
    policy: EpubParseQualityPolicy,
) -> BookQualityAssessment:
    quality = document.quality_report
    finding_codes: list[str] = []
    observed_block_count = sum(len(section.blocks) for section in document.sections)
    observed_text_characters = sum(
        len(block.text)
        for section in document.sections
        for block in section.blocks
    )
    approved_parsers = {
        policy.native_parser_version,
        *policy.approved_alternate_parser_versions,
    }
    if document.parser_version not in approved_parsers:
        finding_codes.append("EPUB_QUALITY_PARSER_UNAPPROVED")
    if policy.require_complete_spine and (
        quality.spine_items_total <= 0
        or quality.spine_items_accounted != quality.spine_items_total
        or quality.spine_items_total != len(document.reading_order)
        or quality.spine_items_accounted != len(document.sections)
    ):
        finding_codes.append("EPUB_QUALITY_SPINE_INCOMPLETE")
    if policy.require_resolved_navigation and quality.navigation_targets_unresolved:
        finding_codes.append("EPUB_QUALITY_NAVIGATION_UNRESOLVED")
    navigation_items = _flatten_navigation(document)
    known_resources = {resource.resource_path for resource in document.resources}
    if (
        quality.navigation_targets_total != len(navigation_items)
        or quality.navigation_targets_unresolved > len(navigation_items)
        or any(item.resource_path not in known_resources for item in navigation_items)
    ):
        finding_codes.append("EPUB_QUALITY_NAVIGATION_INVALID")
    if policy.require_valid_anchors and not _anchors_are_valid(document):
        finding_codes.append("EPUB_QUALITY_ANCHOR_INVALID")
    if (
        quality.block_count != observed_block_count
        or quality.text_characters != observed_text_characters
    ):
        finding_codes.append("EPUB_QUALITY_TEXT_ACCOUNTING_INVALID")
    invalid_caption_relations = sum(
        1
        for section in document.sections
        for index, block in enumerate(section.blocks)
        if block.type == "caption"
        and (index == 0 or section.blocks[index - 1].type != "figure")
    )
    if policy.require_caption_figure_relationship and invalid_caption_relations:
        finding_codes.append("EPUB_QUALITY_CAPTION_RELATION_INVALID")
    empty_spine_items = sum(1 for section in document.sections if not section.blocks)
    if policy.require_native_text_per_spine_item and empty_spine_items:
        finding_codes.append("EPUB_QUALITY_NATIVE_TEXT_MISSING")
    duplicate_spine_items = _duplicate_spine_items(document)
    if policy.reject_duplicate_spine_content and duplicate_spine_items:
        finding_codes.append("EPUB_QUALITY_DUPLICATE_SPINE_CONTENT")
    missing_resources = len(quality.missing_resources)
    if policy.require_declared_resources and missing_resources:
        finding_codes.append("EPUB_QUALITY_RESOURCE_MISSING")
    unapproved_exclusions = sum(
        1
        for resource in document.resources
        if resource.disposition == "excluded"
        and resource.exclusion_code not in {
            *policy.allowed_exclusion_codes,
            "RESOURCE_MISSING",
        }
    )
    if unapproved_exclusions:
        finding_codes.append("EPUB_QUALITY_EXCLUSION_UNAPPROVED")
    repeated_boilerplate_blocks = _repeated_boilerplate_blocks(document, policy)
    if repeated_boilerplate_blocks:
        finding_codes.append("EPUB_QUALITY_REPEATED_BOILERPLATE")
    encoding_replacement_characters = sum(
        block.text.count("\ufffd")
        for section in document.sections
        for block in section.blocks
    )
    if encoding_replacement_characters > policy.max_encoding_replacement_characters:
        finding_codes.append("EPUB_QUALITY_ENCODING_CORRUPTION")

    permanent_findings = {
        "EPUB_QUALITY_ANCHOR_INVALID",
        "EPUB_QUALITY_CAPTION_RELATION_INVALID",
        "EPUB_QUALITY_EXCLUSION_UNAPPROVED",
        "EPUB_QUALITY_NAVIGATION_INVALID",
        "EPUB_QUALITY_NAVIGATION_UNRESOLVED",
        "EPUB_QUALITY_PARSER_UNAPPROVED",
        "EPUB_QUALITY_SPINE_INCOMPLETE",
        "EPUB_QUALITY_TEXT_ACCOUNTING_INVALID",
    }
    if any(code in permanent_findings for code in finding_codes):
        outcome: Literal[
            "PASS",
            "DEGRADED",
            "OCR_REQUIRED",
            "FAILED_PERMANENT",
        ] = "FAILED_PERMANENT"
    elif "EPUB_QUALITY_NATIVE_TEXT_MISSING" in finding_codes:
        outcome = "OCR_REQUIRED"
    elif any(
        code in {
            "EPUB_QUALITY_DUPLICATE_SPINE_CONTENT",
            "EPUB_QUALITY_ENCODING_CORRUPTION",
            "EPUB_QUALITY_REPEATED_BOILERPLATE",
            "EPUB_QUALITY_RESOURCE_MISSING",
        }
        for code in finding_codes
    ):
        outcome = "DEGRADED"
    else:
        outcome = "PASS"
    return BookQualityAssessment(
        assessment_id=assessment_id,
        document_id=document.document_id,
        document_digest=document_digest,
        document_schema_version=document.schema_version,
        parser_version=document.parser_version,
        normalizer_version=document.normalizer_version,
        policy=policy,
        policy_version=policy.version,
        policy_snapshot_hash=policy.snapshot_hash,
        outcome=outcome,
        finding_codes=sorted(finding_codes),
        metrics={
            "anchor_count": quality.anchor_count,
            "block_count": quality.block_count,
            "empty_spine_items": empty_spine_items,
            "duplicate_spine_items": duplicate_spine_items,
            "encoding_replacement_characters": encoding_replacement_characters,
            "invalid_caption_relations": invalid_caption_relations,
            "missing_resources": missing_resources,
            "unapproved_exclusions": unapproved_exclusions,
            "repeated_boilerplate_blocks": repeated_boilerplate_blocks,
            "navigation_targets_total": quality.navigation_targets_total,
            "navigation_targets_unresolved": quality.navigation_targets_unresolved,
            "observed_navigation_targets": len(navigation_items),
            "observed_block_count": observed_block_count,
            "observed_text_characters": observed_text_characters,
            "spine_items_accounted": quality.spine_items_accounted,
            "spine_items_total": quality.spine_items_total,
            "text_characters": quality.text_characters,
        },
    )


def _anchors_are_valid(document: BookDocument) -> bool:
    blocks = [block for section in document.sections for block in section.blocks]
    if document.quality_report.anchor_count != len(blocks):
        return False
    for section in document.sections:
        for occurrence, block in enumerate(section.blocks):
            anchor = block.anchor
            expected_fingerprint = sha256(
                f"{section.resource_path}\x1f{block.type}\x1f{block.text}\x1f{occurrence}".encode(
                    "utf-8"
                )
            ).hexdigest()
            if (
                anchor.asset_id != document.asset_id
                or anchor.resource_path != section.resource_path
            ):
                return False
            if anchor.block_fingerprint != expected_fingerprint or not anchor.offset_map:
                return False
            if anchor.normalized_end - anchor.normalized_start != len(block.text):
                return False
            if anchor.source_end <= anchor.source_start:
                return False
            if anchor.offset_map[0][0] != anchor.normalized_start:
                return False
            if anchor.offset_map[-1][1] != anchor.normalized_end:
                return False
            previous_normalized = anchor.normalized_start
            previous_source = anchor.source_start
            for normalized_start, normalized_end, source_start, source_end in anchor.offset_map:
                if normalized_start != previous_normalized or normalized_end <= normalized_start:
                    return False
                if source_start < previous_source or source_end <= source_start:
                    return False
                if source_start < anchor.source_start or source_end > anchor.source_end:
                    return False
                previous_normalized = normalized_end
                previous_source = source_end
    return True


def _duplicate_spine_items(document: BookDocument) -> int:
    fingerprints: set[str] = set()
    duplicates = 0
    for section in document.sections:
        if not section.blocks:
            continue
        payload = [
            (block.type, block.text.casefold())
            for block in section.blocks
        ]
        fingerprint = sha256(_canonical_json(payload)).hexdigest()
        if fingerprint in fingerprints:
            duplicates += 1
        else:
            fingerprints.add(fingerprint)
    return duplicates


def _repeated_boilerplate_blocks(
    document: BookDocument,
    policy: EpubParseQualityPolicy,
) -> int:
    occurrences: dict[str, set[int]] = {}
    for section_index, section in enumerate(document.sections):
        for block in section.blocks:
            normalized = " ".join(block.text.casefold().split())
            if block.type == "heading" or len(normalized) < policy.repeated_boilerplate_min_characters:
                continue
            occurrences.setdefault(normalized, set()).add(section_index)
    return sum(
        1
        for section_indexes in occurrences.values()
        if len(section_indexes) >= policy.repeated_boilerplate_min_occurrences
    )


def _flatten_navigation(document: BookDocument) -> list[BookNavigationItem]:
    flattened: list[BookNavigationItem] = []

    def collect(items: list[BookNavigationItem]) -> None:
        for item in items:
            flattened.append(item)
            collect(item.children)

    collect(list(document.navigation))
    return flattened


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
