"""HTTP adapter for the App Action Runtime."""

from fastapi import APIRouter

from agent.app_actions.models import (
    ActionReceipt,
    AppActionCatalog,
    AppActionConfirmEnvelope,
    AppActionDispatchEnvelope,
    AppActionUndoEnvelope,
)
from agent.app_actions.runtime import get_app_action_runtime


router = APIRouter(prefix="/app-actions", tags=["app-actions"])


@router.get("/catalog", response_model=AppActionCatalog)
def app_action_catalog() -> AppActionCatalog:
    return get_app_action_runtime().catalog()


@router.post("/dispatch", response_model=ActionReceipt)
def dispatch_app_action(envelope: AppActionDispatchEnvelope) -> ActionReceipt:
    return get_app_action_runtime().dispatch(envelope.request, envelope.context)


@router.post("/undo", response_model=ActionReceipt)
def undo_app_action(envelope: AppActionUndoEnvelope) -> ActionReceipt:
    return get_app_action_runtime().undo(envelope.token, envelope.context)


@router.post("/confirm", response_model=ActionReceipt)
def confirm_app_action(envelope: AppActionConfirmEnvelope) -> ActionReceipt:
    return get_app_action_runtime().confirm(envelope.token, envelope.request, envelope.context)
