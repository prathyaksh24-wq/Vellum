"""Local attachment preparation for UI and NLP App Action routes."""

from __future__ import annotations

import base64
import binascii
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import io
import mimetypes
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from agent.privacy.classifier import DataClass, classify


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_DATA_URL_CHARS = ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4 + 200
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".jsx",
    ".ts", ".tsx", ".css", ".sql", ".toml", ".ini", ".log", ".rst",
}
_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class ConversationAttachment(BaseModel):
    """Canonical attachment record shared by composer and model-content paths."""

    name: str = ""
    kind: str = "file"
    mime_type: str = ""
    size: str = ""
    size_bytes: int = Field(default=0, ge=0)
    digest: str = ""
    data_url: str | None = Field(default=None, max_length=MAX_DATA_URL_CHARS)
    text_content: str | None = Field(default=None, max_length=MAX_TEXT_BYTES)
    url: str | None = Field(default=None, max_length=4096)
    book_import_id: str = ""
    fresh: bool = True
    egress_scope: str = ""
    privacy_class: str = ""
    metadata_stripped: bool = False


class AttachmentImportError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class ClipboardPayload:
    text: str = ""
    files: tuple[Path, ...] = ()
    image_bytes: bytes = b""
    image_mime_type: str = ""


class AttachmentImportService:
    """Resolve intentional local sources without browsing the user's filesystem."""

    def __init__(
        self,
        *,
        clipboard_reader: Callable[[], ClipboardPayload] | None = None,
        granted_folders: Iterable[str | Path] = (),
        path_egress_allowed: Callable[[Path], bool] | None = None,
    ) -> None:
        self._clipboard_reader = clipboard_reader or _read_windows_clipboard
        self._granted_folders = tuple(Path(value).resolve() for value in granted_folders)
        self._path_egress_allowed = path_egress_allowed or (lambda _path: True)
        self._recent: dict[str, ConversationAttachment] = {}
        self._lock = Lock()

    def import_from_action(self, arguments: dict[str, Any], existing_digests: Iterable[str] = ()) -> dict[str, Any]:
        source = str(arguments.get("source") or "").strip().casefold()
        existing = {str(value).strip().casefold() for value in existing_digests if str(value).strip()}
        if source == "picker":
            return {
                "changed": False,
                "attachments": [],
                "client_effect": {"type": "attachment.picker.open", "accept": "supported"},
                "requires_user_selection": True,
                "message": "Choose a file to attach.",
            }
        if source == "clipboard":
            records = self._from_clipboard()
        elif source == "recent":
            reference = _clean_name(arguments.get("reference"))
            records = [self._recent_attachment(reference)]
        elif source == "path":
            records = [self._from_path(self._resolve_path(arguments))]
        else:
            raise AttachmentImportError("ATTACHMENT_SOURCE_REQUIRED", "Choose a file, clipboard, or recent attachment source.")

        for record in records:
            if record.digest.casefold() in existing:
                raise AttachmentImportError(
                    "ATTACHMENT_DUPLICATE",
                    f"{record.name} is already attached.",
                    details={"name": record.name, "digest": record.digest},
                )
        for record in records:
            self.remember(record)
        return {
            "changed": bool(records),
            "attachments": [record.model_dump(mode="json") for record in records],
            "requires_user_selection": False,
            "message": _attachment_message(records),
        }

    def remember(self, attachment: ConversationAttachment | dict[str, Any]) -> None:
        record = attachment if isinstance(attachment, ConversationAttachment) else ConversationAttachment.model_validate(attachment)
        if not record.name or not record.digest or not (record.data_url or record.text_content or record.book_import_id):
            return
        with self._lock:
            self._recent[record.name.casefold()] = record.model_copy(deep=True)

    def import_uploads(
        self,
        uploads: Iterable[dict[str, Any]],
        existing_digests: Iterable[str] = (),
    ) -> list[ConversationAttachment]:
        existing = {str(value).strip().casefold() for value in existing_digests if str(value).strip()}
        records: list[ConversationAttachment] = []
        total_bytes = 0
        for upload in uploads:
            name = _clean_name(upload.get("name"))
            mime_type = str(upload.get("mime_type") or "").strip().casefold()
            data_url = str(upload.get("data_url") or "")
            prefix = "data:" + mime_type + ";base64,"
            if not name or not mime_type or not data_url.startswith(prefix):
                raise AttachmentImportError("ATTACHMENT_UPLOAD_INVALID", "The selected attachment payload is invalid.")
            encoded = data_url[len(prefix):]
            if len(encoded) > ((MAX_ATTACHMENT_BYTES + 2) // 3) * 4:
                raise AttachmentImportError("ATTACHMENT_TOO_LARGE", f"{name} is larger than 10 MB.")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise AttachmentImportError("ATTACHMENT_UPLOAD_INVALID", f"{name} could not be decoded.") from exc
            total_bytes += len(content)
            if total_bytes > MAX_ATTACHMENT_BYTES:
                raise AttachmentImportError("ATTACHMENT_TOTAL_TOO_LARGE", "Attachments contain more than 10 MB in total.")
            record = self._from_bytes(name, content, mime_type)
            if record.digest.casefold() in existing or any(item.digest == record.digest for item in records):
                raise AttachmentImportError(
                    "ATTACHMENT_DUPLICATE",
                    f"{record.name} is already attached.",
                    details={"name": record.name, "digest": record.digest},
                )
            records.append(record)
        for record in records:
            self.remember(record)
        return records

    def _recent_attachment(self, reference: str) -> ConversationAttachment:
        with self._lock:
            if reference:
                exact = self._recent.get(reference.casefold())
                matches = [value for name, value in self._recent.items() if reference.casefold() in name]
            else:
                exact = None
                matches = list(reversed(self._recent.values()))[:1]
        if exact is not None:
            return exact.model_copy(deep=True)
        if len(matches) == 1:
            return matches[0].model_copy(deep=True)
        if not matches:
            raise AttachmentImportError("ATTACHMENT_RECENT_NOT_FOUND", "That recent attachment is unavailable. Choose it from the file picker.")
        raise AttachmentImportError("ATTACHMENT_RECENT_AMBIGUOUS", "More than one recent attachment matches that name.")

    def _resolve_path(self, arguments: dict[str, Any]) -> Path:
        raw = str(arguments.get("path") or "").strip().strip('"\'')
        if not raw:
            raise AttachmentImportError("ATTACHMENT_PATH_REQUIRED", "Provide an explicit file path.")
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            for root in self._granted_folders:
                if _is_within(resolved, root) and resolved.is_file():
                    return resolved
        else:
            for root in self._granted_folders:
                resolved = (root / candidate).resolve()
                if _is_within(resolved, root) and resolved.is_file():
                    return resolved
        raise AttachmentImportError(
            "ATTACHMENT_PATH_NOT_GRANTED",
            "Use an explicit file path or choose a file from a granted folder.",
        )

    def _from_path(self, path: Path) -> ConversationAttachment:
        if not path.exists():
            raise AttachmentImportError("ATTACHMENT_NOT_FOUND", f"{path.name or 'The file'} was not found.")
        if not path.is_file():
            raise AttachmentImportError("ATTACHMENT_NOT_A_FILE", "Only individual files can be attached.")
        if not self._path_egress_allowed(path):
            raise AttachmentImportError(
                "ATTACHMENT_FOLDER_POLICY_BLOCKED",
                f"{path.name} is local-only under its folder policy.",
            )
        size = path.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise AttachmentImportError("ATTACHMENT_TOO_LARGE", f"{path.name} is larger than 10 MB.")
        return self._from_bytes(path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "")

    def _from_clipboard(self) -> list[ConversationAttachment]:
        try:
            payload = self._clipboard_reader()
        except AttachmentImportError:
            raise
        except Exception as exc:
            raise AttachmentImportError("CLIPBOARD_UNAVAILABLE", "Clipboard content is unavailable.") from exc
        if payload.files:
            if len(payload.files) > 10:
                raise AttachmentImportError("ATTACHMENT_COUNT_EXCEEDED", "Attach no more than 10 clipboard files at once.")
            records = [self._from_path(Path(value).resolve()) for value in payload.files]
            if sum(record.size_bytes for record in records) > MAX_ATTACHMENT_BYTES:
                raise AttachmentImportError("ATTACHMENT_TOTAL_TOO_LARGE", "Attachments contain more than 10 MB in total.")
            return records
        if payload.image_bytes:
            return [self._from_bytes("Clipboard image.png", payload.image_bytes, payload.image_mime_type or "image/png")]
        if payload.text:
            return [self._from_bytes("Clipboard text.txt", payload.text.encode("utf-8"), "text/plain")]
        raise AttachmentImportError("CLIPBOARD_EMPTY", "The clipboard does not contain supported text, an image, or files.")

    @staticmethod
    def _from_bytes(name: str, content: bytes, mime_type: str) -> ConversationAttachment:
        size = len(content)
        if size > MAX_ATTACHMENT_BYTES:
            raise AttachmentImportError("ATTACHMENT_TOO_LARGE", f"{name} is larger than 10 MB.")
        suffix = Path(name).suffix.casefold()
        normalized_mime = mime_type.casefold().split(";", 1)[0].strip()
        digest = hashlib.sha256(content).hexdigest()
        common = {
            "name": _clean_name(name) or "Attachment",
            "mime_type": normalized_mime,
            "size": _format_size(size),
            "size_bytes": size,
            "digest": digest,
        }
        if normalized_mime in _IMAGE_MIMES:
            normalized, output_mime = _strip_image_metadata(content, normalized_mime)
            encoded = base64.b64encode(normalized).decode("ascii")
            image_common = {
                **common,
                "mime_type": output_mime,
                "size": _format_size(len(normalized)),
                "size_bytes": len(normalized),
                "digest": hashlib.sha256(normalized).hexdigest(),
            }
            return ConversationAttachment(
                **image_common,
                kind="image",
                data_url=f"data:{output_mime};base64,{encoded}",
                egress_scope="current_turn",
                privacy_class="binary_explicit",
                metadata_stripped=True,
            )
        if suffix == ".docx" or normalized_mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = _extract_docx(content)
            return _text_attachment(common, text)
        if suffix in _TEXT_EXTENSIONS or normalized_mime.startswith("text/") or normalized_mime in {"application/json", "application/xml", "application/yaml"}:
            if size > MAX_TEXT_BYTES:
                raise AttachmentImportError("ATTACHMENT_TEXT_TOO_LARGE", f"{name} contains more than 2 MB of text.")
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise AttachmentImportError("ATTACHMENT_ENCODING_UNSUPPORTED", f"{name} is not valid UTF-8 text.") from exc
            return _text_attachment(common, text)
        raise AttachmentImportError(
            "ATTACHMENT_TYPE_UNSUPPORTED",
            f"{name} is not a supported image, text file, or DOCX document.",
        )


def _extract_docx(content: bytes) -> str:
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            document = archive.getinfo("word/document.xml")
            if document.file_size > MAX_TEXT_BYTES:
                raise AttachmentImportError("ATTACHMENT_TEXT_TOO_LARGE", "The DOCX document contains more than 2 MB of text.")
            xml = archive.read(document)
    except (BadZipFile, KeyError) as exc:
        raise AttachmentImportError("ATTACHMENT_DOCUMENT_INVALID", "The DOCX document could not be read.") from exc
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AttachmentImportError("ATTACHMENT_DOCUMENT_INVALID", "The DOCX document could not be read.") from exc
    paragraphs = []
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if text:
            paragraphs.append(text)
    extracted = "\n".join(paragraphs).strip()
    if not extracted:
        raise AttachmentImportError("ATTACHMENT_DOCUMENT_EMPTY", "The DOCX document does not contain readable text.")
    if len(extracted.encode("utf-8")) > MAX_TEXT_BYTES:
        raise AttachmentImportError("ATTACHMENT_TEXT_TOO_LARGE", "The DOCX document contains more than 2 MB of text.")
    return extracted


def _text_attachment(common: dict[str, Any], text: str) -> ConversationAttachment:
    privacy_class, _reason = classify(text)
    if privacy_class is DataClass.RED:
        raise AttachmentImportError(
            "ATTACHMENT_WITHHELD",
            f"{common['name']} contains sensitive material that cannot be sent to an external model.",
        )
    return ConversationAttachment(
        **common,
        kind="document",
        text_content=text,
        egress_scope="current_turn",
        privacy_class=privacy_class.value,
        metadata_stripped=True,
    )


def _strip_image_metadata(content: bytes, mime_type: str) -> tuple[bytes, str]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            image.load()
            output = io.BytesIO()
            if mime_type == "image/jpeg":
                normalized = image.convert("RGB")
                normalized.save(output, format="JPEG", quality=95)
                return output.getvalue(), "image/jpeg"
            if mime_type == "image/webp":
                normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                normalized.save(output, format="WEBP", lossless=True)
                return output.getvalue(), "image/webp"
            normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            normalized.save(output, format="PNG")
            return output.getvalue(), "image/png"
    except Exception as exc:
        raise AttachmentImportError("ATTACHMENT_IMAGE_INVALID", "The image could not be read safely.") from exc


def _read_windows_clipboard() -> ClipboardPayload:
    try:
        from PIL import Image, ImageGrab

        grabbed = ImageGrab.grabclipboard()
        if isinstance(grabbed, list):
            return ClipboardPayload(files=tuple(Path(value) for value in grabbed))
        if isinstance(grabbed, Image.Image):
            stream = io.BytesIO()
            grabbed.save(stream, format="PNG")
            return ClipboardPayload(image_bytes=stream.getvalue(), image_mime_type="image/png")
    except Exception:
        pass
    if not hasattr(ctypes, "windll"):
        raise AttachmentImportError("CLIPBOARD_UNAVAILABLE", "Clipboard content is unavailable.")
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        raise AttachmentImportError("CLIPBOARD_UNAVAILABLE", "Clipboard content is unavailable.")
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ClipboardPayload()
        kernel32.GlobalLock.restype = ctypes.c_void_p
        pointer = kernel32.GlobalLock(wintypes.HGLOBAL(handle))
        if not pointer:
            return ClipboardPayload()
        try:
            return ClipboardPayload(text=ctypes.wstring_at(pointer))
        finally:
            kernel32.GlobalUnlock(wintypes.HGLOBAL(handle))
    finally:
        user32.CloseClipboard()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").strip().strip('"\'').split())[:255]


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _attachment_message(records: list[ConversationAttachment]) -> str:
    if len(records) == 1:
        return f"{records[0].name} attached."
    return f"{len(records)} items attached."


_service: AttachmentImportService | None = None


def get_attachment_import_service() -> AttachmentImportService:
    global _service
    if _service is None:
        _service = AttachmentImportService(path_egress_allowed=_default_path_egress_allowed)
    return _service


def _default_path_egress_allowed(path: Path) -> bool:
    from agent.config import get_settings
    from agent.obsidian.folder_policy import access_decision

    try:
        relative = path.resolve().relative_to(get_settings().obsidian_vault_path.resolve())
    except ValueError:
        return True
    return access_decision(relative).can_send_to_llm
