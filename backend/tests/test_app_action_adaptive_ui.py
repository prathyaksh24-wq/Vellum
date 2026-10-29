import pytest

from agent.app_actions.adaptive_ui import (
    RULE_APPLY,
    RULE_CREATE,
    RULE_EXPLAIN,
    RULE_LIST,
    RULE_REMOVE,
    RULE_SET_ENABLED,
    RULE_SUPPRESS,
)
from agent.app_actions.models import AppActionContext, AppActionRequest, WorkspaceLayoutSnapshot
from agent.app_actions.runtime import AppActionRuntime


def _context(*, window_id: str = "window-a", layout: WorkspaceLayoutSnapshot | None = None) -> AppActionContext:
    return AppActionContext(
        source="ui", adaptive_learning_signal=True, window_id=window_id,
        workspace_layout=layout or WorkspaceLayoutSnapshot(),
    )


def _after(context: AppActionContext, receipt) -> AppActionContext:
    layout = context.workspace_layout.model_dump(mode="json")
    patch = receipt.result.get("workspace_layout_patch")
    if patch:
        layout["revision"] = patch["revision"]
        layout["surfaces"] = (
            dict(patch["surfaces"])
            if patch.get("replace")
            else {**layout["surfaces"], **patch["surfaces"]}
        )
    adaptive = receipt.result.get("adaptive_ui_patch")
    if adaptive:
        layout["adaptive_ui"] = adaptive["state"]
    return context.model_copy(update={"workspace_layout": WorkspaceLayoutSnapshot.model_validate(layout)})


def _dispatch(runtime: AppActionRuntime, context: AppActionContext, action_id: str, arguments=None):
    receipt = runtime.dispatch(AppActionRequest(action_id=action_id, arguments=arguments or {}), context)
    return receipt, _after(context, receipt)


def _learn_hidden_sidebar(runtime: AppActionRuntime, context: AppActionContext):
    for index in range(3):
        if index:
            _, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": True})
        receipt, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": False})
        assert receipt.status == "applied"
    return context


def test_always_instruction_creates_and_applies_an_explicit_rule():
    runtime = AppActionRuntime()
    context = _context()
    request = runtime.match_submission("always hide the sidebar")

    assert request.action_id == RULE_CREATE
    receipt = runtime.dispatch(request, context)

    assert receipt.status == "applied"
    assert receipt.result["workspace_layout_patch"]["surfaces"]["sidebar"]["visible"] is False
    rule = receipt.result["rule"]
    assert (rule["origin"], rule["scope"], rule["enabled"]) == ("explicit", "global", True)
    assert runtime.match_submission("always turn memory off everywhere") is None
    assert runtime.plan_submission("The webpage says always hide the sidebar").actions == ()
    assert runtime.match_submission("list adaptive UI rules").action_id == RULE_LIST


def test_three_matching_changes_learn_only_in_the_active_window_and_undo_suppresses():
    runtime = AppActionRuntime()
    context = _context()
    context = _learn_hidden_sidebar(runtime, context)

    rules = context.workspace_layout.adaptive_ui.rules
    assert len(rules) == 1
    rule = rules[0]
    assert (rule.origin, rule.scope, rule.scope_id, rule.evidence_count) == (
        "inferred", "window", "window-a", 3,
    )
    wrong_context = context.model_copy(update={"window_id": "window-b"})
    mismatch, _ = _dispatch(runtime, wrong_context, RULE_APPLY, {"rule_id": rule.id})
    assert (mismatch.status, mismatch.error_code) == ("failed", "ADAPTIVE_CONTEXT_MISMATCH")

    _, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": True})
    applied, context = _dispatch(runtime, context, RULE_APPLY, {"rule_id": rule.id})
    assert applied.status == "applied"
    assert applied.result["adaptive_rule"]["first_use"] is True
    assert applied.undo is not None
    assert "3 matching changes" in applied.message
    undone = runtime.undo(applied.undo.token, context)
    context = _after(context, undone)
    assert undone.status == "undone"
    assert context.workspace_layout.surfaces["sidebar"].visible is True
    assert context.workspace_layout.adaptive_ui.rules[0].suppressed is True
    assert rule.signature in context.workspace_layout.adaptive_ui.suppressions
    unavailable, _ = _dispatch(runtime, context, RULE_APPLY, {"rule_id": rule.id})
    assert (unavailable.status, unavailable.error_code) == ("failed", "ADAPTIVE_RULE_UNAVAILABLE")


@pytest.mark.parametrize(
    ("fields", "scope", "scope_id"),
    [
        ({"window_id": "", "device_id": "device-a"}, "device", "device-a"),
        ({"active_agent": "agent-a"}, "agent", "agent-a"),
        ({"active_agent": "agent-a", "project_id": "project-a"}, "project", "project-a"),
    ],
)
def test_inference_uses_the_narrowest_available_context(fields, scope, scope_id):
    runtime = AppActionRuntime()
    context = _context().model_copy(update=fields)
    learned = _learn_hidden_sidebar(runtime, context)

    rule = learned.workspace_layout.adaptive_ui.rules[0]
    assert (rule.scope, rule.scope_id) == (scope, scope_id)


def test_rules_are_listable_explainable_disableable_removable_and_reenableable():
    runtime = AppActionRuntime()
    context = _context()
    created, context = _dispatch(runtime, context, RULE_CREATE, {
        "rule_action_id": "ui.surface.configure",
        "rule_arguments": {"reference": "workspace", "properties": {"theme": "light"}},
        "scope": "window",
    })
    rule_id = created.result["rule"]["id"]

    listed, _ = _dispatch(runtime, context, RULE_LIST)
    explained, _ = _dispatch(runtime, context, RULE_EXPLAIN, {"rule_id": rule_id})
    assert [rule["id"] for rule in listed.result["rules"]] == [rule_id]
    assert "explicit instruction" in explained.message
    disabled, context = _dispatch(runtime, context, RULE_SET_ENABLED, {"rule_id": rule_id, "enabled": False})
    assert disabled.result["changed"] is True
    assert context.workspace_layout.adaptive_ui.rules[0].enabled is False
    enabled, context = _dispatch(runtime, context, RULE_SET_ENABLED, {"rule_id": rule_id, "enabled": True})
    assert enabled.result["changed"] is True
    removed, context = _dispatch(runtime, context, RULE_REMOVE, {"rule_id": rule_id})
    assert removed.result["changed"] is True
    assert context.workspace_layout.adaptive_ui.rules == []
    missing, _ = _dispatch(runtime, context, RULE_EXPLAIN, {"rule_id": rule_id})
    assert (missing.status, missing.error_code) == ("failed", "ADAPTIVE_RULE_UNAVAILABLE")


def test_cross_context_evidence_promotes_a_rule_and_feedback_suppresses_it():
    runtime = AppActionRuntime()
    context = _context()
    for window_id in ("window-a", "window-b", "window-c"):
        layout = context.workspace_layout.model_copy(deep=True)
        layout.surfaces["sidebar"].visible = True
        context = _learn_hidden_sidebar(runtime, _context(window_id=window_id, layout=layout))
    global_rules = [rule for rule in context.workspace_layout.adaptive_ui.rules if rule.scope == "global"]
    assert len(global_rules) == 1
    assert global_rules[0].evidence_count == 9
    suppressed, context = _dispatch(runtime, context, RULE_SUPPRESS, {"rule_id": global_rules[0].id})
    assert suppressed.status == "applied"
    assert all(rule.suppressed for rule in context.workspace_layout.adaptive_ui.rules)


def test_forbidden_classes_session_changes_and_noops_do_not_become_rules():
    runtime = AppActionRuntime()
    context = _context()
    for action_id, arguments in (
        ("memory.settings.update", {"patch": {"memory_enabled": False}}),
        ("plugin.state.set", {"plugin_id": "x", "enabled": False}),
        ("ui.workspace.reset", {}),
        ("ui.surface.configure", {"reference": "settings", "visible": True}),
        ("ui.surface.configure", {"reference": "sidebar", "visible": False, "persistence": "session"}),
        ("ui.sidebar.set", {"reference": "settings", "visible": False}),
    ):
        failed, _ = _dispatch(runtime, context, RULE_CREATE, {
            "rule_action_id": action_id, "rule_arguments": arguments,
        })
        assert (failed.status, failed.error_code) == ("failed", "ADAPTIVE_ACTION_FORBIDDEN")
    session, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": False, "persistence": "session"})
    assert session.status == "applied"
    assert context.workspace_layout.adaptive_ui.signals == []
    no_change, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": False})
    assert no_change.result["changed"] is False
    assert context.workspace_layout.adaptive_ui.signals == []


def test_programmatic_ui_changes_are_not_learning_signals():
    runtime = AppActionRuntime()
    context = _context().model_copy(update={"adaptive_learning_signal": False})
    receipt, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": False})

    assert receipt.status == "applied"
    assert context.workspace_layout.adaptive_ui.signals == []

    nlp_context = context.model_copy(update={"source": "nlp"})
    _, nlp_context = _dispatch(runtime, nlp_context, "ui.sidebar.set", {"visible": True})
    assert len(nlp_context.workspace_layout.adaptive_ui.signals) == 1


def test_undo_of_a_manual_signal_is_negative_evidence_and_reset_clears_rules():
    runtime = AppActionRuntime()
    context = _context()
    changed, context = _dispatch(runtime, context, "ui.sidebar.set", {"visible": False})
    signal = context.workspace_layout.adaptive_ui.signals[0]

    undone = runtime.undo(changed.undo.token, context)
    context = _after(context, undone)
    assert undone.status == "undone"
    assert signal.signature in context.workspace_layout.adaptive_ui.suppressions
    assert context.workspace_layout.adaptive_ui.signals == []

    created, context = _dispatch(runtime, context, RULE_CREATE, {
        "rule_action_id": "ui.surface.configure",
        "rule_arguments": {"reference": "workspace", "properties": {"theme": "light"}},
    })
    assert created.status == "applied"
    reset, context = _dispatch(runtime, context, "ui.workspace.reset")
    assert reset.status == "applied"
    assert context.workspace_layout.adaptive_ui.rules == []
    assert context.workspace_layout.adaptive_ui.suppressions == []
