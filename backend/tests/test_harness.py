from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from pydantic import BaseModel

from agent.harness.manager import PluginManager
from agent.harness.patch import PatchError, compose, parse_layer
from agent.harness.runtime import Harness, HarnessError, Plugin


# --------------------------------------------------------------------------- dialect


def test_patch_dialect_insert_target_and_wholesale_config():
    base = parse_layer([{"insert": [{"id": "a", "name": "p", "config": {"x": 1, "y": 2}}]}], "base")
    bundle = parse_layer([{"id": "a", "config": {"x": 9}}, {"id": "missing", "disabled": True}], "bundle:b")
    rows, warnings = compose([base, bundle])
    assert rows[0].config == {"x": 9}  # replaced wholesale, never deep-merged
    assert rows[0].overridden_by == ["bundle:b"]
    assert any("missing" in w for w in warnings)


def test_patch_name_asserts_rather_than_renames():
    base = parse_layer([{"insert": [{"id": "a", "name": "p"}]}], "base")
    other = parse_layer([{"id": "a", "name": "q", "disabled": True}], "profile")
    rows, warnings = compose([base, other])
    assert rows[0].name == "p" and rows[0].disabled is False
    assert warnings


def test_patch_rejects_unknown_fields():
    with pytest.raises(PatchError):
        parse_layer([{"id": "a", "colour": "red"}], "profile")


# --------------------------------------------------------------------------- runtime


class CounterConfig(BaseModel):
    value: int = 0


def _harness(tmp_path: Path, applied: list, disposed: list) -> Harness:
    def apply(ctx, config):
        applied.append((ctx.entry.id, config.value))
        ctx.effect(lambda: disposed.append(ctx.entry.id))

    base = tmp_path / "base.patch.yml"
    base.write_text("- insert:\n    - id: counter\n      name: '@test/counter'\n      config: {value: 1}\n"
                    "    - id: other\n      name: '@test/counter'\n", encoding="utf-8")
    harness = Harness(tmp_path / "h", base, [Plugin(name="@test/counter", config=CounterConfig, apply=apply, client="builtin")])
    harness.recompose("boot")
    return harness


def _bundle(directory: Path, name: str, patch: str, *, client: str | None = None, host: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    vellum: dict = {"bundle": {"patch": "./harness.patch.yml"}}
    if client is not None:
        (directory / "client.js").write_text(client, encoding="utf-8")
        vellum["client"] = {"entry": "./client.js"}
    if host is not None:
        (directory / "index.py").write_text(host, encoding="utf-8")
        vellum["host"] = {"entry": "./index.py"}
    (directory / "package.json").write_text(json.dumps({"name": name, "version": "1.0.0", "vellum": vellum}), encoding="utf-8")
    (directory / "harness.patch.yml").write_text(patch, encoding="utf-8")
    return directory


def test_recompose_hot_reloads_only_changed_entries(tmp_path):
    applied, disposed = [], []
    harness = _harness(tmp_path, applied, disposed)
    assert applied == [("counter", 1), ("other", 0)]
    harness.edit_config("counter", lambda current: {**current, "value": 5})
    assert disposed == ["counter"]
    assert applied[-1] == ("counter", 5)
    assert harness.config_of("counter") == {"value": 5}
    assert "value: 5" in harness.profile_patch.read_text(encoding="utf-8")


def test_invalid_config_is_an_error_phase_not_a_crash(tmp_path):
    harness = _harness(tmp_path, [], [])
    harness.write_profile_patches([{"id": "counter", "config": {"value": "lots"}}])
    harness.recompose()
    assert harness.entry("counter").phase == "error"
    assert "value" in harness.entry("counter").error
    assert harness.is_active("other")


def test_install_bundle_overrides_rows_inserts_plugins_and_removes_cleanly(tmp_path):
    applied, disposed = [], []
    harness = _harness(tmp_path, applied, disposed)
    manager = PluginManager(harness)
    host = ("STARTED = []\n"
            "def apply(ctx, config):\n"
            "    STARTED.append(1)\n"
            "    ctx.provide('greeter', 'hi')\n")
    source = _bundle(harness.workspace_dir / "greeter", "@local/greeter",
                     "- id: counter\n  config: {value: 7}\n- insert:\n    - id: greeter\n      name: '@local/greeter'\n",
                     client="window.__VellumModuleLoader__.load({id:'@local/greeter',factory(){return {apply(){}}}})\n",
                     host=host)
    result = manager.install_bundle(str(source))
    assert result["application"] == "applied"
    assert {row["id"] for row in result["rows"]} == {"counter", "greeter"}
    assert harness.config_of("counter") == {"value": 7}
    assert harness.services["greeter"] == "hi"
    payload = harness.client_payload()
    greeter = next(e for e in payload["entries"] if e["id"] == "greeter")
    assert greeter["module"].startswith("/api/harness/bundles/@local/greeter/client")

    removed = manager.remove_bundle("@local/greeter")
    assert removed["application"] == "applied"
    assert "greeter" not in harness.services
    assert harness.config_of("counter") == {"value": 1}
    assert not harness.bundle_dir("@local/greeter").exists()


def test_bundle_without_effect_reports_next_step(tmp_path):
    harness = _harness(tmp_path, [], [])
    source = _bundle(harness.workspace_dir / "noop", "@local/noop", "- id: does-not-exist\n  disabled: true\n")
    result = PluginManager(harness).install_bundle(str(source))
    assert result["application"] == "no-effect"
    assert "nextStep" in result


def test_bundle_with_bad_host_code_fails_before_install(tmp_path):
    harness = _harness(tmp_path, [], [])
    source = _bundle(harness.workspace_dir / "bad", "@local/bad", "- insert:\n    - id: bad\n      name: '@local/bad'\n",
                     host="def apply(ctx, config)\n    pass\n")
    with pytest.raises(HarnessError) as error:
        PluginManager(harness).install_bundle(str(source))
    assert error.value.code == "SYNTAX_ERROR"
    assert not harness.bundle_dir("@local/bad").exists()


def test_install_needs_an_absolute_bundle_directory(tmp_path):
    harness = _harness(tmp_path, [], [])
    with pytest.raises(HarnessError) as error:
        PluginManager(harness).install_bundle("relative/dir")
    assert error.value.code == "INVALID_SPEC"


def test_set_plugin_records_only_departures(tmp_path):
    harness = _harness(tmp_path, [], [])
    manager = PluginManager(harness)
    assert manager.set_plugin("other", False)["application"] == "applied"
    assert harness.entry("other").phase == "disabled"
    assert harness.read_profile_patches() == [{"id": "other", "disabled": True}]
    manager.set_plugin("other", True)
    assert harness.read_profile_patches() == []
    assert harness.is_active("other")


def test_set_bundle_off_and_on(tmp_path):
    harness = _harness(tmp_path, [], [])
    manager = PluginManager(harness)
    source = _bundle(harness.workspace_dir / "seven", "@local/seven", "- id: counter\n  config: {value: 7}\n")
    manager.install_bundle(str(source))
    manager.set_bundle("@local/seven", False)
    assert harness.config_of("counter") == {"value": 1}
    manager.set_bundle("@local/seven", True)
    assert harness.config_of("counter") == {"value": 7}


def test_approval_blocks_until_resolved(tmp_path):
    harness = _harness(tmp_path, [], [])
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.setdefault("status", harness.request_approval("Install x", {})))
    worker.start()
    for _ in range(100):
        if harness.pending_approvals():
            break
        time.sleep(0.01)
    pending = harness.pending_approvals()
    assert len(pending) == 1 and outcome == {}
    harness.resolve_approval(pending[0]["id"], True)
    worker.join(2)
    assert outcome["status"] == "approved"


def test_approval_expires(tmp_path):
    harness = _harness(tmp_path, [], [])
    assert harness.request_approval("x", {}, timeout=0.01) == "expired"


# --------------------------------------------------------------------------- tools


@pytest.fixture()
def live_harness(tmp_path, monkeypatch):
    from agent import harness as harness_module

    monkeypatch.setenv("VELLUM_HARNESS_DIR", str(tmp_path / "harness"))
    harness_module.reset_harness()
    yield harness_module.get_harness()
    harness_module.reset_harness()


def test_shipped_composition_starts(live_harness):
    phases = {fid: f.phase for fid, f in live_harness.fibers.items()}
    assert phases["ui-analytics"] == "active"
    assert phases["tool-harness-inspect"] == "active"
    assert live_harness.config_of("ui-analytics") == {"placement": "settings"}
    names = {e["name"] for e in live_harness.client_payload()["entries"]}
    assert {"@vellum/ui-analytics", "@vellum/ui-background"} <= names


def test_inspect_directory_and_config_schema(live_harness):
    from agent.tools.harness import harness_inspect

    directory = json.loads(harness_inspect(None))
    providers = {(p["platform"], p["provider"]) for p in directory["providers"]}
    assert {("host", "Config"), ("host", "Runtime"), ("client", "Slots")} <= providers
    config = json.loads(harness_inspect({"platform": "host", "provider": "Config", "method": "getConfig",
                                         "input": {"id": "ui-analytics"}}))
    assert config["schema"]["properties"]["placement"]["enum"] == ["settings", "sidebar", "both"]
    assert config["value"] == {"placement": "settings"}
    missing = json.loads(harness_inspect({"platform": "host", "provider": "Config", "method": "nope"}))
    assert missing["error"]["code"] == "INSPECT_TARGET_NOT_FOUND"


def test_client_queries_need_a_connected_page(live_harness):
    from agent.tools.harness import harness_inspect

    answer = json.loads(harness_inspect({"platform": "client", "provider": "Slots", "method": "listSubTree"}))
    assert answer["error"]["code"] == "CLIENT_UNAVAILABLE"
    live_harness.set_client_manifest({"slots": [{"name": "shell.background", "cardinality": "single", "registrations": []}]})
    answer = json.loads(harness_inspect({"platform": "client", "provider": "Slots", "method": "listSubTree",
                                         "input": {"name": "shell.background"}}))
    assert answer["cardinality"] == "single"


def test_plugin_manager_tool_waits_for_approval_then_applies(live_harness):
    from agent.tools.harness import plugin_manager, workspace_files

    workspace_files("write", "move-analytics/package.json", json.dumps(
        {"name": "@local/move-analytics", "version": "1.0.0", "vellum": {"bundle": {"patch": "./harness.patch.yml"}}}))
    written = json.loads(workspace_files("write", "move-analytics/harness.patch.yml",
                                         "- id: ui-analytics\n  config:\n    placement: sidebar\n"))
    directory = str(Path(written["absolutePath"]).parent)

    def approve_when_asked():
        for _ in range(200):
            pending = live_harness.pending_approvals()
            if pending:
                assert pending[0]["details"]["bundle"] == "@local/move-analytics"
                live_harness.resolve_approval(pending[0]["id"], True)
                return
            time.sleep(0.01)

    approver = threading.Thread(target=approve_when_asked)
    approver.start()
    result = json.loads(plugin_manager("install_bundle", directory))
    approver.join(3)
    assert result["application"] == "applied"
    assert live_harness.config_of("ui-analytics") == {"placement": "sidebar"}


def test_plugin_manager_denied_changes_nothing(live_harness):
    from agent.tools.harness import plugin_manager

    threading.Thread(target=lambda: (time.sleep(0.05), live_harness.resolve_approval(
        live_harness.pending_approvals()[0]["id"], False))).start()
    result = json.loads(plugin_manager("set_plugin", "ui-analytics", enabled=False))
    assert result["application"] == "not-applied" and result["approval"] == "denied"
    assert live_harness.is_active("ui-analytics")


def test_workspace_is_confined(live_harness):
    from agent.tools.harness import workspace_files

    answer = json.loads(workspace_files("write", "../escape.txt", "x"))
    assert answer["error"]["code"] == "OUTSIDE_WORKSPACE"


# --------------------------------------------------------------------------- agent integration


def test_skill_named_tool_call_is_repaired_into_skill_view(monkeypatch):
    from langchain_core.messages import AIMessage
    from agent.graph import agent as graph_agent

    class Entry:
        def __init__(self, name):
            self.name = name

    class Registry:
        def list_skills(self):
            return [Entry("vellum-harness")]

    monkeypatch.setattr(graph_agent, "_prompt_skill_registry", Registry())
    monkeypatch.setattr(graph_agent, "_all_runtime_tools", lambda: ([], set()))
    message = AIMessage(content="", tool_calls=[
        {"id": "1", "name": "vellum_harness", "args": {"query": "move analytics"}},
        {"id": "2", "name": "web_search", "args": {"query": "x"}},
    ])
    repaired = graph_agent._repair_skill_calls(message)
    assert repaired.tool_calls[0]["name"] == "skill_view"
    assert repaired.tool_calls[0]["args"] == {"name": "vellum-harness"}
    assert repaired.tool_calls[1]["name"] == "web_search"


def test_a_vellum_tab_is_not_a_browser_request():
    from agent.agents.browser import BrowserAgent

    agent = BrowserAgent.__new__(BrowserAgent)
    assert not agent.can_handle("Bring the Analytics tab out of Settings and put it in the main sidebar.")
    assert agent.can_handle("close this tab")
    assert agent.can_handle("show me my browser tabs")
    assert agent.can_handle("open a new tab")


def test_full_access_applies_without_an_approval(live_harness):
    from agent.tools.harness import plugin_manager

    live_harness.set_full_access(True)
    result = json.loads(plugin_manager("set_plugin", "ui-analytics", enabled=False))
    assert result["application"] == "applied"
    assert live_harness.pending_approvals() == []
    live_harness.set_full_access(False)
    assert live_harness.full_access is False


def test_self_changes_switch_is_a_shipped_client_plugin(live_harness):
    names = {e["name"] for e in live_harness.client_payload()["entries"]}
    assert "@vellum/ui-self-changes" in names


def test_an_announcement_without_action_is_nudged_once():
    from langchain_core.messages import AIMessage, HumanMessage
    from agent.graph import agent as graph_agent

    human = HumanMessage(content="What did I watch on YouTube recently?", id="h1")
    announced = AIMessage(content="I'll start by looking for the relevant tools to check your watch history.")
    assert graph_agent._announced_without_acting({"messages": [human, announced]})
    assert not graph_agent._announced_without_acting({"messages": [human, announced], "vellum_nudged_for": "h1"})
    asked = AIMessage(content="I'll need your channel. Which account should I check?")
    assert not graph_agent._announced_without_acting({"messages": [human, asked]})
    answered = AIMessage(content="You watched three videos about chess openings.")
    assert not graph_agent._announced_without_acting({"messages": [human, answered]})


def test_local_models_get_a_longer_stream_idle_window(monkeypatch):
    from types import SimpleNamespace
    from agent import api
    import agent.llm.providers as providers

    entries = {"ollama/gemma4:12b": SimpleNamespace(provider="ollama"),
               "openrouter/x": SimpleNamespace(provider="openrouter")}
    monkeypatch.setattr(providers, "get_provider_registry", lambda: SimpleNamespace(resolve=entries.get))
    assert api._stream_idle_timeout("ollama/gemma4:12b") >= 600
    assert api._stream_idle_timeout("openrouter/x") == api.get_settings().llm_stream_timeout_seconds


def test_asking_permission_for_a_step_the_agent_can_take_is_nudged():
    from langchain_core.messages import AIMessage, HumanMessage
    from agent.graph import agent as graph_agent

    human = HumanMessage(content="Which artists are in my local music library?", id="h2")
    ask = AIMessage(content="I can see you listen to Drake. To list three artists from your library, "
                            "I'll need to use the MusicAgent to check your local data. Would you like me to do that?")
    assert graph_agent._announced_without_acting({"messages": [human, ask]})
    clarify = AIMessage(content="Which library do you mean: your local files or Spotify?")
    assert not graph_agent._announced_without_acting({"messages": [human, clarify]})
    offer = AIMessage(content="Here are three artists: A, B and C. Would you like me to play one?")
    assert not graph_agent._announced_without_acting({"messages": [human, offer]})
