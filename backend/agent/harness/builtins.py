"""Vellum's shipped plugins. Each one is an ordinary entry in the composed tree."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.harness.runtime import RUNTIME_VERSION, Context, HarnessError, InspectMethod, InspectProvider, Plugin


log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- UI plugins
# These have their client half in design/Velllum/uploads/components/harness-builtins.js.


class AnalyticsConfig(BaseModel):
    """Where Analytics is reachable."""

    model_config = ConfigDict(extra="forbid")
    placement: Literal["settings", "sidebar", "both"] = Field(
        default="settings",
        description="settings: a Settings section. sidebar: a main sidebar entry that opens Analytics as a full page. both: both.",
    )


class BackgroundConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def ui_background() -> Plugin:
    return Plugin(
        name="@vellum/ui-background",
        description="Renders the selected background into the shell.background slot. A plugin registered into that slot with a lower priority replaces it.",
        config=BackgroundConfig,
        client="builtin",
    )


def ui_analytics() -> Plugin:
    return Plugin(
        name="@vellum/ui-analytics",
        description="Analytics (runs, traces, context, usage). Registers into settings.sections, sidebar.panellist and shell.view according to placement.",
        config=AnalyticsConfig,
        client="builtin",
    )


# --------------------------------------------------------------------------- model provider


class ModelProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["ollama", "openrouter", "openai"] | None = Field(
        default=None,
        description="Model source for chat. ollama is the local model; null leaves the user's current choice unchanged.",
    )
    model: str | None = Field(
        default=None,
        description="Exact model id from the Models provider (listModels). null keeps the source's default model.",
    )


def llm_provider(state_dir: Path) -> Plugin:
    state_file = state_dir / "llm-provider.json"

    def apply(ctx: Context, config: ModelProviderConfig) -> None:
        wanted = config.model_dump(mode="json")
        if wanted == {"provider": None, "model": None}:
            return
        # Apply a configuration once. Later picker changes by the user stay theirs
        # across restarts until this config changes again.
        try:
            applied = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            applied = None
        if applied == wanted:
            return
        from agent.app_actions.models import AppActionContext, AppActionRequest
        from agent.app_actions.runtime import get_app_action_runtime

        arguments = {key: value for key, value in wanted.items() if value}
        receipt = get_app_action_runtime().dispatch(
            AppActionRequest(action_id="settings.default_model.set", arguments=arguments),
            AppActionContext(source="ui"),
        )
        if receipt.status != "applied":
            raise HarnessError("MODEL_UNAVAILABLE", receipt.message or f"Model change was {receipt.status}.")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(wanted), encoding="utf-8")

    return Plugin(
        name="@vellum/llm-provider",
        description="The chat model source and model. Applies through the same settings operation as the model picker.",
        config=ModelProviderConfig,
        apply=apply,
    )


# --------------------------------------------------------------------------- App Actions


def app_actions() -> Plugin:
    def apply(ctx: Context, _config: Any) -> None:
        from agent.app_actions.runtime import get_app_action_runtime

        def catalog():
            return get_app_action_runtime().catalog()

        def list_actions(arguments: Any) -> dict[str, Any]:
            query = str((arguments or {}).get("query") or "").casefold()
            actions = [a for a in catalog().actions
                       if not query or query in f"{a.id} {a.title} {a.description}".casefold()]
            return {"actions": [{"id": a.id, "title": a.title, "access": a.access_class,
                                 "confirmation": a.confirmation_rule} for a in actions[:50]],
                    "total": len(actions)}

        def describe(arguments: Any) -> dict[str, Any]:
            action_id = str((arguments or {}).get("id") or "")
            action = next((a for a in catalog().actions if a.id == action_id), None)
            if action is None:
                raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No App Action {action_id}.")
            return action.model_dump(mode="json")

        ctx.inspect(InspectProvider(
            id="Actions",
            description="Vellum application operations the app_action tool executes (settings, conversations, connectors).",
            methods={
                "listActions": InspectMethod("List App Actions, optionally filtered by a query.",
                                             {"type": "object", "properties": {"query": {"type": "string"}}}, list_actions),
                "describeAction": InspectMethod("One App Action's argument schema and confirmation rule.",
                                                {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}}, describe),
            },
        ))

    return Plugin(name="@vellum/app-actions",
                  description="Exposes the App Action catalog through runtime inspection.", apply=apply)


# --------------------------------------------------------------------------- inspection


def tool_harness_inspect() -> Plugin:
    """Owns the Host inspect providers and the harness_inspect tool."""

    def apply(ctx: Context, _config: Any) -> None:
        harness = ctx.harness

        def list_configs(arguments: Any) -> dict[str, Any]:
            arguments = arguments or {}
            offset = int(arguments.get("offset") or 0)
            limit = int(arguments.get("limit") or 50)
            if not 1 <= limit <= 100:
                raise HarnessError("INVALID_ARGS", "limit is from 1 to 100.")
            name = arguments.get("name")
            rows = []
            for entry_id in harness.order:
                fiber = harness.fibers[entry_id]
                if name and fiber.row.name != name:
                    continue
                plugin = fiber.plugin or harness.resolve_plugin(fiber.row.name)
                if fiber.phase == "disabled" or plugin is None:
                    status = "inactive"
                elif plugin.config is None:
                    status = "absent"
                else:
                    status = "schema"
                rows.append({"id": entry_id, "name": fiber.row.name, "status": status, "fiberPhase": fiber.phase})
            page = rows[offset:offset + limit]
            return {"entries": page, "total": len(rows),
                    **({"nextOffset": offset + limit} if offset + limit < len(rows) else {})}

        def get_config(arguments: Any) -> dict[str, Any]:
            entry_id = str((arguments or {}).get("id") or "")
            fiber = harness.entry(entry_id)
            if fiber is None:
                raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No entry {entry_id}. Call listConfigs for ids.")
            plugin = fiber.plugin or harness.resolve_plugin(fiber.row.name)
            if fiber.phase == "disabled" or plugin is None:
                return {"id": entry_id, "name": fiber.row.name, "status": "inactive"}
            schema = plugin.config.model_json_schema() if plugin.config is not None else None
            return {
                "id": entry_id,
                "name": fiber.row.name,
                "description": plugin.description,
                "status": "schema" if schema else "absent",
                "schema": schema,
                "value": harness.config_of(entry_id) if fiber.phase == "active" else fiber.row.config,
                "fiberPhase": fiber.phase,
                **({"error": fiber.error} if fiber.error else {}),
                "bundle": plugin.bundle or "@vellum/app",
                **({"packageDir": str(harness.bundle_dir(plugin.bundle))} if plugin.bundle else {}),
            }

        def list_tools(_arguments: Any) -> dict[str, Any]:
            from agent.graph.agent import core_tools

            return {"tools": [{"name": t.name, "description": (t.description or "").split("\n")[0][:200]}
                              for t in core_tools()]}

        def list_models(arguments: Any) -> dict[str, Any]:
            from agent.llm.providers import get_provider_registry

            registry = get_provider_registry()
            provider = (arguments or {}).get("provider")
            current = registry.current_model()
            sources = [provider] if provider else ["ollama", "openrouter", "openai"]
            result = {}
            for source in sources:
                try:
                    result[source] = [m.id for m in registry.list_picker_models(source)][:40]
                except Exception as exc:  # an unconnected provider lists nothing
                    result[source] = {"unavailable": str(exc)}
            return {"current": {"provider": registry.picker_provider(), "model": current.id}, "providers": result}

        ctx.inspect(InspectProvider(
            id="Config",
            description="The live entry tree: each entry's id (what patches address), plugin name and Config, projected as JSON Schema.",
            methods={
                "listConfigs": InspectMethod(
                    "Page the live entries with their Config status (schema, absent, inactive).",
                    {"type": "object", "properties": {"offset": {"type": "number"}, "limit": {"type": "number"},
                                                      "name": {"type": "string", "description": "Exact plugin name."}}},
                    list_configs),
                "getConfig": InspectMethod(
                    "One entry's Config JSON Schema, current value, phase and owning bundle.",
                    {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
                    get_config),
            },
        ))
        ctx.inspect(InspectProvider(
            id="Runtime",
            description="The running Vellum harness.",
            methods={"getVersion": InspectMethod("The harness runtime version that bundles declare compatibility with.",
                                                 {"type": "object", "properties": {}}, lambda _a: {"version": RUNTIME_VERSION})},
        ))
        ctx.inspect(InspectProvider(
            id="Tools",
            description="The tools this agent can call.",
            methods={"listTools": InspectMethod("Names and one-line descriptions of the agent's tools.",
                                                {"type": "object", "properties": {}}, list_tools)},
        ))
        ctx.inspect(InspectProvider(
            id="Models",
            description="Model sources and models the llm-provider entry can select.",
            methods={"listModels": InspectMethod(
                "Current model and the models each source offers.",
                {"type": "object", "properties": {"provider": {"enum": ["ollama", "openrouter", "openai"]}}},
                list_models)},
        ))

    return Plugin(name="@vellum/tool-harness-inspect",
                  description="Read-only runtime inspection for the harness_inspect tool.", apply=apply)


def tool_plugin_manager() -> Plugin:
    return Plugin(name="@vellum/tool-plugin-manager",
                  description="The plugin_manager tool: list, enable, disable, install and remove bundles.")


def ui_self_changes() -> Plugin:
    return Plugin(
        name="@vellum/ui-self-changes",
        description="Settings section with the user-only switch that lets plugin changes apply without an approval each time.",
        client="builtin",
    )


def builtin_plugins(state_dir: Path) -> list[Plugin]:
    return [
        ui_background(),
        ui_analytics(),
        ui_self_changes(),
        llm_provider(state_dir),
        app_actions(),
        tool_harness_inspect(),
        tool_plugin_manager(),
    ]
