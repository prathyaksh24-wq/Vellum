from pathlib import Path

import pytest

from agent.app_actions.models import (
    AppActionContext,
    AppActionDefinition,
    AppActionRequest,
    SurfacePresentation,
    UISurfaceDefinition,
)
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins.contributions import (
    PluginActionContribution,
    PluginContribution,
    PluginContributionError,
    PluginSurfaceContribution,
)
from agent.plugins.portable import PortablePluginContext
from agent.plugins.registry import PluginRegistry, PluginRegistryError


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    capabilities: tuple[str, ...] = ("demo.run", "demo.view"),
    protected: bool = False,
) -> None:
    plugin = root / "connectors" / plugin_id
    plugin.mkdir(parents=True)
    capability_lines = "\n".join(f"  - {item}" for item in capabilities)
    (plugin / "plugin.yaml").write_text(
        f"id: {plugin_id}\n"
        f"name: {plugin_id.title()}\n"
        "type: connector\n"
        "category: Test\n"
        f"protected: {'true' if protected else 'false'}\n"
        "capabilities:\n"
        f"{capability_lines}\n",
        encoding="utf-8",
    )


def _action(plugin_id: str, *, adapter=True, action_id: str | None = None):
    definition = AppActionDefinition(
        id=action_id or f"{plugin_id}.run",
        version="1",
        owner=plugin_id,
        plugin_id=plugin_id,
        title="Run demo",
        description="Run the demo contribution.",
        scope="conversation",
        access_class="write",
        confirmation_rule="none",
        executor_location="server",
        supports_undo=False,
        idempotent=True,
        argument_schema={"type": "object"},
        result_schema={"type": "object"},
        ui_reference=f"{plugin_id}.panel",
        audit_label=f"{plugin_id}.run",
        required_permissions=["demo.run"],
    )

    def run(payload):
        return {
            "changed": True,
            "arguments": payload["arguments"],
            "_target_kind": "plugin_runtime",
            "_target_id": plugin_id,
            "_message": "Demo action ran.",
        }

    return PluginActionContribution(definition=definition, adapter=run if adapter else None)


def _surface(plugin_id: str, *, reference: str | None = None, control_kernel: bool = False):
    return PluginSurfaceContribution(
        definition=UISurfaceDefinition(
            reference=reference or f"{plugin_id}.panel",
            owner=plugin_id,
            plugin_id=plugin_id,
            title="Demo panel",
            aliases=["demo panel"],
            default_presentation=SurfacePresentation(visible=True, location="right"),
            supported_locations=["right", "left"],
            configurable_properties={"density": {"type": "string", "enum": ["quiet", "dense"]}},
            control_kernel=control_kernel,
            required_permissions=["demo.view"],
        )
    )


def _runtime(tmp_path: Path, *plugin_ids: str):
    root = tmp_path / "plugins"
    for plugin_id in plugin_ids:
        _write_plugin(root, plugin_id)
    registry = PluginRegistry(root, state_path=tmp_path / "plugin-state.json")
    return AppActionRuntime(plugin_registry=registry), registry


def test_enabled_contributions_project_and_dispatch_through_existing_registries(tmp_path: Path) -> None:
    runtime, registry = _runtime(tmp_path, "demo")
    portable_context = PortablePluginContext(
        contribution_registrar=runtime.register_plugin_contribution,
    )
    portable_context.register_contribution(PluginContribution(
        owner="demo",
        actions=(_action("demo"),),
        surfaces=(_surface("demo"),),
    ))
    first_chat = AppActionContext(source="nlp", invocation_conversation_id="chat-1")
    second_chat = AppActionContext(source="ui", invocation_conversation_id="chat-2")

    first_catalog = runtime.catalog(first_chat)
    receipt = runtime.dispatch(
        AppActionRequest(action_id="demo.run", arguments={"value": 3}),
        first_chat,
    )

    assert "demo.run" in {action.id for action in first_catalog.actions}
    assert "demo.panel" in {surface.reference for surface in first_catalog.surfaces}
    summary = runtime.plugin_contribution_summary("demo")
    assert summary["app_actions"][0]["required_permissions"] == ["demo.run"]
    assert summary["app_actions"][0]["available"] is True
    assert summary["ui_surfaces"][0]["available"] is True
    assert receipt.status == "applied"
    assert receipt.target.model_dump() == {"kind": "plugin_runtime", "id": "demo", "revision": None}
    assert receipt.result == {"changed": True, "arguments": {"value": 3}}
    assert len(portable_context.contributions) == 1

    registry.set_enabled("demo", False)
    assert "demo.run" not in {action.id for action in runtime.catalog(first_chat).actions}
    assert "demo.panel" not in {surface.reference for surface in runtime.catalog(second_chat).surfaces}
    assert runtime.plugin_contribution_summary("demo")["app_actions"][0]["available"] is False
    assert runtime.dispatch(AppActionRequest(action_id="demo.run"), first_chat).status == "unavailable"

    registry.set_enabled("demo", True)
    assert "demo.run" in {action.id for action in runtime.catalog(second_chat).actions}


def test_duplicate_and_control_kernel_identifiers_are_rejected(tmp_path: Path) -> None:
    runtime, _registry = _runtime(tmp_path, "demo", "other")
    runtime.register_plugin_contribution(PluginContribution(
        owner="demo",
        actions=(_action("demo"),),
        surfaces=(_surface("demo"),),
    ))

    with pytest.raises(PluginContributionError, match="already registered"):
        runtime.register_plugin_contribution(PluginContribution(
            owner="other",
            actions=(_action("other", action_id="demo.run"),),
        ))
    with pytest.raises(PluginContributionError, match="Control Kernel"):
        runtime.register_plugin_contribution(PluginContribution(
            owner="other",
            surfaces=(_surface("other", reference="composer", control_kernel=True),),
        ))


def test_missing_adapters_and_permissions_fail_truthfully(tmp_path: Path) -> None:
    runtime, _registry = _runtime(tmp_path, "demo")
    runtime.register_plugin_contribution(PluginContribution(
        owner="demo",
        actions=(_action("demo", adapter=False),),
    ))

    assert "demo.run" not in {action.id for action in runtime.catalog().actions}
    assert runtime.plugin_contribution_diagnostics() == [{
        "owner": "demo",
        "kind": "action",
        "identifier": "demo.run",
        "code": "MISSING_ACTION_ADAPTER",
    }]
    receipt = runtime.dispatch(AppActionRequest(action_id="demo.run"), AppActionContext(source="nlp"))
    assert (receipt.status, receipt.error_code) == ("unavailable", "ACTION_UNAVAILABLE")

    bad = _action("demo", action_id="demo.other")
    bad.definition.required_permissions = ["undeclared.permission"]
    with pytest.raises(PluginContributionError, match="not declared"):
        runtime.register_plugin_contribution(PluginContribution(owner="demo", actions=(bad,)))

    invalid_adapter = _action("demo", action_id="demo.invalid")
    object.__setattr__(invalid_adapter, "adapter", "not-callable")
    with pytest.raises(PluginContributionError, match="adapter must be callable"):
        runtime.register_plugin_contribution(PluginContribution(owner="demo", actions=(invalid_adapter,)))


def test_protected_plugin_surface_can_be_hidden_but_plugin_cannot_be_removed(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "builtin-ui", capabilities=("demo.view",), protected=True)
    registry = PluginRegistry(root, state_path=tmp_path / "plugin-state.json")
    runtime = AppActionRuntime(plugin_registry=registry)
    runtime.register_plugin_contribution(PluginContribution(
        owner="builtin-ui",
        surfaces=(_surface("builtin-ui"),),
    ))

    receipt = runtime.dispatch(
        AppActionRequest(
            action_id="ui.surface.configure",
            arguments={"reference": "builtin-ui.panel", "visible": False},
        ),
        AppActionContext(source="ui"),
    )

    assert receipt.status == "applied"
    assert receipt.result["presentation"]["visible"] is False
    assert registry.describe("builtin-ui")["protected"] is True
    with pytest.raises(PluginRegistryError, match="protected"):
        registry.assert_removable("builtin-ui")
