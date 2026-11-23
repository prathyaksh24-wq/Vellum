"""Plugin Manager: the one implementation behind the Plugins UI and the plugin_manager tool.

Operations mirror DeepSeek Harness' plugin manager: list plugins and bundles, enable or
disable an entry or a bundle, install a bundle from a package directory, and remove an
installed bundle. Every change result carries ``application``; anything other than
``applied`` also carries ``nextStep``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from agent.harness.patch import PatchError, compose, read_layer
from agent.harness.runtime import Bundle, Harness, HarnessError


BUILTIN_BUNDLE = "@vellum/app"
DEFAULT_LIMIT = 25
MAX_LIMIT = 100


class PluginManager:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness

    # ------------------------------------------------------------------ reads
    def list_plugins(self, *, offset: int = 0, limit: int = DEFAULT_LIMIT, name: str = "") -> dict[str, Any]:
        offset, limit = _page(offset, limit)
        rows = []
        for entry_id in self.harness.order:
            fiber = self.harness.fibers[entry_id]
            if name and fiber.row.name != name:
                continue
            rows.append({
                "id": entry_id,
                "name": fiber.row.name,
                "enabled": not fiber.row.disabled,
                "fiberPhase": fiber.phase,
                "bundle": _owner_bundle(fiber.row.origin),
                "description": fiber.plugin.description if fiber.plugin else "",
                **({"error": fiber.error} if fiber.error else {}),
            })
        page = rows[offset:offset + limit]
        return {"plugins": page, "total": len(rows),
                **({"nextOffset": offset + limit} if offset + limit < len(rows) else {})}

    def list_bundles(self, *, offset: int = 0, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        offset, limit = _page(offset, limit)
        selection = {item["name"]: item.get("enabled", True) for item in self.harness.read_selection()}
        bundles: list[dict[str, Any]] = [{
            "name": BUILTIN_BUNDLE,
            "description": "Vellum's shipped plugins. Always enabled; its rows can be overridden.",
            "enabled": True,
            "builtin": True,
            "rows": self._rows_from(lambda origin: origin == "base"),
        }]
        for bundle in self.harness.installed_bundles():
            bundles.append({
                "name": bundle.name,
                "version": bundle.version,
                "description": bundle.description,
                "enabled": bool(selection.get(bundle.name, False)),
                "builtin": False,
                "rows": self._rows_from(lambda origin, n=bundle.name: origin == f"bundle:{n}"),
                "overrides": self._overrides_by(bundle.name),
                **({"error": bundle.error} if bundle.error else {}),
            })
        page = bundles[offset:offset + limit]
        return {"bundles": page, "total": len(bundles),
                **({"nextOffset": offset + limit} if offset + limit < len(bundles) else {})}

    def _rows_from(self, predicate) -> list[dict[str, Any]]:
        return [
            {"id": fid, "name": f.row.name, "fiberPhase": f.phase}
            for fid, f in ((i, self.harness.fibers[i]) for i in self.harness.order)
            if predicate(f.row.origin)
        ]

    def _overrides_by(self, bundle_name: str) -> list[str]:
        label = f"bundle:{bundle_name}"
        return [fid for fid in self.harness.order if label in self.harness.fibers[fid].row.overridden_by]

    # ------------------------------------------------------------------ set_plugin
    def set_plugin(self, entry_id: str, enabled: bool) -> dict[str, Any]:
        fiber = self.harness.entry(entry_id)
        if fiber is None:
            raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No plugin entry '{entry_id}'. List plugins for exact ids.")
        patches = self.harness.read_profile_patches()
        override = next((p for p in reversed(patches) if "insert" not in p and p.get("id") == entry_id), None)
        if override is None:
            override = {"id": entry_id}
            patches.append(override)
        override["disabled"] = not enabled
        # Record only departures: drop an id+disabled override the lower layers already satisfy.
        if set(override) == {"id", "disabled"}:
            without = [p for p in patches if p is not override]
            if self._state_without_profile(entry_id, without) == (not enabled):
                patches = without
        self.harness.write_profile_patches(patches)
        self.harness.recompose(f"set_plugin:{entry_id}")
        return self._change_result(entry_id=entry_id, expected_enabled=enabled)

    def _state_without_profile(self, entry_id: str, profile_patches: list[dict[str, Any]]) -> bool | None:
        from agent.harness.patch import parse_layer

        layers = self.harness.layers()[:-1] + [parse_layer(profile_patches, "profile")]
        rows, _ = compose(layers)
        row = next((r for r in rows if r.id == entry_id), None)
        return None if row is None else row.disabled

    # ------------------------------------------------------------------ set_bundle
    def set_bundle(self, name: str, enabled: bool) -> dict[str, Any]:
        if name == BUILTIN_BUNDLE:
            raise HarnessError("PROTECTED_BUNDLE", "Vellum's shipped bundle cannot be turned off. Disable individual rows instead.")
        selection = self.harness.read_selection()
        item = next((i for i in selection if i["name"] == name), None)
        if item is None:
            raise HarnessError("NOT_INSTALLED", f"{name} is not installed. List bundles for exact names.")
        if not enabled:
            item["enabled"] = False
        else:
            # Enabling appends the bundle at the end, like DSH: it can change precedence.
            selection = [i for i in selection if i["name"] != name] + [{"name": name, "enabled": True}]
        self.harness.write_selection(selection)
        self.harness.recompose(f"set_bundle:{name}")
        return self._bundle_result(name, expect_enabled=enabled)

    # ------------------------------------------------------------------ install
    def inspect_target(self, target: str) -> Bundle:
        source = Path(target).expanduser()
        if not source.is_absolute():
            raise HarnessError("INVALID_SPEC", "install_bundle needs the absolute path of the bundle's package directory.")
        if not source.is_dir():
            raise HarnessError("NOT_A_PACKAGE", f"{target} is not a directory.")
        bundle = self.harness.read_bundle(source)
        if bundle.name == BUILTIN_BUNDLE or bundle.name in self.harness.builtin_plugins:
            raise HarnessError("PROTECTED_BUNDLE", f"{bundle.name} is a shipped name; choose another package name.")
        return bundle

    def install_bundle(self, target: str, *, enabled: bool = True) -> dict[str, Any]:
        bundle = self.inspect_target(target)
        warnings = self._validate_sources(bundle)
        replaced = self.harness.bundle_dir(bundle.name).exists()
        self.harness.copy_bundle(bundle.directory, bundle)
        selection = [i for i in self.harness.read_selection() if i["name"] != bundle.name]
        previous = next((i for i in self.harness.read_selection() if i["name"] == bundle.name), None)
        keep_enabled = previous.get("enabled", True) if previous else enabled
        selection.append({"name": bundle.name, "enabled": keep_enabled})
        self.harness.write_selection(selection)
        try:
            self.harness.recompose(f"install:{bundle.name}")
        except HarnessError as exc:
            return {
                "application": "failed",
                "bundle": bundle.name,
                "error": str(exc),
                "nextStep": "Fix the bundle patch in your workspace and install it again, or remove_bundle to restore the previous composition.",
            }
        result = self._bundle_result(bundle.name, expect_enabled=keep_enabled)
        result.update({"version": bundle.version, "replaced": replaced})
        if warnings:
            result["warnings"] = warnings + result.get("warnings", [])
        return result

    def _validate_sources(self, bundle: Bundle) -> list[str]:
        warnings = []
        if bundle.patch is not None:
            try:
                layer = read_layer(bundle.patch, f"bundle:{bundle.name}")
            except PatchError as exc:
                raise HarnessError("INVALID_PATCH", str(exc)) from exc
            if not layer.patches:
                warnings.append("The bundle patch is empty, so it changes nothing.")
        if bundle.host is not None:
            try:
                compile(bundle.host.read_text(encoding="utf-8"), str(bundle.host), "exec")
            except SyntaxError as exc:
                raise HarnessError("SYNTAX_ERROR", f"{bundle.host.name}:{exc.lineno}: {exc.msg}") from exc
        if bundle.client is not None:
            node = shutil.which("node")
            if node is None:
                warnings.append("node is not on PATH, so the client module's syntax was not checked.")
            else:
                checked = subprocess.run([node, "--check", str(bundle.client)], capture_output=True, text=True, timeout=30)
                if checked.returncode != 0:
                    detail = (checked.stderr or checked.stdout).strip().splitlines()
                    raise HarnessError("SYNTAX_ERROR", "client module: " + " ".join(detail[:4]))
        return warnings

    # ------------------------------------------------------------------ remove
    def remove_bundle(self, name: str) -> dict[str, Any]:
        if name == BUILTIN_BUNDLE:
            raise HarnessError("PROTECTED_BUNDLE", "Vellum's shipped bundle cannot be removed.")
        selection = self.harness.read_selection()
        if not any(i["name"] == name for i in selection):
            raise HarnessError("NOT_INSTALLED", f"{name} is not installed. List bundles for exact names.")
        self.harness.write_selection([i for i in selection if i["name"] != name])
        self.harness.recompose(f"remove:{name}")
        directory = self.harness.bundle_dir(name)
        if directory.exists():
            shutil.rmtree(directory)
        return {"application": "applied", "bundle": name, "removed": True}

    # ------------------------------------------------------------------ results
    def _change_result(self, *, entry_id: str, expected_enabled: bool) -> dict[str, Any]:
        fiber = self.harness.entry(entry_id)
        if fiber is None:
            return {"application": "applied", "entry": entry_id}
        actual_enabled = not fiber.row.disabled
        if actual_enabled != expected_enabled:
            layer = fiber.row.overridden_by[-1] if fiber.row.overridden_by else fiber.row.origin
            return {"application": "overridden", "entry": entry_id, "fiberPhase": fiber.phase,
                    "nextStep": f"A higher-priority layer ({layer}) decides this row. Tell the user; change that layer instead."}
        if fiber.phase == "error":
            return {"application": "failed-to-start", "entry": entry_id, "error": fiber.error,
                    "nextStep": "The row is saved but its plugin did not start. Report the error to the user."}
        return {"application": "applied", "entry": entry_id, "fiberPhase": fiber.phase}

    def _bundle_result(self, name: str, *, expect_enabled: bool) -> dict[str, Any]:
        label = f"bundle:{name}"
        rows = []
        for fid in self.harness.order:
            fiber = self.harness.fibers[fid]
            if fiber.row.origin == label or label in fiber.row.overridden_by:
                rows.append({"id": fid, "name": fiber.row.name, "fiberPhase": fiber.phase,
                             **({"error": fiber.error} if fiber.error else {})})
        result: dict[str, Any] = {"application": "applied", "bundle": name, "enabled": expect_enabled, "rows": rows}
        if self.harness.warnings:
            result["warnings"] = [w for w in self.harness.warnings if label in w]
        failed = [row for row in rows if row["fiberPhase"] == "error"]
        if expect_enabled and not rows:
            result["application"] = "no-effect"
            result["nextStep"] = ("The bundle is installed but its patch inserted or changed no row. "
                                  "Check that patch ids match list_plugins ids, fix it in the workspace and install again.")
        elif failed:
            result["application"] = "failed-to-start"
            result["nextStep"] = ("The bundle is saved but these rows did not start: "
                                  + "; ".join(f"{r['id']}: {r['error']}" for r in failed)
                                  + ". Fix the bundle in the workspace and install it again.")
        return result


def _owner_bundle(origin: str) -> str:
    if origin == "base":
        return BUILTIN_BUNDLE
    if origin.startswith("bundle:"):
        return origin.removeprefix("bundle:")
    return origin


def _page(offset: int, limit: int) -> tuple[int, int]:
    try:
        offset = max(0, int(offset or 0))
        limit = int(limit or DEFAULT_LIMIT)
    except (TypeError, ValueError) as exc:
        raise HarnessError("INVALID_ARGS", "offset and limit are numbers.") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise HarnessError("INVALID_ARGS", f"limit is from 1 to {MAX_LIMIT}.")
    return offset, limit
