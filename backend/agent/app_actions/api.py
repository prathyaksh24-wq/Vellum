"""HTTP adapter for the App Action Runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agent.app_actions.attachments import MAX_DATA_URL_CHARS, AttachmentImportError, get_attachment_import_service

from agent.app_actions.models import (
    ActionReceipt,
    AppActionCatalog,
    AppActionCancelEnvelope,
    AppActionConfirmEnvelope,
    AppActionContext,
    AppActionDispatchEnvelope,
    AppActionRequest,
    AppActionUndoEnvelope,
)
from agent.app_actions.knowledge_sources import BOOK_IMPORT_ACTION_ID, _book_error_message, _default_book_library as _book_library
from agent.knowledge.runtime import get_knowledge_core
from agent.knowledge.book_library import RIGHTS_ATTESTATION_VERSION
from agent.knowledge.book_upload import prepare_book_upload, download_book_upload
from agent.app_actions.runtime import get_app_action_runtime


router = APIRouter(prefix="/app-actions", tags=["app-actions"])


def _finish_book_import(import_id: str) -> None:
    """Advance the existing durable Book stages after the upload response."""
    try:
        _book_library().materialize(import_id)
    except Exception as exc:
        # The retained EPUB remains readable; the existing Process control can
        # resume its canonical stages if processing or the server was interrupted.
        logging.getLogger(__name__).warning("Book processing remains pending for %s (%s)", import_id, type(exc).__name__)


def _queue_book_processing(receipt: ActionReceipt, background_tasks: BackgroundTasks) -> None:
    library = (receipt.result or {}).get("library") or {}
    if receipt.status == "applied" and library.get("processing_pending") and not library.get("already_present"):
        import_id = (library.get("book") or {}).get("id")
        if import_id:
            background_tasks.add_task(_finish_book_import, str(import_id))


class AttachmentUpload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=160)
    data_url: str = Field(min_length=1, max_length=MAX_DATA_URL_CHARS)


class AttachmentPrepareEnvelope(BaseModel):
    uploads: list[AttachmentUpload] = Field(min_length=1, max_length=10)
    existing_digests: list[str] = Field(default_factory=list, max_length=50)


@router.get("/catalog", response_model=AppActionCatalog)
def app_action_catalog() -> AppActionCatalog:
    return get_app_action_runtime().catalog()


@router.post("/attachments/prepare")
def prepare_attachments(envelope: AttachmentPrepareEnvelope) -> dict:
    try:
        attachments = get_attachment_import_service().import_uploads(
            [upload.model_dump(mode="json") for upload in envelope.uploads],
            envelope.existing_digests,
        )
    except AttachmentImportError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc), **exc.details},
        ) from exc
    return {"attachments": [attachment.model_dump(mode="json") for attachment in attachments]}


@router.post("/books/import", response_model=ActionReceipt)
async def import_book_action(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    rights_attestation_version: Annotated[str, Form(max_length=120)] = RIGHTS_ATTESTATION_VERSION,
    scan_approved: Annotated[bool, Form()] = True,
    local_only: Annotated[bool, Form()] = True,
    conversation_id: Annotated[str, Form(max_length=240)] = "",
    title: Annotated[str, Form(max_length=1000)] = "",
    author: Annotated[str, Form(max_length=300)] = "",
    cover: Annotated[UploadFile | None, File()] = None,
) -> ActionReceipt:
    """Move selected EPUB bytes into the same typed action used by chat."""

    maximum = get_knowledge_core().book_ingestion.policy.max_asset_bytes
    filename = str(file.filename or "")
    try:
        content = await file.read(maximum + 1)
    finally:
        await file.close()
    cover_bytes = b""
    if cover is not None:
        try:
            cover_bytes = await cover.read(6 * 1024 * 1024 + 1)
        finally:
            await cover.close()
    try:
        filename, content = await asyncio.to_thread(prepare_book_upload, filename, content, title=title, author=author, cover=cover_bytes)
    except (ValueError, OSError) as exc:
        code = str(exc) if str(exc).startswith("BOOK_") else "BOOK_UPLOAD_INVALID"
        raise HTTPException(status_code=422, detail={"code":code,"message":_book_error_message(code)}) from exc
    request = AppActionRequest(
        action_id=BOOK_IMPORT_ACTION_ID,
        arguments={
            "file_name": filename,
            "rights_attestation_version": RIGHTS_ATTESTATION_VERSION,
            "scan_approved": True,
            "local_only": local_only,
            "_content": content,
            "defer_processing": True,
        },
    )
    context = AppActionContext(source="ui", invocation_conversation_id=conversation_id.strip())
    receipt = await asyncio.to_thread(get_app_action_runtime().dispatch, request, context)
    _queue_book_processing(receipt, background_tasks)
    return receipt


class BookUrlImport(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    rights_attestation_version: str = Field(default=RIGHTS_ATTESTATION_VERSION, max_length=120)
    scan_approved: bool = True


@router.post("/books/import-url", response_model=ActionReceipt)
async def import_book_url_action(request: BookUrlImport, background_tasks: BackgroundTasks) -> ActionReceipt:
    try:
        filename, content, cover = await asyncio.to_thread(download_book_upload, request.url)
        filename, content = await asyncio.to_thread(prepare_book_upload, filename, content, cover=cover)
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("BOOK_") else "BOOK_URL_IMPORT_FAILED"
        raise HTTPException(status_code=422, detail={"code":code}) from exc
    receipt = await asyncio.to_thread(get_app_action_runtime().dispatch,
        AppActionRequest(action_id=BOOK_IMPORT_ACTION_ID, arguments={"file_name":filename,
            "_content":content, "rights_attestation_version":request.rights_attestation_version,
            "scan_approved":True, "local_only":True, "defer_processing":True}), AppActionContext(source="ui"))
    _queue_book_processing(receipt, background_tasks)
    return receipt


@router.post("/dispatch", response_model=ActionReceipt)
def dispatch_app_action(envelope: AppActionDispatchEnvelope) -> ActionReceipt:
    return get_app_action_runtime().dispatch(envelope.request, envelope.context)


@router.post("/undo", response_model=ActionReceipt)
def undo_app_action(envelope: AppActionUndoEnvelope) -> ActionReceipt:
    return get_app_action_runtime().undo(envelope.token, envelope.context)


@router.post("/confirm", response_model=ActionReceipt)
def confirm_app_action(envelope: AppActionConfirmEnvelope) -> ActionReceipt:
    return get_app_action_runtime().confirm(envelope.token, envelope.request, envelope.context)


@router.post("/cancel", response_model=ActionReceipt)
def cancel_app_action(envelope: AppActionCancelEnvelope) -> ActionReceipt:
    return get_app_action_runtime().cancel(envelope.token, envelope.context)
