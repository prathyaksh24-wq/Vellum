"""Read-only presentation of validated EPUB assets, without a second book store."""

from __future__ import annotations

from base64 import b64encode
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import posixpath
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from agent.knowledge.book_documents import (
    BookDocumentError, _container_package_path, _local_name, _manifest,
    _metadata, _parse_xml, _reading_order,
)


SCHEMA_VERSION = "books-reader-v1"
MAX_SECTION_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_RENDER_BYTES = 32 * 1024 * 1024


class ReaderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReaderSection(ReaderModel):
    id: str
    title: str
    index: int


class BookReaderManifest(ReaderModel):
    schema_version: str = SCHEMA_VERSION
    book_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    sections: list[ReaderSection]


class BookReaderSection(ReaderModel):
    schema_version: str = SCHEMA_VERSION
    book_id: str
    section: ReaderSection
    html: str


class BookReaderText(ReaderModel):
    schema_version: str = SCHEMA_VERSION
    book_id: str
    content: str


class _BookText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p","div","section","h1","h2","h3","h4","li","blockquote","br","tr"}:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        self.handle_starttag(tag, [])

    def handle_data(self, data):
        self.parts.append(data)


def reader_text(path: Path, book_id: str) -> BookReaderText:
    pieces = []
    with ZipFile(path) as archive:
        _, manifest, order = _source(archive)
        for item in order:
            root = _xml(_read(archive, item.resource_path, MAX_SECTION_BYTES))
            parser = _BookText()
            parser.feed(_sanitized_html(root, archive, item.resource_path, manifest))
            pieces.append("".join(parser.parts).strip())
    return BookReaderText(book_id=book_id, content="\n\n".join(pieces))


def _section_id(path: str, position: int) -> str:
    return "section_" + sha256(f"{position}\x1f{path}".encode()).hexdigest()[:32]


def _read(archive: ZipFile, name: str, maximum: int) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > maximum or info.flag_bits & 1:
        raise ValueError("BOOK_READER_RESOURCE_TOO_LARGE")
    data = archive.read(info)
    if len(data) > maximum:
        raise ValueError("BOOK_READER_RESOURCE_TOO_LARGE")
    return data


def _xml(raw: bytes):
    # Use the canonical EPUB parser's XML boundary, including its entity policy.
    return _parse_xml(raw, reason_code="BOOK_READER_CONTENT_INVALID", stage="structured")


def _source(archive: ZipFile):
    package_path = _container_package_path(_xml(_read(archive, "META-INF/container.xml", 65536)))
    package = _xml(_read(archive, package_path, 2 * 1024 * 1024))
    manifest = _manifest(package, package_path)
    return _metadata(package, archive=archive, manifest=manifest), manifest, _reading_order(package, manifest)


def _title(root, index: int) -> str:
    for wanted in ({"h1", "h2"}, {"title"}):
        for element in root.iter():
            if _local_name(element.tag) in wanted:
                text = " ".join("".join(element.itertext()).split())
                if text:
                    return text[:1000]
    return f"Section {index + 1}"


def reader_manifest(path: Path, book_id: str) -> BookReaderManifest:
    with ZipFile(path) as archive:
        metadata, _, order = _source(archive)
        sections = [ReaderSection(id=_section_id(item.resource_path, index), index=index,
                                 title=_title(_xml(_read(archive, item.resource_path, MAX_SECTION_BYTES)), index))
                    for index, item in enumerate(order)]
        if not sections:
            raise ValueError("BOOK_READER_CONTENT_UNAVAILABLE")
        return BookReaderManifest(book_id=book_id, title=metadata.title or "Untitled book",
                                  authors=metadata.creators, sections=sections)


ALLOWED_TAGS = {
    "p", "div", "section", "article", "aside", "header", "footer", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u",
    "s", "small", "sub", "sup", "span", "br", "hr", "blockquote", "q",
    "pre", "code", "ol", "ul", "li", "dl", "dt", "dd", "table", "thead",
    "tbody", "tfoot", "tr", "td", "th", "caption", "figure", "figcaption",
    "a", "ruby", "rt", "rp", "abbr", "cite",
}
DROP_TAGS = {"script", "style", "template", "form", "input", "button", "iframe",
             "object", "embed", "audio", "video", "link", "meta", "foreignobject"}


def _sanitized_html(root, archive: ZipFile, resource_path: str, manifest) -> str:
    allowed_images = {item["path"] for item in manifest.values()
                      if item["media_type"] in {"image/png", "image/jpeg", "image/webp", "image/gif"}}
    budget = [0]

    def image(element) -> str:
        source = next((value for key, value in element.attrib.items()
                       if _local_name(key) in {"src", "href"}), "")
        parsed = urlsplit(source)
        alt = escape(element.attrib.get("alt", ""), quote=True)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return f"<span>{alt}</span>"
        name = posixpath.normpath(posixpath.join(posixpath.dirname(resource_path), unquote(parsed.path)))
        if name not in allowed_images:
            return f"<span>{alt}</span>"
        try:
            data = _read(archive, name, MAX_IMAGE_BYTES)
            with Image.open(BytesIO(data)) as picture:
                if picture.width * picture.height > 16_000_000:
                    return f"<span>{alt}</span>"
                media_type = {"PNG":"image/png", "JPEG":"image/jpeg", "WEBP":"image/webp", "GIF":"image/gif"}.get(picture.format)
                picture.verify()
            if not media_type:
                return f"<span>{alt}</span>"
        except (KeyError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            return f"<span>{alt}</span>"
        encoded = b64encode(data).decode("ascii")
        budget[0] += len(encoded)
        if budget[0] > MAX_RENDER_BYTES:
            raise ValueError("BOOK_READER_RESOURCE_TOO_LARGE")
        return f'<img alt="{alt}" src="data:{media_type};base64,{encoded}" loading="lazy"/>'

    def render(element) -> str:
        name = _local_name(element.tag)
        if name in DROP_TAGS:
            return ""
        if name in {"img", "image"}:
            return image(element)
        content = escape(element.text or "") + "".join(render(child) + escape(child.tail or "") for child in element)
        if name not in ALLOWED_TAGS:
            return content
        attributes = ""
        element_id = element.attrib.get("id")
        if element_id:
            attributes += f' id="{escape(element_id, quote=True)}"'
        # Only same-section fragment links can navigate inside the sandboxed page.
        if name == "a" and element.attrib.get("href", "").startswith("#"):
            attributes += f' href="{escape(element.attrib["href"], quote=True)}"'
        for key in ("colspan", "rowspan") if name in {"td", "th"} else ():
            value = element.attrib.get(key, "")
            if value.isdigit() and 1 <= int(value) <= 100:
                attributes += f' {key}="{int(value)}"'
        if name in {"br", "hr"}:
            return f"<{name}{attributes}/>"
        return f"<{name}{attributes}>{content}</{name}>"

    body = next((node for node in root.iter() if _local_name(node.tag) == "body"), root)
    html = render(body)
    if len(html.encode("utf-8")) > MAX_RENDER_BYTES:
        raise ValueError("BOOK_READER_RESOURCE_TOO_LARGE")
    return html


def reader_section(path: Path, book_id: str, section_id: str) -> BookReaderSection:
    with ZipFile(path) as archive:
        _, manifest, order = _source(archive)
        for index, item in enumerate(order):
            if _section_id(item.resource_path, index) != section_id:
                continue
            root = _xml(_read(archive, item.resource_path, MAX_SECTION_BYTES))
            return BookReaderSection(book_id=book_id,
                section=ReaderSection(id=section_id, index=index, title=_title(root, index)),
                html=_sanitized_html(root, archive, item.resource_path, manifest))
    raise KeyError("BOOK_READER_SECTION_NOT_FOUND")
