"""Model access to Vellum's harness: inspection, plugin management and the bundle workspace.

These mirror DeepSeek Harness' ``cordis_inspect`` and ``plugin_manager`` tools. The agent
authors bundles as workspace files, installs them with ``plugin_manager``, and finds facts
about the running harness with ``harness_inspect``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from agent.harness import HarnessError, get_harness, get_plugin_manager


CLIENT_MANIFEST_MAX_AGE_SECONDS = 120
_MAX_FILE_BYTES = 256 * 1024
_MUTATING = {"set_plugin", "set_bundle", "install_bundle", "remove_bundle"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _error(exc: Exception) -> str:
    code = getattr(exc, "code", "ERROR")
    return _json({"error": {"code": code, "message": str(exc)}})


# --------------------------------------------------------------------------- harness_inspect

_CLIENT_PROVIDERS = {
    "Slots": {
        "description": "Live UI slots in the connected page: each slot's cardinality and registrations (id, order, priority, owner).",
        "methods": {
            "listSubTree": {
                "description": "The slot tree, or one slot and its registrations when name is given.",
                "input": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        },
    },
    "Theme": {
        "description": "Theme tokens (CSS custom properties) and the active light/dark mode of the connected page.",
        "methods": {"listTokens": {"description": "Token names and current values.", "input": {"type": "object", "properties": {}}}},
    },
}


class InspectQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["host", "client"] = Field(description="Provider platform.")
    provider: str = Field(description="Provider ID from the directory.")
    method: str = Field(description="Method name from the directory.")
    input: Any = Field(default=None, description="Arguments matching the method's input schema.")


class InspectArgs(BaseModel):
    query: InspectQuery | None = None


def _directory() -> dict[str, Any]:
    harness = get_harness()
    host = [{
        "platform": "host",
        "provider": provider.id,
        "description": provider.description,
        "methods": [{"method": name, "description": m.description, "input": m.input_schema}
                    for name, m in provider.methods.items()],
    } for (platform, _), provider in sorted(harness.providers.items()) if platform == "host"]
    connected = time.time() - harness.client_manifest_at < CLIENT_MANIFEST_MAX_AGE_SECONDS
    client = [{
        "platform": "client",
        "provider": name,
        "description": spec["description"],
        "methods": [{"method": method, "description": m["description"], "input": m["input"]}
                    for method, m in spec["methods"].items()],
    } for name, spec in _CLIENT_PROVIDERS.items()]
    return {"providers": host + client, "clientConnected": connected}


def _client_query(provider: str, method: str, arguments: Any) -> Any:
    harness = get_harness()
    if time.time() - harness.client_manifest_at > CLIENT_MANIFEST_MAX_AGE_SECONDS:
        raise HarnessError("CLIENT_UNAVAILABLE", "No connected Vellum page has reported its UI. Client queries require an open page.")
    manifest = harness.client_manifest
    if provider == "Slots" and method == "listSubTree":
        slots = manifest.get("slots") or []
        name = (arguments or {}).get("name") if isinstance(arguments, dict) else None
        if name:
            match = next((slot for slot in slots if slot.get("name") == name), None)
            if match is None:
                raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No slot {name}. Omit name to list slots.")
            return match
        return {"slots": slots}
    if provider == "Theme" and method == "listTokens":
        return manifest.get("theme") or {}
    raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No client method {provider}.{method}. Omit query for the directory.")


def harness_inspect(query: InspectQuery | dict | None = None) -> str:
    if not get_harness().is_active("tool-harness-inspect"):
        return _json({"error": {"code": "TOOL_DISABLED", "message": "Runtime inspection is disabled in this profile."}})
    try:
        if query is None:
            return _json(_directory())
        if isinstance(query, dict):
            query = InspectQuery.model_validate(query)
        if query.platform == "client":
            return _json(_client_query(query.provider, query.method, query.input))
        provider = get_harness().providers.get(("host", query.provider))
        if provider is None:
            raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No host provider {query.provider}. Omit query for the directory.")
        method = provider.methods.get(query.method)
        if method is None:
            raise HarnessError("INSPECT_TARGET_NOT_FOUND",
                               f"{query.provider} has no method {query.method}; it has {sorted(provider.methods)}.")
        return _json(method.handler(query.input))
    except Exception as exc:
        return _error(exc)


# --------------------------------------------------------------------------- plugin_manager


class PluginManagerArgs(BaseModel):
    action: Literal["list_plugins", "list_bundles", "set_plugin", "set_bundle", "install_bundle", "remove_bundle"] = Field(
        description="Management operation.")
    target: str = Field(default="", description=(
        "Plugin entry id (set_plugin), bundle package name (set_bundle, remove_bundle), or the absolute "
        "path of the bundle's package directory (install_bundle)."))
    enabled: bool | None = Field(default=None, description="Required for set operations; defaults to true for installation.")
    offset: int = Field(default=0, description="Zero-based list offset; defaults to 0.")
    limit: int = Field(default=25, description="List page size, from 1 to 100; defaults to 25.")


def _approval_details(action: str, target: str, enabled: bool | None) -> tuple[str, dict[str, Any]]:
    manager = get_plugin_manager()
    if action == "install_bundle":
        bundle = manager.inspect_target(target)
        files = sorted(p.relative_to(bundle.directory).as_posix() for p in bundle.directory.rglob("*") if p.is_file())
        patch = bundle.patch.read_text(encoding="utf-8") if bundle.patch else ""
        return (f"Install plugin {bundle.name}", {
            "action": action, "bundle": bundle.name, "version": bundle.version,
            "description": bundle.description, "files": files[:40], "patch": patch[:4000],
            "runsHostCode": bundle.host is not None,
        })
    verb = {"set_plugin": "Turn {state} plugin {target}", "set_bundle": "Turn {state} bundle {target}",
            "remove_bundle": "Remove bundle {target}"}[action]
    return (verb.format(state="on" if enabled else "off", target=target),
            {"action": action, "target": target, "enabled": enabled})


def _record_receipt(action: str, target: str, result: dict[str, Any]) -> None:
    """Make plugin changes visible to the turn's result guard, like App Action receipts."""
    from agent.tools.app_actions import _SESSION

    session = _SESSION.get()
    if session is None:
        return
    applied = result.get("application") == "applied"
    # These messages replace the model's answer when it claims an unapplied change,
    # so they are written for the user, never as instructions to the model.
    name = result.get("bundle") or (Path(target).name if action == "install_bundle" else target)
    done = {"install_bundle": f"Installed the plugin {name}.", "remove_bundle": f"Removed the plugin {name}.",
            "set_bundle": f"Turned {'on' if result.get('enabled', True) else 'off'} the plugin {name}.",
            "set_plugin": f"Updated {name}."}[action]
    what = {"install_bundle": f"install the plugin {name}", "remove_bundle": f"remove the plugin {name}",
            "set_bundle": f"change the plugin {name}", "set_plugin": f"change {name}"}[action]
    if applied:
        message = done
    elif result.get("approval") == "denied":
        message = f"You declined, so I didn't {what}. Nothing changed."
    elif result.get("approval") == "expired":
        message = f"The approval to {what} timed out, so nothing changed."
    else:
        reason = str(result.get("error") or result.get("application") or "it failed").rstrip(".")
        message = f"I couldn't {what}: {reason}. Nothing was changed."
    session.write_results[f"plugin_manager:{action}:{target}"] = {
        "status": "applied" if applied else "failed", "message": message}


def plugin_manager(action: str, target: str = "", enabled: bool | None = None, offset: int = 0, limit: int = 25) -> str:
    harness = get_harness()
    if not harness.is_active("tool-plugin-manager"):
        return _json({"error": {"code": "TOOL_DISABLED", "message": "Plugin management is disabled in this profile."}})
    manager = get_plugin_manager()
    try:
        if action == "list_plugins":
            return _json(manager.list_plugins(offset=offset, limit=limit))
        if action == "list_bundles":
            return _json(manager.list_bundles(offset=offset, limit=limit))
        if action not in _MUTATING:
            raise HarnessError("INVALID_ARGS", f"Unknown action {action}.")
        if not target:
            raise HarnessError("INVALID_ARGS", f"{action} needs target.")
        if action in {"set_plugin", "set_bundle"} and enabled is None:
            raise HarnessError("INVALID_ARGS", f"{action} needs enabled.")
        title, details = _approval_details(action, target, enabled)
        # With full access (granted only by the user in the app), changes apply
        # without asking, like a DeepSeek Harness danger-full-access session.
        decision = "approved" if harness.full_access else harness.request_approval(title, details)
        if decision != "approved":
            result = {"application": "not-applied", "approval": decision,
                      "nextStep": "The user did not approve this change. Nothing changed; tell the user and do not retry unless they ask."}
            _record_receipt(action, target, result)
            return _json(result)
        if action == "set_plugin":
            result = manager.set_plugin(target, bool(enabled))
        elif action == "set_bundle":
            result = manager.set_bundle(target, bool(enabled))
        elif action == "install_bundle":
            result = manager.install_bundle(target, enabled=True if enabled is None else bool(enabled))
        else:
            result = manager.remove_bundle(target)
        _record_receipt(action, target, result)
        return _json(result)
    except HarnessError as exc:
        if action in _MUTATING:
            _record_receipt(action, target, {"application": "failed", "error": str(exc)})
        return _error(exc)


# --------------------------------------------------------------------------- workspace


class WorkspaceArgs(BaseModel):
    action: Literal["list", "read", "write", "delete"] = Field(description="File operation.")
    path: str = Field(default="", description="Path relative to the workspace, e.g. animated-bg/client.js.")
    content: str = Field(default="", description="Full file text for write.")


def _workspace_path(path: str) -> Path:
    root = get_harness().workspace_dir.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise HarnessError("OUTSIDE_WORKSPACE", "Paths stay inside the bundle workspace.")
    return candidate


def workspace_files(action: str, path: str = "", content: str = "") -> str:
    try:
        root = get_harness().workspace_dir.resolve()
        target = _workspace_path(path)
        if action == "list":
            if not target.exists():
                return _json({"workspace": str(root), "files": []})
            files = sorted(p.relative_to(root).as_posix() for p in target.rglob("*") if p.is_file())
            return _json({"workspace": str(root), "files": files[:200]})
        if not path:
            raise HarnessError("INVALID_ARGS", f"{action} needs path.")
        if action == "read":
            if not target.is_file():
                raise HarnessError("NOT_FOUND", f"{path} does not exist in the workspace.")
            return target.read_text(encoding="utf-8")
        if action == "write":
            if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
                raise HarnessError("TOO_LARGE", "Workspace files are limited to 256 KB.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return _json({"written": target.relative_to(root).as_posix(), "absolutePath": str(target),
                          "bytes": len(content.encode("utf-8"))})
        if action == "delete":
            if target.is_file():
                target.unlink()
                return _json({"deleted": path})
            raise HarnessError("NOT_FOUND", f"{path} is not a file.")
        raise HarnessError("INVALID_ARGS", f"Unknown action {action}.")
    except (HarnessError, OSError) as exc:
        return _error(exc)


HARNESS_INSPECT_DESCRIPTION = (
    "Inspect Vellum's running harness before writing or configuring plugins. Omit query to discover "
    "providers, methods, and input schemas; then query an exact entry from that directory. Read-only: "
    "cannot invoke application operations or modify the runtime. Client queries require a connected page. "
    "Author persistent changes as bundles and install them with plugin_manager."
)

PLUGIN_MANAGER_DESCRIPTION = (
    "List plugins or bundles in the current profile, enable or disable them, install a bundle, or remove an "
    "installed bundle. Every change requires the user's approval for that call, and the call waits for it, unless "
    "the user turned on full access, in which case it applies at once. Changes "
    "affect every conversation and survive restart. List first to obtain exact identifiers. The application "
    "field of a change result is authoritative: applied means the change is in effect and needs no restart; any "
    "other value carries nextStep, which says what to do or tell the user."
)

WORKSPACE_DESCRIPTION = (
    "Read and write files in the bundle workspace where you author Vellum plugin bundles before installing "
    "them with plugin_manager install_bundle. write returns the file's absolutePath; install_bundle takes the "
    "absolute path of the bundle's package directory."
)


def harness_tools() -> list[StructuredTool]:
    return [
        StructuredTool.from_function(harness_inspect, name="harness_inspect",
                                     description=HARNESS_INSPECT_DESCRIPTION, args_schema=InspectArgs),
        StructuredTool.from_function(plugin_manager, name="plugin_manager",
                                     description=PLUGIN_MANAGER_DESCRIPTION, args_schema=PluginManagerArgs),
        StructuredTool.from_function(workspace_files, name="workspace_files",
                                     description=WORKSPACE_DESCRIPTION, args_schema=WorkspaceArgs),
    ]
