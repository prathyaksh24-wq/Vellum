from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

from agent import api
from agent.app_actions.attachments import (
    AttachmentImportError,
    AttachmentImportService,
    ClipboardPayload,
)
from agent.app_actions.models import AppActionContext
from agent.app_actions.runtime import ATTACHMENT_IMPORT_ACTION_ID, AppActionRuntime
import agent.skills.curator_runtime as curator_runtime


def _png_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (2, 2), color=(120, 30, 10)).save(stream, format="PNG", pnginfo=None)
    return stream.getvalue()


def _docx_bytes(text: str) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return stream.getvalue()


def test_explicit_path_produces_a_path_free_canonical_attachment(tmp_path: Path) -> None:
    folder = tmp_path / "research"
    folder.mkdir()
    source = folder / "notes.txt"
    source.write_text("A local research note.", encoding="utf-8")
    service = AttachmentImportService(granted_folders=(tmp_path,))

    result = service.import_from_action({"source": "path", "path": str(source)})
    attachment = result["attachments"][0]

    assert attachment["name"] == "notes.txt"
    assert attachment["text_content"] == "A local research note."
    assert attachment["egress_scope"] == "current_turn"
    assert attachment["metadata_stripped"] is True
    assert str(source) not in str(result)


def test_clipboard_text_and_docx_use_the_same_records() -> None:
    clipboard = AttachmentImportService(clipboard_reader=lambda: ClipboardPayload(text="Copied context"))
    copied = clipboard.import_from_action({"source": "clipboard"})["attachments"][0]
    uploaded = AttachmentImportService().import_uploads([{
        "name": "brief.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "data_url": "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"
        + base64.b64encode(_docx_bytes("Document context")).decode("ascii"),
    }])[0]

    assert copied["name"] == "Clipboard text.txt"
    assert copied["text_content"] == "Copied context"
    assert uploaded.kind == "document"
    assert uploaded.text_content == "Document context"


def test_image_metadata_is_removed_before_egress() -> None:
    source = _png_bytes()
    service = AttachmentImportService()
    attachment = service.import_uploads([{
        "name": "photo.png",
        "mime_type": "image/png",
        "data_url": "data:image/png;base64," + base64.b64encode(source).decode("ascii"),
    }])[0]

    assert attachment.kind == "image"
    assert attachment.metadata_stripped is True
    assert attachment.egress_scope == "current_turn"
    assert attachment.data_url.startswith("data:image/png;base64,")


def test_invalid_upload_base64_is_rejected() -> None:
    service = AttachmentImportService()

    with pytest.raises(AttachmentImportError) as invalid:
        service.import_uploads([{
            "name": "notes.txt",
            "mime_type": "text/plain",
            "data_url": "data:text/plain;base64,not-valid-base64!",
        }])

    assert invalid.value.code == "ATTACHMENT_UPLOAD_INVALID"


def test_duplicate_missing_unsupported_and_folder_policy_errors_are_typed(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("safe note", encoding="utf-8")
    service = AttachmentImportService(granted_folders=(tmp_path,))
    first = service.import_from_action({"source": "path", "path": str(source)})["attachments"][0]

    with pytest.raises(AttachmentImportError, match="already attached") as duplicate:
        service.import_from_action({"source": "path", "path": str(source)}, [first["digest"]])
    assert duplicate.value.code == "ATTACHMENT_DUPLICATE"

    with pytest.raises(AttachmentImportError) as missing:
        service.import_from_action({"source": "path", "path": str(tmp_path / "missing.txt")})
    assert missing.value.code == "ATTACHMENT_NOT_FOUND"

    binary = tmp_path / "archive.bin"
    binary.write_bytes(b"unsupported")
    with pytest.raises(AttachmentImportError) as unsupported:
        service.import_from_action({"source": "path", "path": str(binary)})
    assert unsupported.value.code == "ATTACHMENT_TYPE_UNSUPPORTED"

    blocked = AttachmentImportService(
        granted_folders=(tmp_path,),
        path_egress_allowed=lambda _path: False,
    )
    with pytest.raises(AttachmentImportError) as private:
        blocked.import_from_action({"source": "path", "path": str(source)})
    assert private.value.code == "ATTACHMENT_FOLDER_POLICY_BLOCKED"


def test_path_outside_granted_folder_is_rejected_before_filesystem_access(tmp_path: Path) -> None:
    granted = tmp_path / "granted"
    granted.mkdir()
    outside = tmp_path / "granted-private.txt"
    outside.write_text("private", encoding="utf-8")
    service = AttachmentImportService(granted_folders=(granted,))

    with pytest.raises(AttachmentImportError) as blocked:
        service.import_from_action({"source": "path", "path": str(outside)})

    assert blocked.value.code == "ATTACHMENT_PATH_NOT_GRANTED"
    with pytest.raises(AttachmentImportError) as traversal:
        service.import_from_action({"source": "path", "path": "../granted-private.txt"})
    assert traversal.value.code == "ATTACHMENT_PATH_NOT_GRANTED"


def test_attachment_nlp_matching_is_narrow_and_picker_is_a_client_effect() -> None:
    service = AttachmentImportService(clipboard_reader=lambda: ClipboardPayload(text="hello"))
    runtime = AppActionRuntime(attachment_importer=service.import_from_action)

    clipboard = runtime.match_submission("attach my copied text")
    picker = runtime.match_submission("add a document")

    assert clipboard.action_id == ATTACHMENT_IMPORT_ACTION_ID
    assert clipboard.arguments == {"source": "clipboard"}
    assert picker.arguments == {"source": "picker"}
    receipt = runtime.dispatch(picker, AppActionContext(source="nlp"))
    assert receipt.result["client_effect"]["type"] == "attachment.picker.open"
    assert runtime.match_submission("Explain how file attachments work") is None


@pytest.mark.asyncio
async def test_mixed_path_action_feeds_path_free_attachment_into_same_agent_turn(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "brief.txt"
    source.write_text("Quarterly plan", encoding="utf-8")
    service = AttachmentImportService(granted_folders=(tmp_path,))
    monkeypatch.setattr(curator_runtime, "get_curator_runtime", lambda: SimpleNamespace(mark_activity=lambda: None))
    monkeypatch.setattr(api, "_attachment_import_service", service)
    monkeypatch.setattr(api, "_app_action_runtime", AppActionRuntime(attachment_importer=service.import_from_action))
    async def passthrough(events, _audit):
        async for event in events:
            yield event

    monkeypatch.setattr(api, "_audited_turn_stream", passthrough)
    seen = []

    async def agent_stream(**kwargs):
        seen.append(kwargs)
        yield 'event: response.created\ndata: {"thread_id":"chat-1"}\n\n'
        yield 'event: response.completed\ndata: {"response":{"thread_id":"chat-1","output_text":"Summary","tools":[],"sources":[]}}\n\n'

    monkeypatch.setattr(api, "_stream_agent_turn", agent_stream)
    response = await api.chat_stream(api.ChatRequest(
        message=f'attach "{source}" and summarize it',
        thread_id="chat-1",
    ))
    body = "".join([chunk async for chunk in response.body_iterator])

    assert seen[0]["clean_message"] == "summarize it"
    assert seen[0]["attachments"][0].text_content == "Quarterly plan"
    assert str(source) not in seen[0]["clean_message"]
    assert "app.action.receipt" in body
