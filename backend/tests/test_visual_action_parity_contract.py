"""Reviewable UI inventory must only claim actions in the live App Action catalog."""

import json
from itertools import product
from pathlib import Path

from agent.app_actions.models import AppActionContext, AppActionRequest, SurfacePresentation, WorkspaceLayoutSnapshot
from agent.app_actions.runtime import AppActionRuntime


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "frontend" / "ui" / "action-parity.inventory.json"


def test_covered_visual_controls_reference_registered_app_actions(monkeypatch, tmp_path) -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    from agent.plugins.registry import PluginRegistry
    runtime = AppActionRuntime(
        plugin_registry=PluginRegistry(ROOT / "plugins", state_path=tmp_path / "plugins.json"),
        session_control_handler=lambda *_args: {},
        settings_runtime_handler=lambda *_args: {},
        lifecycle_control_handler=lambda *_args: {},
        observability_handler=lambda *_args: {},
        coding_github_handler=lambda *_args: {},
        automation_handler=lambda *_args: {},
        knowledge_source_handler=lambda *_args: {},
    )
    from agent.plugins import google_calendar_controls, spotify_controls, youtube_controls
    monkeypatch.setattr(google_calendar_controls, "google_calendar_status", lambda: {"connected": True, "configured": True})
    runtime.register_plugin_contribution(google_calendar_controls.google_calendar_plugin_contribution())
    runtime.register_plugin_contribution(spotify_controls.spotify_plugin_contribution(authenticated=lambda: True))
    runtime.register_plugin_contribution(youtube_controls.youtube_plugin_contribution(
        status_provider=lambda: {"connected": True, "configured": True},
    ))
    from agent.plugins.google_workspace_controls import google_contribution
    from agent.plugins.linear_controls import linear_contribution
    from agent.plugins.product_hunt_controls import product_hunt_contribution
    from agent.plugins.github_controls import github_contribution
    from agent.plugins.slack_controls import slack_contribution
    runtime.register_plugin_contribution(google_contribution())
    runtime.register_plugin_contribution(linear_contribution())
    runtime.register_plugin_contribution(product_hunt_contribution())
    runtime.register_plugin_contribution(github_contribution())
    runtime.register_plugin_contribution(slack_contribution())
    from agent.plugins.airtable_controls import airtable_contribution
    runtime.register_plugin_contribution(airtable_contribution())
    from agent.plugins.notion_controls import notion_contribution
    runtime.register_plugin_contribution(notion_contribution())
    from agent.plugins.apify_controls import apify_contribution
    runtime.register_plugin_contribution(apify_contribution())
    from agent.plugins.serpapi_controls import serpapi_contribution
    runtime.register_plugin_contribution(serpapi_contribution())
    from agent.plugins.supabase_controls import supabase_contribution
    runtime.register_plugin_contribution(supabase_contribution())
    from agent.plugins.vercel_controls import vercel_contribution
    runtime.register_plugin_contribution(vercel_contribution())
    from agent.plugins.clickup_controls import clickup_contribution
    runtime.register_plugin_contribution(clickup_contribution())
    from agent.plugins.hubspot_controls import hubspot_contribution
    runtime.register_plugin_contribution(hubspot_contribution())
    from agent.plugins.exa_controls import exa_contribution
    runtime.register_plugin_contribution(exa_contribution())
    from agent.plugins.tavily_controls import tavily_contribution
    runtime.register_plugin_contribution(tavily_contribution())
    from agent.plugins.firecrawl_controls import firecrawl_contribution
    runtime.register_plugin_contribution(firecrawl_contribution())
    from agent.plugins.asana_controls import asana_contribution
    runtime.register_plugin_contribution(asana_contribution())
    from agent.plugins.swiggy_controls import swiggy_contribution
    runtime.register_plugin_contribution(swiggy_contribution())
    from agent.plugins.zomato_controls import zomato_contribution
    runtime.register_plugin_contribution(zomato_contribution())
    from agent.plugins.district_controls import district_contribution
    runtime.register_plugin_contribution(district_contribution())
    from agent.plugins.local_music_controls import local_music_contribution
    runtime.register_plugin_contribution(local_music_contribution())
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
