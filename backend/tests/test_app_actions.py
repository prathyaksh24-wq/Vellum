from datetime import datetime, timezone

from agent.app_actions.models import (
    AppActionContext,
    AppActionRequest,
    SurfacePresentation,
    WorkspaceLayoutSnapshot,
)
from agent.app_actions.runtime import (
    AppActionRuntime,
    CONVERSATION_RENAME_ACTION_ID,
    SIDEBAR_ACTION_ID,
    SURFACE_ACTION_ID,
    WORKSPACE_RESET_ACTION_ID,
)


FIXED_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def layout_context(
    *,
    visible: bool = True,
    revision: int = 0,
    source: str = "nlp",
    surfaces: dict[str, SurfacePresentation] | None = None,
    focused: str = "",
    selected: str = "",
    visible_references: list[str] | None = None,
) -> AppActionContext:
    return AppActionContext(
        source=source,
        invocation_conversation_id="chat-1",
        workspace_layout=WorkspaceLayoutSnapshot(
            revision=revision,
            surfaces=surfaces or {"sidebar": SurfacePresentation(visible=visible)},
        ),
        focused_ui_reference=focused,
        selected_ui_reference=selected,
        visible_ui_references=visible_references or [],
    )


def runtime() -> AppActionRuntime:
    receipt_ids = iter([f"receipt-{index}" for index in range(1, 20)])
    undo_tokens = iter([f"undo-{index}" for index in range(1, 20)])
    return AppActionRuntime(
        clock=lambda: FIXED_NOW,
        receipt_id_factory=lambda: next(receipt_ids),
        undo_token_factory=lambda: next(undo_tokens),
    )


def test_catalog_exposes_actions_and_registered_surface_contracts() -> None:
    catalog = runtime().catalog()
    actions = {action.id: action for action in catalog.actions}
    surfaces = {surface.reference: surface for surface in catalog.surfaces}

    sidebar = actions[SIDEBAR_ACTION_ID]
    assert sidebar.executor_location == "client"
    assert sidebar.scope == "device"
    assert sidebar.supports_undo is True
    assert sidebar.argument_schema["required"] == ["visible"]
    assert sidebar.ui_reference == "sidebar"
    assert actions[SURFACE_ACTION_ID].supports_undo is True
    assert actions[WORKSPACE_RESET_ACTION_ID].ui_reference == "workspace-layout"

    assert set(surfaces) == {
        "workspace",
        "sidebar",
        "settings",
        "right-panel",
        "composer",
        "composer.send",
    }
    assert surfaces["workspace"].default_presentation.properties == {"theme": "dark"}
    assert surfaces["sidebar"].supported_locations == ["left"]
    assert surfaces["settings"].default_presentation.visible is False
    assert set(surfaces["composer.send"].configurable_properties) == {"label", "size"}
    assert surfaces["composer"].control_kernel is True


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
        "persistence": "device",
        "replace": False,
        "surfaces": {
            "sidebar": {"visible": True, "location": "left", "properties": {}},
        },
    }
    assert reused.status == "unavailable"
    assert reused.error_code == "UNDO_UNAVAILABLE"


def test_submission_matcher_handles_complete_presentation_instructions() -> None:
    subject = runtime()

    assert subject.match_submission("Hide the sidebar").arguments == {"visible": False}
    assert subject.match_submission("Could you please show my sidebar?").arguments == {"visible": True}
    assert subject.match_submission("turn sidebar off").arguments == {"visible": False}
    assert subject.match_submission("Use light mode").arguments == {
        "reference": "workspace",
        "properties": {"theme": "light"},
    }
    assert subject.match_submission("Temporarily open settings").arguments == {
        "reference": "settings",
        "persistence": "session",
        "visible": True,
    }
    assert subject.match_submission("make the input box bigger").arguments == {
        "reference": "composer",
        "properties": {"size": "large"},
    }
    assert subject.match_submission('change the send button text to "Run"').arguments == {
        "reference": "composer.send",
        "properties": {"label": "Run"},
    }
    assert subject.match_submission('Please rename my SEND BUTTON label TO "Go to Chat"').arguments == {
        "reference": "composer.send",
        "properties": {"label": "Go to Chat"},
    }
    assert subject.match_submission("reset my interface").action_id == WORKSPACE_RESET_ACTION_ID
    assert subject.match_submission("hide the sidebar and tell me the news") is None
    assert subject.match_submission("tell me how to hide a sidebar") is None
    assert subject.match_submission("I am typing hide the side") is None


def test_submission_planner_separates_multiple_actions_from_conversation() -> None:
    subject = runtime()

    planned = subject.plan_submission(
        "Hide the sidebar, open settings, and tell me today's Bitcoin news"
    )

    assert [request.action_id for request in planned.actions] == [
        SIDEBAR_ACTION_ID,
        SURFACE_ACTION_ID,
    ]
    assert planned.actions[0].arguments == {"visible": False}
    assert planned.actions[1].arguments == {"reference": "settings", "visible": True}
    assert planned.conversation_message == "tell me today's Bitcoin news"
    assert planned.is_mixed is True

    trailing = subject.plan_submission("What's new with Bitcoin and hide the sidebar")

    assert [request.action_id for request in trailing.actions] == [SIDEBAR_ACTION_ID]
    assert trailing.conversation_message == "What's new with Bitcoin"


def test_submission_planner_separates_conversation_from_free_form_action_arguments() -> None:
    subject = runtime()

    renamed = subject.plan_submission("Rename this chat to Alpha and tell me about Bitcoin")
    relabeled = subject.plan_submission(
        'Change the send button text to "Run" and summarize today\'s news'
    )

    assert [request.action_id for request in renamed.actions] == [CONVERSATION_RENAME_ACTION_ID]
    assert renamed.actions[0].arguments == {"title": "Alpha"}
    assert renamed.conversation_message == "tell me about Bitcoin"
    assert [request.action_id for request in relabeled.actions] == [SURFACE_ACTION_ID]
    assert relabeled.actions[0].arguments["properties"] == {"label": "Run"}
    assert relabeled.conversation_message == "summarize today's news"


def test_submission_planner_preserves_and_inside_an_unquoted_action_argument() -> None:
    subject = runtime()

    planned = subject.plan_submission("Rename this chat to Research and Development")

    assert [request.action_id for request in planned.actions] == [CONVERSATION_RENAME_ACTION_ID]
    assert planned.actions[0].arguments == {"title": "Research and Development"}
    assert planned.conversation_message == ""


def test_live_catalog_and_dispatch_reflect_current_action_availability() -> None:
    enabled = {SIDEBAR_ACTION_ID}
    subject = AppActionRuntime(
        action_availability=lambda definition, _context: definition.id in enabled,
    )
    request = subject.match_submission("hide the sidebar")

    assert [definition.id for definition in subject.catalog(layout_context()).actions] == [
        SIDEBAR_ACTION_ID,
    ]

    enabled.clear()
    unavailable = subject.dispatch(request, layout_context())

    assert subject.catalog(layout_context()).actions == []
    assert unavailable.status == "unavailable"
    assert unavailable.error_code == "ACTION_UNAVAILABLE"
    assert unavailable.message == "Set sidebar visibility is currently unavailable."

    enabled.add(SIDEBAR_ACTION_ID)
    applied = subject.dispatch(request, layout_context())

    assert applied.status == "applied"


def test_multiple_layout_actions_advance_the_context_revision_in_order() -> None:
    subject = runtime()
    requests = subject.plan_submission("hide the sidebar and open settings").actions

    receipts = subject.dispatch_many(requests, layout_context())

    assert [receipt.status for receipt in receipts] == ["applied", "applied"]
    assert [
        receipt.result["workspace_layout_patch"]["base_revision"]
        for receipt in receipts
    ] == [0, 1]
    assert receipts[1].result["workspace_layout_patch"]["surfaces"]["settings"]["visible"] is True


def test_generic_surface_action_supports_device_and_session_patches() -> None:
    subject = runtime()
    request = AppActionRequest(
        action_id=SURFACE_ACTION_ID,
        arguments={"reference": "composer.send", "properties": {"label": "Run", "size": "large"}},
    )
    device = subject.dispatch(request, layout_context(revision=2, source="ui"))
    session = subject.dispatch(
        request.model_copy(update={"arguments": {**request.arguments, "persistence": "session"}}),
        layout_context(revision=2, source="nlp"),
    )

    assert device.status == session.status == "applied"
    assert device.result["workspace_layout_patch"]["persistence"] == "device"
    assert session.result["workspace_layout_patch"]["persistence"] == "session"
    assert device.result["presentation"] == session.result["presentation"] == {
        "visible": True,
        "location": "composer-action",
        "properties": {"label": "Run", "size": "large"},
    }


def test_ambiguous_surface_reference_requests_clarification_without_a_patch() -> None:
    subject = runtime()
    request = subject.match_submission("show the panel")

    receipt = subject.dispatch(request, layout_context())

    assert receipt.status == "failed"
    assert receipt.error_code == "AMBIGUOUS_UI_REFERENCE"
    assert receipt.result == {"candidates": ["settings", "right-panel"]}
    assert "workspace_layout_patch" not in receipt.result
    assert receipt.undo is None


def test_visible_context_resolves_an_ambiguous_panel_reference() -> None:
    subject = runtime()
    request = subject.match_submission("show the panel")

    receipt = subject.dispatch(
        request,
        layout_context(visible_references=["workspace", "composer", "right-panel"]),
    )

    assert receipt.status == "applied"
    assert receipt.target.id == "right-panel"


def test_contextual_button_reference_requires_a_button_and_uses_selected_control() -> None:
    subject = runtime()
    request = subject.match_submission('change this button text to "Run"')

    missing = subject.dispatch(request, layout_context(focused="composer"))
    selected = subject.dispatch(request, layout_context(selected="composer.send"))

    assert missing.error_code == "UI_CONTEXT_REQUIRED"
    assert selected.status == "applied"
    assert selected.target.id == "composer.send"


def test_reset_restores_registered_defaults_and_clears_overrides_client_side() -> None:
    subject = runtime()
    context = layout_context(
        revision=8,
        surfaces={
            "workspace": SurfacePresentation(location="application", properties={"theme": "light"}),
            "sidebar": SurfacePresentation(visible=False, location="left"),
            "settings": SurfacePresentation(visible=True, location="overlay"),
            "right-panel": SurfacePresentation(visible=True, location="right"),
            "composer": SurfacePresentation(location="bottom", properties={"size": "large"}),
            "composer.send": SurfacePresentation(
                location="composer-action",
                properties={"label": "Run", "size": "large"},
            ),
        },
    )

    receipt = subject.dispatch(
        AppActionRequest(action_id=WORKSPACE_RESET_ACTION_ID),
        context,
    )

    patch = receipt.result["workspace_layout_patch"]
    assert receipt.status == "applied"
    assert patch["replace"] is True
    assert patch["revision"] == 9
    assert patch["surfaces"]["workspace"]["properties"] == {"theme": "dark"}
    assert patch["surfaces"]["sidebar"]["visible"] is True
    assert patch["surfaces"]["settings"]["visible"] is False
    assert patch["surfaces"]["composer.send"]["properties"] == {"label": "Send", "size": "medium"}


def test_control_kernel_and_property_allowlist_reject_invalid_mutations() -> None:
    subject = runtime()
    hidden_composer = subject.dispatch(
        AppActionRequest(
            action_id=SURFACE_ACTION_ID,
            arguments={"reference": "composer", "visible": False},
        ),
        layout_context(),
    )
    arbitrary_style = subject.dispatch(
        AppActionRequest(
            action_id=SURFACE_ACTION_ID,
            arguments={"reference": "sidebar", "properties": {"color": "red"}},
        ),
        layout_context(),
    )

    assert hidden_composer.error_code == "CONTROL_KERNEL_PROTECTED"
    assert arbitrary_style.error_code == "SURFACE_PROPERTY_NOT_ALLOWED"
    assert hidden_composer.authorization.decision == arbitrary_style.authorization.decision == "allowed"


def test_unknown_action_returns_an_unavailable_receipt() -> None:
    receipt = runtime().dispatch(
        AppActionRequest(request_id="unknown", action_id="ui.unknown", arguments={}),
        layout_context(),
    )

    assert receipt.status == "unavailable"
    assert receipt.error_code == "ACTION_UNAVAILABLE"
    assert receipt.authorization.decision == "denied"
