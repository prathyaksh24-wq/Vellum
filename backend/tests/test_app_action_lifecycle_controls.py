from pathlib import Path

from agent.app_actions.lifecycle_controls import (
    PLUGIN_STATE_SET_ACTION_ID,
    SKILL_MUTATION_APPROVE_ACTION_ID,
    SKILL_MUTATION_SUBMIT_ACTION_ID,
    SKILL_UNINSTALL_ACTION_ID,
    LifecycleControlError,
    PluginSkillActionService,
)
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins.registry import PluginRegistry
from agent.profiles.policy import profile_policy


def _write_plugin(root: Path, plugin_id: str, *, required: bool = False) -> None:
    plugin = root / "connectors" / plugin_id
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        f"id: {plugin_id}\nname: {plugin_id.title()}\ntype: connector\ncategory: Connectors\nrequired: {'true' if required else 'false'}\n",
        encoding="utf-8",
    )


class Mutations:
    def __init__(self) -> None:
        self.calls = []

    def approve(self, mutation_id):
        self.calls.append(("approve", mutation_id))
        return {"ok": True, "name": "demo-skill", "status": "applied"}

    def reject(self, mutation_id):
        self.calls.append(("reject", mutation_id))
        return {"ok": True, "name": "demo-skill", "status": "rejected"}


class SkillSurface:
    def __init__(self) -> None:
        self.calls = []
        self.mutations = Mutations()

    def action(self, action, *, name):
        self.calls.append((action, name))
        return {"id": "mutation-1", "identity": name, "status": "pending"}


def _service(tmp_path, *, required=False):
    plugins = tmp_path / "plugins"
    _write_plugin(plugins, "demo", required=required)
    registry = PluginRegistry(plugins, state_path=tmp_path / "plugin-state.json")
    surface = SkillSurface()
    changed = []
    service = PluginSkillActionService(
        plugin_registry=registry,
        skill_surface_provider=lambda: surface,
        skill_hub_handler=lambda payload: {"id": "hub-mutation", "identity": payload.get("identifier") or payload.get("name"), "status": "pending"},
        uninstall_handler=lambda name: {"ok": True, "name": name, "snapshot": "snapshot-1"},
        plugin_state_changed=lambda: changed.append(True),
    )
    return service, registry, surface, changed


def _runtime(service):
    return AppActionRuntime(
        lifecycle_control_handler=lambda action_id, arguments, context, confirmed: service.execute(
            action_id,
            arguments,
            context,
            confirmed=confirmed,
        )
    )


def test_plugin_and_skill_controls_delegate_to_their_canonical_owners(tmp_path) -> None:
    service, registry, surface, changed = _service(tmp_path)
    runtime = _runtime(service)
    context = AppActionContext(source="ui")

    disabled = runtime.dispatch(
        AppActionRequest(action_id=PLUGIN_STATE_SET_ACTION_ID, arguments={"plugin_id": "demo", "enabled": False}),
        context,
    )
    archived = runtime.dispatch(
        AppActionRequest(action_id=SKILL_MUTATION_SUBMIT_ACTION_ID, arguments={"operation": "disable", "name": "demo-skill"}),
        context,
    )
    approved = runtime.dispatch(
        AppActionRequest(action_id=SKILL_MUTATION_APPROVE_ACTION_ID, arguments={"mutation_id": "mutation-1"}),
        context,
    )

    assert disabled.status == "applied"
    assert registry.is_enabled("demo") is False
    assert changed == [True]
    assert archived.result["mutation"]["status"] == "pending"
    assert surface.calls == [("archive", "demo-skill")]
    assert approved.status == "applied"
    assert surface.mutations.calls == [("approve", "mutation-1")]


def test_required_plugin_disable_fails_without_changing_registry_state(tmp_path) -> None:
    service, registry, _surface, changed = _service(tmp_path, required=True)
    receipt = _runtime(service).dispatch(
        AppActionRequest(action_id=PLUGIN_STATE_SET_ACTION_ID, arguments={"plugin_id": "demo", "enabled": False}),
        AppActionContext(source="nlp"),
    )

    assert receipt.status == "failed"
    assert receipt.error_code == "LIFECYCLE_ACTION_FAILED"
    assert registry.is_enabled("demo") is True
    assert changed == []


def test_profile_policy_can_deny_plugin_and_skill_lifecycle_actions(tmp_path) -> None:
    service, registry, _surface, changed = _service(tmp_path)
    runtime = _runtime(service)

    with profile_policy(profile_id="restricted", allowed_tools=frozenset()):
        receipt = runtime.dispatch(
            AppActionRequest(action_id=PLUGIN_STATE_SET_ACTION_ID, arguments={"plugin_id": "demo", "enabled": False}),
            AppActionContext(source="nlp"),
        )

    assert receipt.status == "unavailable"
    assert receipt.error_code == "ACTION_NOT_AUTHORIZED"
    assert registry.is_enabled("demo") is True
    assert changed == []


def test_skill_uninstall_is_bound_to_confirmation_and_reports_recovery_snapshot(tmp_path) -> None:
    service, _registry, _surface, _changed = _service(tmp_path)
    runtime = _runtime(service)
    request = AppActionRequest(action_id=SKILL_UNINSTALL_ACTION_ID, arguments={"name": "demo-skill"})
    context = AppActionContext(source="nlp")

    pending = runtime.dispatch(request, context)
    confirmed = runtime.confirm(pending.confirmation.token, request, context)

    assert pending.status == "confirmation_required"
    assert confirmed.status == "applied"
    assert confirmed.result["recoverable_snapshot"] == "snapshot-1"


def test_lifecycle_nlp_matching_is_explicit() -> None:
    runtime = AppActionRuntime(lifecycle_control_handler=lambda *_args: {})

    assert runtime.match_submission("disable the demo plugin").arguments == {"plugin_id": "demo", "enabled": False}
    assert runtime.match_submission("archive demo skill").arguments == {"operation": "archive", "name": "demo"}
    assert runtime.match_submission("approve skill mutation abc123").action_id == SKILL_MUTATION_APPROVE_ACTION_ID
    assert runtime.match_submission("install demo plugin") is None
    assert runtime.match_submission("Should I disable plugins I do not use?") is None
