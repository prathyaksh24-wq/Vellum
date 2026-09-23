"""Reviewable UI inventory must only claim actions in the live App Action catalog."""

import json
from itertools import product
from pathlib import Path

from agent.app_actions.models import AppActionContext, AppActionRequest, SurfacePresentation, WorkspaceLayoutSnapshot
from agent.app_actions.runtime import AppActionRuntime


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "frontend" / "ui" / "action-parity.inventory.json"


def test_covered_visual_controls_reference_registered_app_actions() -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    runtime = AppActionRuntime(
        session_control_handler=lambda *_args: {},
        settings_runtime_handler=lambda *_args: {},
        lifecycle_control_handler=lambda *_args: {},
        observability_handler=lambda *_args: {},
        coding_github_handler=lambda *_args: {},
        automation_handler=lambda *_args: {},
        knowledge_source_handler=lambda *_args: {},
    )
    registered = {action.id for action in runtime.catalog().actions}
    assert inventory["covered"]
    assert len({(item["surface"], item["name"]) for item in inventory["covered"]}) == len(inventory["covered"])
    for item in inventory["covered"]:
        assert item["actionId"] in registered, item
        assert (ROOT / item["probe"]["path"]).is_file(), item


def test_visual_action_parity_deferrals_are_explicit() -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    assert inventory["exemptions"]
    assert inventory["deferred"]
    for item in inventory["deferred"]:
        assert item["surface"] and item["reason"]


def test_control_kernel_cannot_be_hidden_under_any_optional_layout() -> None:
    runtime = AppActionRuntime()
    control_kernel = [surface.reference for surface in runtime.catalog().surfaces if surface.control_kernel]
    assert set(control_kernel) == {"workspace", "composer", "composer.send"}

    for visibility in product((False, True), repeat=3):
        context = AppActionContext(
            source="ui",
            workspace_layout=WorkspaceLayoutSnapshot(surfaces={
                name: SurfacePresentation(visible=visible)
                for name, visible in zip(("sidebar", "settings", "right-panel"), visibility)
            }),
        )
        for reference in control_kernel:
            receipt = runtime.dispatch(
                AppActionRequest(action_id="ui.surface.configure", arguments={"reference": reference, "visible": False}),
                context,
            )
            assert receipt.error_code == "CONTROL_KERNEL_PROTECTED", (visibility, reference)

        reset = runtime.dispatch(AppActionRequest(action_id="ui.workspace.reset"), context)
        assert reset.status == "applied", visibility
        assert all(reset.result["workspace_layout_patch"]["surfaces"][reference]["visible"] for reference in control_kernel)
