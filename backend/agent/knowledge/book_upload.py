"""Normalize the supplied import UI's local inputs into canonical EPUB intake."""
from __future__ import annotations

from html import escape
from io import BytesIO
import posixpath
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_STORED, ZIP_DEFLATED
import xml.etree.ElementTree as ET
import re

import httpx
from PIL import Image
from agent.knowledge.book_documents import _container_package_path, _local_name, _parse_xml

def _write(archive, name, content, compress_type=ZIP_DEFLATED):
    info=ZipInfo(name, date_time=(2000,1,1,0,0,0))
    archive.writestr(info,content,compress_type=compress_type)


OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"


def prepare_book_upload(filename: str, content: bytes, *, title: str = "", author: str = "", cover: bytes = b"") -> tuple[str, bytes]:
    suffix = Path(filename.strip()).suffix.casefold()
    if suffix not in {".epub", ".txt", ".md"}:
        raise ValueError("BOOK_UPLOAD_FORMAT_UNSUPPORTED")
    if not content or len(content) > 64 * 1024 * 1024:
        raise ValueError("BOOK_EPUB_TOO_LARGE" if content else "BOOK_EPUB_EMPTY")
    if suffix == ".epub":
        try:
            with ZipFile(BytesIO(content)) as archive:
                entries = archive.infolist()
                # Common EPUB repacks compress or move mimetype. Repair that
                # container detail rather than rejecting an otherwise readable book.
                if "mimetype" not in archive.namelist() or entries[0].filename != "mimetype" or entries[0].compress_type != ZIP_STORED:
                    output = BytesIO()
                    with ZipFile(output,"w") as target:
                        _write(target,"mimetype","application/epub+zip",compress_type=ZIP_STORED)
                        for info in entries:
                            if info.filename != "mimetype":
                                target.writestr(info,archive.read(info))
                    content = output.getvalue()
        except BadZipFile as exc:
            raise ValueError("BOOK_UPLOAD_INVALID") from exc
    if suffix != ".epub":
        try:
            text = content.decode("utf-8-sig").replace("\r\n", "\n").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("BOOK_TEXT_ENCODING_INVALID") from exc
        if len(text) < 40:
            raise ValueError("BOOK_TEXT_TOO_SHORT")
        title = title.strip() or Path(filename).stem or "Imported book"
        author = author.strip() or "Unknown"
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            _write(archive, "mimetype", "application/epub+zip", compress_type=ZIP_STORED)
            _write(archive, "META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
            _write(archive, "OPS/package.opf", f'<package xmlns="{OPF}" version="3.0"><metadata xmlns:dc="{DC}"><dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator><dc:language>und</dc:language></metadata><manifest><item id="body" href="body.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="body"/></spine></package>')
            blocks = "".join("<p>" + escape(part).replace("\n", "<br/>") + "</p>" for part in re.split(r"\n\s*\n", text))
            _write(archive, "OPS/body.xhtml", f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(title)}</title></head><body>{blocks}</body></html>')
        content = output.getvalue()
    if not title.strip() and not author.strip() and not cover:
        return Path(filename).stem + ".epub", content
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source:
        container = _parse_xml(source.read("META-INF/container.xml"), reason_code="BOOK_UPLOAD_INVALID", stage="identified")
        package_path = _container_package_path(container)
        package_bytes = source.read(package_path)
        if len(package_bytes) > 2 * 1024 * 1024:
            raise ValueError("BOOK_UPLOAD_INVALID")
        package = _parse_xml(package_bytes, reason_code="BOOK_UPLOAD_INVALID", stage="identified")
        metadata = next((element for element in package if _local_name(element.tag) == "metadata"), None)
        manifest = next((element for element in package if _local_name(element.tag) == "manifest"), None)
        if metadata is None or manifest is None:
            raise ValueError("BOOK_UPLOAD_INVALID")
        for field, value in (("title", title), ("creator", author)):
            if value.strip():
                for old in list(metadata):
                    if _local_name(old.tag) == field: metadata.remove(old)
                ET.SubElement(metadata, f"{{{DC}}}{field}").text = value.strip()
        cover_path = ""
        if cover:
            if len(cover) > 6 * 1024 * 1024:
                raise ValueError("BOOK_COVER_INVALID")
            with Image.open(BytesIO(cover)) as image:
                if image.width * image.height > 16_000_000 or image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("BOOK_COVER_INVALID")
                extension, media_type = {"PNG":("png","image/png"),"JPEG":("jpg","image/jpeg"),"WEBP":("webp","image/webp")}[image.format]
                image.verify()
            name = f"vellum-import-cover.{extension}"
            cover_path = posixpath.join(posixpath.dirname(package_path), name)
            for item in manifest:
                item.attrib["properties"] = " ".join(p for p in item.attrib.get("properties", "").split() if p != "cover-image")
            for element in metadata:
                if element.attrib.get("name") == "cover": element.attrib["content"] = "vellum-import-cover"
            ET.SubElement(manifest, f"{{{OPF}}}item", {"id":"vellum-import-cover","href":name,"media-type":media_type,"properties":"cover-image"})
        with ZipFile(output, "w") as target:
            for info in source.infolist():
                if info.filename == cover_path: continue
                target.writestr(info, ET.tostring(package, encoding="utf-8", xml_declaration=True) if info.filename == package_path else source.read(info))
            if cover_path: _write(target, cover_path, cover)
    return Path(filename).stem + ".epub", output.getvalue()


def download_book_upload(url: str) -> tuple[str, bytes, bytes]:
    """Bounded public-domain provider fetch; never an arbitrary URL proxy."""
    def checked(value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname not in {"www.gutenberg.org", "gutenberg.org", "standardebooks.org"} or parsed.port not in {None,443} or parsed.username or parsed.password:
            raise ValueError("BOOK_URL_PROVIDER_UNSUPPORTED")
        return parsed
    current = url
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            parsed = checked(current)
            with client.stream("GET", current) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers.get("location", "")); continue
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 64 * 1024 * 1024: raise ValueError("BOOK_EPUB_TOO_LARGE")
                    chunks.append(chunk)
                content = b"".join(chunks)
                media_type = response.headers.get("content-type", "").split(";")[0]
            filename = posixpath.basename(parsed.path) or "imported-book"
            if content.startswith(b"PK") or media_type == "application/epub+zip": filename = "imported-book.epub"
            elif media_type == "text/plain" or ".txt" in filename: filename = "imported-book.txt"
            else: raise ValueError("BOOK_UPLOAD_FORMAT_UNSUPPORTED")
            cover = b""
            match = re.search(r"/(?:cache/epub|ebooks)/(\d+)", parsed.path)
            if match and parsed.hostname in {"www.gutenberg.org","gutenberg.org"} and filename.endswith(".txt"):
                try:
                    with client.stream("GET", f"https://www.gutenberg.org/cache/epub/{match[1]}/pg{match[1]}.cover.medium.jpg") as image:
                        if image.status_code == 200:
                            data = bytearray()
                            for chunk in image.iter_bytes():
                                data.extend(chunk)
                                if len(data) > 6 * 1024 * 1024: raise ValueError("BOOK_COVER_INVALID")
                            cover = bytes(data)
                except (ValueError, httpx.HTTPError): pass
            return filename, content, cover
    raise ValueError("BOOK_URL_REDIRECT_LIMIT")
