"""HTTP adapter for the App Action Runtime."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.app_actions.attachments import MAX_DATA_URL_CHARS, AttachmentImportError, get_attachment_import_service

from agent.app_actions.models import (
    ActionReceipt,
    AppActionCatalog,
    AppActionCancelEnvelope,
    AppActionConfirmEnvelope,
    AppActionDispatchEnvelope,
    AppActionUndoEnvelope,
)
from agent.app_actions.runtime import get_app_action_runtime


router = APIRouter(prefix="/app-actions", tags=["app-actions"])


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
