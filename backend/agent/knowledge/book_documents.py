"""Deterministic EPUB construction for Knowledge Core BookDocuments."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
import json
import posixpath
import re
from typing import Any, Literal
import unicodedata
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from agent.knowledge.models import BookDocumentRequest, BookImportStatus
from agent.knowledge.store import (
    BookDocumentPublication,
    BookDocumentResourcePublication,
    KnowledgeStore,
)


BOOK_DOCUMENT_SCHEMA_VERSION = "book-document-v1"
EPUB_PARSER_VERSION = "epub-native-v1"
BOOK_NORMALIZER_VERSION = "book-normalizer-v1"


class BookDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BookDocumentMetadata(BookDocumentModel):
    title: str = ""
    creators: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    identifiers: list[str] = Field(default_factory=list)
    publisher: str = ""
    published_at: str = ""


class BookSourceAnchor(BookDocumentModel):
    asset_id: str
    resource_path: str
    source_element: str
    fragment: str = ""
    epub_cfi: str = ""
    block_fingerprint: str
    normalized_start: int = Field(ge=0)
    normalized_end: int = Field(ge=0)
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    offset_map: list[tuple[int, int, int, int]] = Field(default_factory=list)


class BookLink(BookDocumentModel):
    text: str = ""
    href: str


class BookBlock(BookDocumentModel):
    id: str
    type: Literal[
        "heading",
        "paragraph",
        "list_item",
        "quotation",
        "table",
        "figure",
        "caption",
        "note",
        "link",
    ]
    text: str
    role: str = ""
    level: int | None = Field(default=None, ge=1, le=6)
    links: list[BookLink] = Field(default_factory=list)
    anchor: BookSourceAnchor


class BookSection(BookDocumentModel):
    id: str
    resource_path: str
    title: str = ""
    role: str = "body"
    blocks: list[BookBlock] = Field(default_factory=list)


class BookReadingOrderItem(BookDocumentModel):
    idref: str
    resource_path: str
    media_type: str
    position: int = Field(ge=0)
    linear: bool = True


class BookNavigationItem(BookDocumentModel):
    label: str
    href: str
    resource_path: str
    fragment: str = ""
    children: list["BookNavigationItem"] = Field(default_factory=list)


class BookResource(BookDocumentModel):
    id: str
    manifest_id: str
    resource_path: str
    media_type: str
    properties: list[str] = Field(default_factory=list)
    source_sha256: str
    extracted_text_sha256: str
    byte_size: int = Field(ge=0)
    spine_position: int | None = Field(default=None, ge=0)
    disposition: Literal["included", "excluded"] = "included"
    exclusion_code: str = ""


class BookParseQualityReport(BookDocumentModel):
    policy_version: str = "book-parse-observation-v1"
    evaluated: bool = False
    outcome: Literal[
        "PASS",
        "DEGRADED",
        "OCR_REQUIRED",
        "FAILED_RETRYABLE",
        "FAILED_PERMANENT",
    ] | None = None
    navigation_source: Literal["epub3", "ncx", "inferred"]
    spine_items_total: int = Field(ge=0)
    spine_items_accounted: int = Field(ge=0)
    navigation_targets_total: int = Field(ge=0)
    navigation_targets_unresolved: int = Field(ge=0)
    missing_resources: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    text_characters: int = Field(ge=0)
    block_count: int = Field(ge=0)
    anchor_count: int = Field(ge=0)
    language: str = ""


class BookDocument(BookDocumentModel):
    schema_version: str
    normalizer_version: str
    document_id: str
    asset_id: str
    run_id: str
    parser_version: str
    metadata: BookDocumentMetadata
    reading_order: list[BookReadingOrderItem]
    navigation: list[BookNavigationItem]
    sections: list[BookSection]
    resources: list[BookResource]
    quality_report: BookParseQualityReport


class BookDocumentError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        *,
        stage: Literal["extracted", "identified", "structured"] = "structured",
        retryable: bool = False,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.stage = stage
        self.retryable = retryable


@dataclass(frozen=True)
class ExtractedResource:
    resource: BookResource
    text: str | None


@dataclass(frozen=True)
class ParsedBook:
    document: BookDocument
    resources: tuple[ExtractedResource, ...]


@dataclass(frozen=True)
class LexicalBlockSpan:
    tag: str
    text: str
    source_start: int
    source_end: int
    offset_map: tuple[tuple[int, int, int, int], ...]


class BookDocumentPipeline:
    """Build and publish one immutable BookDocument behind the Knowledge Core seam."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def construct(self, request: BookDocumentRequest) -> BookImportStatus:
        document_id = self.store.book_document_id(
            run_id=request.run_id,
            parser_version=EPUB_PARSER_VERSION,
            schema_version=BOOK_DOCUMENT_SCHEMA_VERSION,
        )
        existing = self.store.find_book_document_status(
            user_id=request.user_id,
            import_id=request.import_id,
            run_id=request.run_id,
            document_id=document_id,
        )
        if existing is not None:
            return BookImportStatus.model_validate(existing)

        source = self.store.begin_book_document(
            user_id=request.user_id,
            import_id=request.import_id,
            run_id=request.run_id,
            parser_version=EPUB_PARSER_VERSION,
            schema_version=BOOK_DOCUMENT_SCHEMA_VERSION,
        )
        receipt_metadata = {
            "parser_version": EPUB_PARSER_VERSION,
            "schema_version": BOOK_DOCUMENT_SCHEMA_VERSION,
        }
        try:
            raw = self.store.blobs.resolve(str(source["blob_path"])).read_bytes()
            if len(raw) != int(source["byte_size"]):
                raise BookDocumentError("BOOK_ASSET_SIZE_MISMATCH", stage="extracted")
            if sha256(raw).hexdigest() != str(source["asset_sha256"]):
                raise BookDocumentError("BOOK_ASSET_DIGEST_MISMATCH", stage="extracted")
            parsed = parse_epub_document(
                raw,
                document_id=document_id,
                asset_id=str(source["asset_id"]),
                run_id=request.run_id,
                parser_version=EPUB_PARSER_VERSION,
                schema_version=BOOK_DOCUMENT_SCHEMA_VERSION,
            )
            tenant_scope = self.store.book_tenant_scope(request.user_id)
            resource_rows: list[BookDocumentResourcePublication] = []
            for item in parsed.resources:
                digest = ""
                blob_path = ""
                byte_size = 0
                if item.text is not None:
                    resource_payload = _canonical_json(
                        {
                            "schema_version": "book-resource-v1",
                            "manifest_id": item.resource.manifest_id,
                            "resource_path": item.resource.resource_path,
                            "media_type": item.resource.media_type,
                            "text": item.text,
                        }
                    )
                    digest, blob_path, byte_size = self.store.blobs.put_book_artifact(
                        resource_payload,
                        tenant_scope=tenant_scope,
                        category="resources",
                        suffix="json",
                    )
                resource_rows.append(
                    BookDocumentResourcePublication(
                        id=item.resource.id,
                        manifest_id=item.resource.manifest_id,
                        resource_path=item.resource.resource_path,
                        media_type=item.resource.media_type,
                        source_digest=item.resource.source_sha256,
                        extracted_digest=item.resource.extracted_text_sha256,
                        artifact_digest=digest,
                        blob_path=blob_path,
                        byte_size=item.resource.byte_size,
                        artifact_byte_size=byte_size,
                        spine_position=item.resource.spine_position,
                        disposition=item.resource.disposition,
                        reason_code=item.resource.exclusion_code,
                    )
                )
            document_payload = _canonical_json(parsed.document.model_dump(mode="json"))
            document_digest, document_path, _ = self.store.blobs.put_book_artifact(
                document_payload,
                tenant_scope=tenant_scope,
                category="documents",
                suffix="json",
            )
        except BookDocumentError as exc:
            return self._fail(
                request,
                exc,
                receipt_metadata,
                input_digest=str(source["asset_sha256"]),
            )
        except (BadZipFile, KeyError, RuntimeError, UnicodeError):
            return self._fail(
                request,
                BookDocumentError("EPUB_ASSET_READ_FAILED", stage="extracted"),
                receipt_metadata,
                input_digest=str(source["asset_sha256"]),
            )
        except ValueError:
            return self._fail(
                request,
                BookDocumentError("BOOK_DOCUMENT_INVALID", stage="structured"),
                receipt_metadata,
                input_digest=str(source["asset_sha256"]),
            )
        except OSError:
            return self._fail(
                request,
                BookDocumentError(
                    "BOOK_DOCUMENT_STORAGE_FAILED",
                    stage="extracted",
                    retryable=True,
                ),
                receipt_metadata,
                input_digest=str(source["asset_sha256"]),
            )

        quality = parsed.document.quality_report
        status = self.store.publish_book_document(
            BookDocumentPublication(
                user_id=request.user_id,
                import_id=request.import_id,
                run_id=request.run_id,
                document_id=document_id,
                asset_id=str(source["asset_id"]),
                input_digest=str(source["asset_sha256"]),
                document_digest=document_digest,
                document_blob_path=document_path,
                parser_version=EPUB_PARSER_VERSION,
                schema_version=BOOK_DOCUMENT_SCHEMA_VERSION,
                quality_outcome=quality.outcome or "",
                quality_evaluated=quality.evaluated,
                resources=tuple(resource_rows),
                receipt_metadata={
                    **receipt_metadata,
                    "resource_count": len(parsed.document.resources),
                    "spine_item_count": len(parsed.document.reading_order),
                    "block_count": quality.block_count,
                    "navigation_item_count": quality.navigation_targets_total,
                    "quality_evaluated": quality.evaluated,
                },
            )
        )
        return BookImportStatus.model_validate(status)

    def load(self, *, user_id: str, document_id: str) -> BookDocument:
        record = self.store.get_book_document_record(user_id=user_id, document_id=document_id)
        payload = self.store.blobs.read_book_artifact(str(record["blob_path"]))
        if sha256(payload).hexdigest() != str(record["digest"]):
            raise BookDocumentError("BOOK_DOCUMENT_DIGEST_MISMATCH")
        try:
            return BookDocument.model_validate_json(payload)
        except ValueError as exc:
            raise BookDocumentError("BOOK_DOCUMENT_INVALID") from exc

    def _fail(
        self,
        request: BookDocumentRequest,
        error: BookDocumentError,
        metadata: dict[str, Any],
        *,
        input_digest: str,
    ) -> BookImportStatus:
        result = self.store.publish_book_stage(
            user_id=request.user_id,
            import_id=request.import_id,
            run_id=request.run_id,
            stage=error.stage,
            stage_version=f"{EPUB_PARSER_VERSION}:{BOOK_DOCUMENT_SCHEMA_VERSION}",
            input_digest=input_digest,
            output_digest="",
            status="failed_retryable" if error.retryable else "failed_permanent",
            reason_code=error.reason_code,
            metadata=metadata,
        )
        return BookImportStatus.model_validate(result)


def parse_epub_document(
    raw: bytes,
    *,
    document_id: str,
    asset_id: str,
    run_id: str,
    parser_version: str,
    schema_version: str,
) -> ParsedBook:
    try:
        archive = ZipFile(BytesIO(raw))
    except BadZipFile as exc:
        raise BookDocumentError("MALFORMED_EPUB", stage="extracted") from exc
    with archive:
        names = {name for name in archive.namelist() if not name.endswith("/")}
        if "META-INF/container.xml" not in names:
            raise BookDocumentError("EPUB_CONTAINER_MALFORMED", stage="extracted")
        container = _parse_xml(
            archive.read("META-INF/container.xml"),
            reason_code="EPUB_CONTAINER_MALFORMED",
            stage="extracted",
        )
        package_path = _container_package_path(container)
        if package_path not in names:
            raise BookDocumentError("EPUB_PACKAGE_MISSING", stage="extracted")
        package = _parse_xml(
            archive.read(package_path),
            reason_code="EPUB_PACKAGE_MALFORMED",
            stage="identified",
        )
        metadata = _metadata(package)
        manifest = _manifest(package, package_path)
        reading_order = _reading_order(package, manifest)
        if not reading_order:
            raise BookDocumentError("EPUB_SPINE_MISSING", stage="identified")

        extracted: dict[str, ExtractedResource] = {}
        sections: list[BookSection] = []
        resource_fragments: dict[str, set[str]] = {}
        for item in reading_order:
            if item.resource_path not in names:
                raise BookDocumentError("EPUB_SPINE_RESOURCE_MISSING", stage="extracted")
            source = archive.read(item.resource_path)
            source_text = _decode_xml_text(source)
            root = _parse_xml(
                source,
                reason_code="EPUB_CONTENT_MALFORMED",
                stage="structured",
            )
            section, text = _section_from_resource(
                root,
                asset_id=asset_id,
                resource_path=item.resource_path,
                spine_position=item.position,
                source_text=source_text,
            )
            sections.append(section)
            resource_fragments[item.resource_path] = _element_ids(root)
            if item.idref not in extracted:
                manifest_item = manifest[item.idref]
                extracted[item.idref] = _resource_artifact(
                    manifest_id=item.idref,
                    path=item.resource_path,
                    media_type=item.media_type,
                    properties=manifest_item["properties"].split(),
                    source=source,
                    text=text,
                    spine_position=item.position,
                )

        navigation, navigation_source, nav_resource = _navigation(
            archive=archive,
            names=names,
            package=package,
            manifest=manifest,
            sections=sections,
        )
        if nav_resource is not None:
            extracted[nav_resource.resource.manifest_id] = nav_resource
        unresolved = _unresolved_navigation(navigation, names, resource_fragments)
        if unresolved:
            raise BookDocumentError("EPUB_NAV_TARGET_MISSING", stage="structured")

        for manifest_id, item in manifest.items():
            if manifest_id in extracted:
                continue
            path = item["path"]
            if path not in names:
                extracted[manifest_id] = _missing_resource(
                    manifest_id=manifest_id,
                    path=path,
                    media_type=item["media_type"],
                    properties=item["properties"].split(),
                )
                continue
            extracted[manifest_id] = _resource_artifact(
                manifest_id=manifest_id,
                path=path,
                media_type=item["media_type"],
                properties=item["properties"].split(),
                source=archive.read(path),
                text=None,
                spine_position=None,
                disposition="excluded",
                exclusion_code="NOT_EXTRACTED_TEXT_RESOURCE",
            )

    resources = tuple(extracted[manifest_id] for manifest_id in manifest)
    block_count = sum(len(section.blocks) for section in sections)
    document = BookDocument(
        schema_version=schema_version,
        normalizer_version=BOOK_NORMALIZER_VERSION,
        document_id=document_id,
        asset_id=asset_id,
        run_id=run_id,
        parser_version=parser_version,
        metadata=metadata,
        reading_order=reading_order,
        navigation=navigation,
        sections=sections,
        resources=[item.resource for item in resources],
        quality_report=BookParseQualityReport(
            navigation_source=navigation_source,
            spine_items_total=len(reading_order),
            spine_items_accounted=len(sections),
            navigation_targets_total=_navigation_count(navigation),
            navigation_targets_unresolved=0,
            missing_resources=[
                item.resource.resource_path
                for item in resources
                if item.resource.exclusion_code == "RESOURCE_MISSING"
            ],
            exclusions=[
                f"{item.resource.manifest_id}:{item.resource.exclusion_code}"
                for item in resources
                if item.resource.disposition == "excluded"
            ],
            text_characters=sum(len(block.text) for section in sections for block in section.blocks),
            block_count=block_count,
            anchor_count=block_count,
            language=metadata.languages[0] if metadata.languages else "",
        ),
    )
    return ParsedBook(document=document, resources=resources)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parse_xml(raw: bytes, *, reason_code: str, stage: str) -> ET.Element:
    upper = raw[:65536].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise BookDocumentError("UNSAFE_XML_DECLARATION", stage=stage)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise BookDocumentError(reason_code, stage=stage) from exc


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _attribute(element: ET.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local_name(key) == name.casefold():
            return str(value).strip()
    return ""


def _clean_text(element: ET.Element) -> str:
    parts: list[str] = []

    def collect(current: ET.Element) -> None:
        if _local_name(current.tag) in {"script", "style", "template", "form"}:
            return
        if current.text:
            parts.append(current.text)
        for child in current:
            collect(child)
            if child.tail:
                parts.append(child.tail)

    collect(element)
    return unicodedata.normalize("NFC", " ".join(" ".join(parts).split()))


def _container_package_path(container: ET.Element) -> str:
    for element in container.iter():
        if _local_name(element.tag) == "rootfile":
            if _attribute(element, "media-type") != "application/oebps-package+xml":
                continue
            raw_path = unquote(_attribute(element, "full-path"))
            path = posixpath.normpath(raw_path)
            if (
                not raw_path
                or "\\" in raw_path
                or raw_path.startswith("/")
                or path == ".."
                or path.startswith("../")
            ):
                raise BookDocumentError("EPUB_PACKAGE_ROOTFILE_MISSING", stage="extracted")
            return path
    raise BookDocumentError("EPUB_PACKAGE_ROOTFILE_MISSING", stage="extracted")


def _metadata(package: ET.Element) -> BookDocumentMetadata:
    values: dict[str, list[str]] = {}
    for element in package.iter():
        name = _local_name(element.tag)
        if name in {"title", "creator", "language", "identifier", "publisher", "date"}:
            text = _clean_text(element)
            if text:
                values.setdefault(name, []).append(text)
    return BookDocumentMetadata(
        title=(values.get("title") or [""])[0],
        creators=values.get("creator", []),
        languages=values.get("language", []),
        identifiers=values.get("identifier", []),
        publisher=(values.get("publisher") or [""])[0],
        published_at=(values.get("date") or [""])[0],
    )


def _manifest(package: ET.Element, package_path: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for element in package.iter():
        if _local_name(element.tag) != "item":
            continue
        item_id = _attribute(element, "id")
        href = _attribute(element, "href")
        if not item_id or not href or item_id in result:
            raise BookDocumentError("EPUB_MANIFEST_INVALID", stage="identified")
        path, fragment = _resolve_href(package_path, href)
        result[item_id] = {
            "id": item_id,
            "path": path,
            "fragment": fragment,
            "media_type": _attribute(element, "media-type"),
            "properties": _attribute(element, "properties"),
        }
    return result


def _reading_order(
    package: ET.Element,
    manifest: dict[str, dict[str, str]],
) -> list[BookReadingOrderItem]:
    result: list[BookReadingOrderItem] = []
    spine = next((element for element in package.iter() if _local_name(element.tag) == "spine"), None)
    if spine is None:
        return result
    for element in spine:
        if _local_name(element.tag) != "itemref":
            continue
        idref = _attribute(element, "idref")
        item = manifest.get(idref)
        if item is None:
            raise BookDocumentError("EPUB_SPINE_MANIFEST_ITEM_MISSING", stage="identified")
        if item["media_type"] not in {"application/xhtml+xml", "text/html"}:
            raise BookDocumentError("EPUB_SPINE_MEDIA_UNSUPPORTED", stage="identified")
        result.append(
            BookReadingOrderItem(
                idref=idref,
                resource_path=item["path"],
                media_type=item["media_type"],
                position=len(result),
                linear=_attribute(element, "linear").casefold() != "no",
            )
        )
    return result


def _resolve_href(base_path: str, href: str) -> tuple[str, str]:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query:
        raise BookDocumentError("EPUB_UNSAFE_RESOURCE_REFERENCE", stage="identified")
    decoded = unquote(parsed.path)
    if not decoded or "\\" in decoded or decoded.startswith("/"):
        raise BookDocumentError("EPUB_UNSAFE_RESOURCE_REFERENCE", stage="identified")
    combined = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), decoded))
    if combined == ".." or combined.startswith("../") or combined.startswith("/"):
        raise BookDocumentError("EPUB_UNSAFE_RESOURCE_REFERENCE", stage="identified")
    return combined, unquote(parsed.fragment)


class _LexicalBlockParser(HTMLParser):
    _block_tags = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "blockquote",
        "table",
        "figure",
        "figcaption",
        "aside",
        "a",
    }
    _unsafe_tags = {"script", "style", "template", "form"}

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_starts = [0]
        for match in re.finditer(r"\n", source):
            self.line_starts.append(match.end())
        self.active: list[dict[str, Any]] = []
        self.spans: dict[str, list[LexicalBlockSpan]] = {}
        self.unsafe_depth = 0

    def _absolute(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def _append(self, text: str, source_start: int, source_end: int) -> None:
        if self.unsafe_depth:
            return
        for capture in self.active:
            if capture["tag"] == "figure":
                continue
            capture["characters"].extend(
                (character, source_start + index, source_start + index + 1)
                for index, character in enumerate(text)
            )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        absolute = self._absolute()
        if tag in self._unsafe_tags:
            self.unsafe_depth += 1
            return
        if self.unsafe_depth:
            return
        if tag in self._block_tags:
            self.active.append(
                {"tag": tag, "source_start": absolute, "characters": []}
            )
        if tag == "img":
            alt = next((value or "" for name, value in attrs if name.casefold() == "alt"), "")
            if not alt:
                return
            start_tag = self.get_starttag_text() or ""
            match = re.search(r"\balt\s*=\s*(['\"])(.*?)\1", start_tag, re.IGNORECASE | re.DOTALL)
            if match is None:
                return
            value_start = absolute + match.start(2)
            for capture in self.active:
                if capture["tag"] == "figure":
                    capture["characters"].extend(
                        (character, value_start + index, value_start + index + 1)
                        for index, character in enumerate(unescape(match.group(2)))
                    )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self._finish(tag.casefold(), self._absolute() + len(self.get_starttag_text() or ""))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._unsafe_tags:
            self.unsafe_depth = max(0, self.unsafe_depth - 1)
            return
        if self.unsafe_depth:
            return
        absolute = self._absolute()
        closing_end = self.source.find(">", absolute)
        self._finish(tag, len(self.source) if closing_end < 0 else closing_end + 1)

    def _finish(self, tag: str, source_end: int) -> None:
        for index in range(len(self.active) - 1, -1, -1):
            capture = self.active[index]
            if capture["tag"] != tag:
                continue
            del self.active[index]
            text, offset_map = _normalize_lexical_characters(capture["characters"])
            if text:
                self.spans.setdefault(tag, []).append(
                    LexicalBlockSpan(
                        tag=tag,
                        text=text,
                        source_start=int(capture["source_start"]),
                        source_end=source_end,
                        offset_map=offset_map,
                    )
                )
            return

    def handle_data(self, data: str) -> None:
        self._append(data, self._absolute(), self._absolute() + len(data))

    def handle_entityref(self, name: str) -> None:
        raw = f"&{name};"
        decoded = unescape(raw)
        start = self._absolute()
        for capture in self.active:
            if not self.unsafe_depth and capture["tag"] != "figure":
                capture["characters"].extend((character, start, start + len(raw)) for character in decoded)

    def handle_charref(self, name: str) -> None:
        raw = f"&#{name};"
        decoded = unescape(raw)
        start = self._absolute()
        for capture in self.active:
            if not self.unsafe_depth and capture["tag"] != "figure":
                capture["characters"].extend((character, start, start + len(raw)) for character in decoded)


def _normalize_lexical_characters(
    characters: list[tuple[str, int, int]],
) -> tuple[str, tuple[tuple[int, int, int, int], ...]]:
    normalized: list[tuple[str, int, int]] = []
    pending_whitespace: tuple[int, int] | None = None
    for character, source_start, source_end in characters:
        if character.isspace():
            if normalized:
                pending_whitespace = (
                    source_start if pending_whitespace is None else pending_whitespace[0],
                    source_end,
                )
            continue
        if pending_whitespace is not None:
            normalized.append((" ", pending_whitespace[0], pending_whitespace[1]))
            pending_whitespace = None
        normalized.append((unicodedata.normalize("NFC", character), source_start, source_end))
    text = "".join(character for character, _start, _end in normalized)
    spans: list[tuple[int, int, int, int]] = []
    normalized_cursor = 0
    for character, source_start, source_end in normalized:
        next_cursor = normalized_cursor + len(character)
        if (
            spans
            and spans[-1][1] == normalized_cursor
            and spans[-1][3] == source_start
            and (spans[-1][1] - spans[-1][0]) == (spans[-1][3] - spans[-1][2])
            and len(character) == source_end - source_start
        ):
            previous = spans[-1]
            spans[-1] = (previous[0], next_cursor, previous[2], source_end)
        else:
            spans.append((normalized_cursor, next_cursor, source_start, source_end))
        normalized_cursor = next_cursor
    return text, tuple(spans)


def _decode_xml_text(raw: bytes) -> str:
    declaration = raw[:256]
    match = re.search(br"encoding\s*=\s*['\"]([A-Za-z0-9._-]+)['\"]", declaration, re.IGNORECASE)
    encoding = match.group(1).decode("ascii") if match is not None else "utf-8-sig"
    try:
        return raw.decode(encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise BookDocumentError("EPUB_TEXT_DECODING_FAILED", stage="structured") from exc


def _lexical_block_spans(source: str) -> dict[str, list[LexicalBlockSpan]]:
    parser = _LexicalBlockParser(source)
    parser.feed(source)
    parser.close()
    return parser.spans


def _section_from_resource(
    root: ET.Element,
    *,
    asset_id: str,
    resource_path: str,
    spine_position: int,
    source_text: str,
) -> tuple[BookSection, str]:
    blocks: list[BookBlock] = []
    extracted_parts: list[str] = []
    cursor = 0
    lexical_spans = _lexical_block_spans(source_text)
    lexical_occurrences: dict[str, int] = {}

    def emit(element: ET.Element, block_type: str, text: str, level: int | None = None) -> None:
        nonlocal cursor
        tag = _local_name(element.tag)
        lexical_index = lexical_occurrences.get(tag, 0)
        candidates = lexical_spans.get(tag, [])
        lexical = candidates[lexical_index] if lexical_index < len(candidates) else None
        lexical_occurrences[tag] = lexical_index + 1
        if lexical is None or lexical.text != text:
            raise BookDocumentError("EPUB_SOURCE_ANCHOR_INVALID", stage="structured")
        if not text:
            return
        if extracted_parts:
            cursor += 1
        start = cursor
        end = start + len(text)
        extracted_parts.append(text)
        cursor = end
        occurrence = len(blocks)
        fingerprint = sha256(
            f"{resource_path}\x1f{block_type}\x1f{text}\x1f{occurrence}".encode("utf-8")
        ).hexdigest()
        block_identity = sha256(
            f"{asset_id}\x1f{resource_path}\x1f{spine_position}\x1f{occurrence}\x1f{fingerprint}".encode(
                "utf-8"
            )
        ).hexdigest()[:32]
        block_id = f"bkb_{block_identity}"
        cfi = element.attrib.get("data-epub-cfi", "") or _attribute(element, "cfi")
        links = _links(element)
        blocks.append(
            BookBlock(
                id=block_id,
                type=block_type,
                text=text,
                role=_epub_type(element),
                level=level,
                links=links,
                anchor=BookSourceAnchor(
                    asset_id=asset_id,
                    resource_path=resource_path,
                    source_element=tag,
                    fragment=_attribute(element, "id"),
                    epub_cfi=cfi,
                    block_fingerprint=fingerprint,
                    normalized_start=start,
                    normalized_end=end,
                    source_start=lexical.source_start,
                    source_end=lexical.source_end,
                    offset_map=[
                        (
                            start + normalized_start,
                            start + normalized_end,
                            source_start,
                            source_end,
                        )
                        for normalized_start, normalized_end, source_start, source_end in lexical.offset_map
                    ],
                ),
            )
        )

    def visit(element: ET.Element) -> None:
        name = _local_name(element.tag)
        if name in {"script", "style", "template", "form"}:
            return
        if name == "figure":
            alt = " ".join(
                value
                for child in element.iter()
                if _local_name(child.tag) == "img"
                for value in [_attribute(child, "alt")]
                if value
            )
            emit(element, "figure", alt or _clean_text(element))
            for child in element:
                if _local_name(child.tag) == "figcaption":
                    visit(child)
            return
        block_type = {
            "p": "paragraph",
            "li": "list_item",
            "blockquote": "quotation",
            "table": "table",
            "figcaption": "caption",
            "aside": "note",
        }.get(name)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            emit(element, "heading", _clean_text(element), int(name[1]))
            for descendant in element.iter():
                if descendant is not element and _local_name(descendant.tag) == "a":
                    emit(descendant, "link", _clean_text(descendant))
            return
        if block_type is not None:
            emit(element, block_type, _clean_text(element))
            for descendant in element.iter():
                if descendant is not element and _local_name(descendant.tag) == "a":
                    emit(descendant, "link", _clean_text(descendant))
            return
        if name == "a":
            emit(element, "link", _clean_text(element))
            return
        for child in element:
            visit(child)

    body = next((element for element in root.iter() if _local_name(element.tag) == "body"), root)
    visit(body)
    title = next((block.text for block in blocks if block.type == "heading"), "")
    role = _epub_type(body) or _epub_type(root) or "body"
    section_hash = sha256(
        f"{asset_id}\x1f{resource_path}\x1f{spine_position}".encode("utf-8")
    ).hexdigest()[:32]
    return (
        BookSection(
            id=f"bksc_{section_hash}",
            resource_path=resource_path,
            title=title,
            role=role,
            blocks=blocks,
        ),
        "\n".join(extracted_parts),
    )


def _links(element: ET.Element) -> list[BookLink]:
    result: list[BookLink] = []
    for child in element.iter():
        if _local_name(child.tag) != "a":
            continue
        href = _attribute(child, "href")
        parsed = urlsplit(href)
        if parsed.scheme.casefold() not in {"", "http", "https", "mailto"}:
            raise BookDocumentError("EPUB_UNSAFE_LINK", stage="structured")
        if href:
            result.append(BookLink(text=_clean_text(child), href=href))
    return result


def _epub_type(element: ET.Element) -> str:
    value = element.attrib.get("{http://www.idpf.org/2007/ops}type", "")
    return str(value).strip().split()[0] if str(value).strip() else ""


def _element_ids(root: ET.Element) -> set[str]:
    return {_attribute(element, "id") for element in root.iter() if _attribute(element, "id")}


def _resource_artifact(
    *,
    manifest_id: str,
    path: str,
    media_type: str,
    properties: list[str],
    source: bytes,
    text: str | None,
    spine_position: int | None,
    disposition: Literal["included", "excluded"] = "included",
    exclusion_code: str = "",
) -> ExtractedResource:
    source_digest = sha256(source).hexdigest()
    text_digest = sha256(text.encode("utf-8")).hexdigest() if text is not None else ""
    resource_id = f"bkdr_{sha256(f'{manifest_id}\x1f{path}\x1f{source_digest}'.encode('utf-8')).hexdigest()[:32]}"
    return ExtractedResource(
        resource=BookResource(
            id=resource_id,
            manifest_id=manifest_id,
            resource_path=path,
            media_type=media_type,
            properties=properties,
            source_sha256=source_digest,
            extracted_text_sha256=text_digest,
            byte_size=len(source),
            spine_position=spine_position,
            disposition=disposition,
            exclusion_code=exclusion_code,
        ),
        text=text,
    )


def _missing_resource(
    *,
    manifest_id: str,
    path: str,
    media_type: str,
    properties: list[str],
) -> ExtractedResource:
    identity = sha256(f"{manifest_id}\x1f{path}\x1fmissing".encode("utf-8")).hexdigest()[:32]
    return ExtractedResource(
        resource=BookResource(
            id=f"bkdr_{identity}",
            manifest_id=manifest_id,
            resource_path=path,
            media_type=media_type,
            properties=properties,
            source_sha256="",
            extracted_text_sha256="",
            byte_size=0,
            disposition="excluded",
            exclusion_code="RESOURCE_MISSING",
        ),
        text=None,
    )


def _navigation(
    *,
    archive: ZipFile,
    names: set[str],
    package: ET.Element,
    manifest: dict[str, dict[str, str]],
    sections: list[BookSection],
) -> tuple[list[BookNavigationItem], Literal["epub3", "ncx", "inferred"], ExtractedResource | None]:
    nav_items = [item for item in manifest.values() if "nav" in item["properties"].split()]
    if len(nav_items) > 1:
        raise BookDocumentError("EPUB_NAV_MULTIPLE", stage="identified")
    nav_item = nav_items[0] if nav_items else None
    if nav_item is not None:
        path = nav_item["path"]
        if path not in names:
            raise BookDocumentError("EPUB_NAV_RESOURCE_MISSING", stage="extracted")
        source = archive.read(path)
        root = _parse_xml(source, reason_code="EPUB_NAV_MALFORMED", stage="structured")
        nav = next(
            (
                element
                for element in root.iter()
                if _local_name(element.tag) == "nav" and _epub_type(element) == "toc"
            ),
            None,
        )
        if nav is None:
            raise BookDocumentError("EPUB_NAV_TOC_MISSING", stage="structured")
        items = _epub3_navigation(nav, path)
        if not items:
            raise BookDocumentError("EPUB_NAV_MALFORMED", stage="structured")
        text = "\n".join(item.label for item in _flatten_navigation(items))
        return items, "epub3", _resource_artifact(
            manifest_id=nav_item["id"],
            path=path,
            media_type=nav_item["media_type"],
            properties=nav_item["properties"].split(),
            source=source,
            text=text,
            spine_position=None,
        )

    spine = next((element for element in package.iter() if _local_name(element.tag) == "spine"), None)
    ncx_id = _attribute(spine, "toc") if spine is not None else ""
    if ncx_id and ncx_id not in manifest:
        raise BookDocumentError("EPUB_NCX_MANIFEST_ITEM_MISSING", stage="identified")
    ncx_item = (
        manifest.get(ncx_id)
        if ncx_id
        else next(
            (item for item in manifest.values() if item["media_type"] == "application/x-dtbncx+xml"),
            None,
        )
    )
    if ncx_item is not None:
        path = ncx_item["path"]
        if path not in names:
            raise BookDocumentError("EPUB_NAV_RESOURCE_MISSING", stage="extracted")
        source = archive.read(path)
        root = _parse_xml(source, reason_code="EPUB_NAV_MALFORMED", stage="structured")
        items = _ncx_navigation(root, path)
        if not items:
            raise BookDocumentError("EPUB_NCX_MALFORMED", stage="structured")
        text = "\n".join(item.label for item in _flatten_navigation(items))
        return items, "ncx", _resource_artifact(
            manifest_id=ncx_item["id"],
            path=path,
            media_type=ncx_item["media_type"],
            properties=ncx_item["properties"].split(),
            source=source,
            text=text,
            spine_position=None,
        )

    inferred = []
    for section in sections:
        headings = [block for block in section.blocks if block.type == "heading"]
        if not headings:
            inferred.append(
                BookNavigationItem(
                    label=section.title or "Untitled section",
                    href=section.resource_path,
                    resource_path=section.resource_path,
                )
            )
            continue
        inferred.extend(
            BookNavigationItem(
                label=heading.text,
                href=(
                    f"{section.resource_path}#{heading.anchor.fragment}"
                    if heading.anchor.fragment
                    else section.resource_path
                ),
                resource_path=section.resource_path,
                fragment=heading.anchor.fragment,
            )
            for heading in headings
        )
    return inferred, "inferred", None


def _epub3_navigation(nav: ET.Element, nav_path: str) -> list[BookNavigationItem]:
    root_list = next((child for child in nav if _local_name(child.tag) in {"ol", "ul"}), None)
    if root_list is None:
        return []

    def parse_list(element: ET.Element) -> list[BookNavigationItem]:
        result: list[BookNavigationItem] = []
        for child in element:
            if _local_name(child.tag) != "li":
                continue
            link = next((item for item in child if _local_name(item.tag) == "a"), None)
            nested = next((item for item in child if _local_name(item.tag) in {"ol", "ul"}), None)
            if link is None:
                continue
            href = _attribute(link, "href")
            path, fragment = _resolve_href(nav_path, href)
            result.append(
                BookNavigationItem(
                    label=_clean_text(link),
                    href=href,
                    resource_path=path,
                    fragment=fragment,
                    children=parse_list(nested) if nested is not None else [],
                )
            )
        return result

    return parse_list(root_list)


def _ncx_navigation(root: ET.Element, nav_path: str) -> list[BookNavigationItem]:
    nav_map = next((element for element in root.iter() if _local_name(element.tag) == "navmap"), None)
    if nav_map is None:
        return []

    def parse_points(element: ET.Element) -> list[BookNavigationItem]:
        result: list[BookNavigationItem] = []
        for point in element:
            if _local_name(point.tag) != "navpoint":
                continue
            label_element = next(
                (item for item in point.iter() if _local_name(item.tag) == "navlabel"),
                None,
            )
            content = next(
                (item for item in point if _local_name(item.tag) == "content"),
                None,
            )
            if content is None:
                continue
            href = _attribute(content, "src")
            path, fragment = _resolve_href(nav_path, href)
            result.append(
                BookNavigationItem(
                    label=_clean_text(label_element) if label_element is not None else "",
                    href=href,
                    resource_path=path,
                    fragment=fragment,
                    children=parse_points(point),
                )
            )
        return result

    return parse_points(nav_map)


def _flatten_navigation(items: list[BookNavigationItem]) -> list[BookNavigationItem]:
    result: list[BookNavigationItem] = []
    for item in items:
        result.append(item)
        result.extend(_flatten_navigation(item.children))
    return result


def _navigation_count(items: list[BookNavigationItem]) -> int:
    return len(_flatten_navigation(items))


def _unresolved_navigation(
    items: list[BookNavigationItem],
    names: set[str],
    fragments: dict[str, set[str]],
) -> list[str]:
    unresolved: list[str] = []
    for item in _flatten_navigation(items):
        if item.resource_path not in names:
            unresolved.append(item.href)
            continue
        if item.fragment and item.fragment not in fragments.get(item.resource_path, set()):
            unresolved.append(item.href)
    return unresolved
