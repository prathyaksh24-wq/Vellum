from datetime import datetime, timezone

from agent.app_actions.models import (
    AppActionContext,
    AppActionRequest,
    SurfacePresentation,
    WorkspaceLayoutSnapshot,
)
from agent.app_actions.runtime import AppActionRuntime, SIDEBAR_ACTION_ID


FIXED_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def layout_context(*, visible: bool, revision: int, source: str) -> AppActionContext:
    return AppActionContext(
        source=source,
        invocation_conversation_id="chat-1",
        workspace_layout=WorkspaceLayoutSnapshot(
            revision=revision,
            surfaces={"sidebar": SurfacePresentation(visible=visible)},
        ),
    )


def runtime() -> AppActionRuntime:
    receipt_ids = iter(["receipt-1", "receipt-2", "receipt-3", "receipt-4"])
    undo_tokens = iter(["undo-1", "undo-2", "undo-3"])
    return AppActionRuntime(
        clock=lambda: FIXED_NOW,
        receipt_id_factory=lambda: next(receipt_ids),
        undo_token_factory=lambda: next(undo_tokens),
    )


def test_catalog_exposes_typed_client_owned_sidebar_action() -> None:
    action = runtime().catalog().actions[0]

    assert action.id == SIDEBAR_ACTION_ID
    assert action.executor_location == "client"
    assert action.scope == "device"
    assert action.supports_undo is True
    assert action.argument_schema["required"] == ["visible"]
    assert action.ui_reference == "sidebar"


def test_ui_and_nlp_dispatch_cross_the_same_runtime_interface() -> None:
    subject = runtime()
    ui_receipt = subject.dispatch(
        AppActionRequest(request_id="ui-request", action_id=SIDEBAR_ACTION_ID, arguments={"visible": False}),
        layout_context(visible=True, revision=4, source="ui"),
    )
    nlp_receipt = subject.dispatch(
        AppActionRequest(request_id="nlp-request", action_id=SIDEBAR_ACTION_ID, arguments={"visible": False}),
        layout_context(visible=True, revision=4, source="nlp"),
    )

    assert ui_receipt.status == nlp_receipt.status == "applied"
    assert ui_receipt.action_id == nlp_receipt.action_id == SIDEBAR_ACTION_ID
    assert ui_receipt.result == nlp_receipt.result
    assert ui_receipt.target == nlp_receipt.target
    assert ui_receipt.authorization.agent_name == "VellumUI"
    assert nlp_receipt.authorization.agent_name == "VellumAgent"
    assert ui_receipt.authorization.decision == nlp_receipt.authorization.decision == "allowed"
    assert ui_receipt.undo is not None
    assert nlp_receipt.undo is not None


def test_undo_restores_previous_sidebar_state_and_rejects_reuse() -> None:
    subject = runtime()
    applied = subject.dispatch(
        AppActionRequest(request_id="hide", action_id=SIDEBAR_ACTION_ID, arguments={"visible": False}),
        layout_context(visible=True, revision=0, source="nlp"),
    )

    undone = subject.undo(
        applied.undo.token,
        layout_context(visible=False, revision=1, source="ui"),
    )
    reused = subject.undo(
        applied.undo.token,
        layout_context(visible=True, revision=2, source="ui"),
    )

    assert undone.status == "undone"
    assert undone.result["workspace_layout_patch"] == {
        "version": 1,
        "base_revision": 1,
        "revision": 2,
        "surfaces": {"sidebar": {"visible": True}},
    }
    assert reused.status == "unavailable"
    assert reused.error_code == "UNDO_UNAVAILABLE"


def test_submission_matcher_only_handles_complete_sidebar_instructions() -> None:
    subject = runtime()

    assert subject.match_submission("Hide the sidebar").arguments == {"visible": False}
    assert subject.match_submission("Could you please show my sidebar?").arguments == {"visible": True}
    assert subject.match_submission("turn sidebar off").arguments == {"visible": False}
    assert subject.match_submission("hide the sidebar and tell me the news") is None
    assert subject.match_submission("tell me how to hide a sidebar") is None
    assert subject.match_submission("I am typing hide the side") is None


def test_unknown_action_returns_an_unavailable_receipt() -> None:
    receipt = runtime().dispatch(
        AppActionRequest(request_id="unknown", action_id="ui.unknown", arguments={}),
        layout_context(visible=True, revision=0, source="nlp"),
    )

    assert receipt.status == "unavailable"
    assert receipt.error_code == "ACTION_UNAVAILABLE"
    assert receipt.authorization.decision == "denied"
