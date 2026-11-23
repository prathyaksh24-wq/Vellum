"""Vellum's harness runtime: everything is a plugin.

This is the Vellum port of the DeepSeek Harness / Cordis model:

- Every feature is a plugin entry (a row) in one composed tree.
- The tree is composed from ordered patch layers: the shipped base patch, then each
  selected bundle's patch in selection order, then the profile's own patch.
- A plugin's ``apply(ctx, config)`` registers effects on its context; disposing the
  entry removes every effect it registered.
- Changing the profile recomposes the live tree: only entries whose name, config or
  enabled state changed are disposed and applied again (hot reload).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from agent.harness.patch import Layer, PatchError, Row, compose, dump_layer, parse_layer, read_layer


log = logging.getLogger(__name__)

RUNTIME_VERSION = "1.0.0"
BUNDLE_MANIFEST = "package.json"
PROFILE_MANIFEST = "profile.json"
PROFILE_PATCH = "harness.patch.yml"
APPROVAL_TIMEOUT_SECONDS = 600


class HarnessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- plugins


@dataclass
class Plugin:
    """A plugin a row can name. Built-ins are Python objects; bundles add their own."""

    name: str
    description: str = ""
    config: type[BaseModel] | None = None
    apply: Callable[["Context", Any], None] | None = None
    # "builtin" for a client module shipped with the page, a URL for a bundle module,
    # or "" for a Host-only plugin.
    client: str = ""
    bundle: str = ""


@dataclass
class InspectMethod:
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Any], Any]


@dataclass
class InspectProvider:
    id: str
    description: str
    methods: dict[str, InspectMethod]
    platform: str = "host"


class Context:
    """The context a plugin applies on. Registrations are effects it owns."""

    def __init__(self, harness: "Harness", row: Row) -> None:
        self.harness = harness
        self.entry = row
        self._effects: list[Callable[[], None]] = []

    def effect(self, dispose: Callable[[], None]) -> Callable[[], None]:
        self._effects.append(dispose)
        return dispose

    def provide(self, name: str, value: Any) -> None:
        self.harness._provide(name, value)
        self.effect(lambda: self.harness._unprovide(name, value))

    def get(self, name: str) -> Any:
        return self.harness.services.get(name)

    def inspect(self, provider: InspectProvider) -> None:
        self.harness._add_provider(provider)
        self.effect(lambda: self.harness._remove_provider(provider))

    def on(self, event: str, listener: Callable[[dict[str, Any]], None]) -> None:
        self.harness._listeners.setdefault(event, []).append(listener)
        self.effect(lambda: self.harness._listeners.get(event, []).remove(listener))

    def dispose(self) -> None:
        while self._effects:
            dispose = self._effects.pop()
            try:
                dispose()
            except Exception:  # an effect failing must not keep others alive
                log.exception("harness effect disposal failed for %s", self.entry.id)


@dataclass
class Fiber:
    row: Row
    key: str
    phase: str  # active | disabled | error | inactive
    plugin: Plugin | None = None
    context: Context | None = None
    error: str = ""
    config: Any = None


@dataclass
class Bundle:
    name: str
    version: str
    description: str
    directory: Path
    patch: Path | None
    client: Path | None
    host: Path | None
    digest: str
    meta: dict[str, Any] = field(default_factory=dict)
    error: str = ""


# --------------------------------------------------------------------------- harness


class Harness:
    def __init__(self, root: Path, base_patch: Path, plugins: Iterable[Plugin]) -> None:
        self.root = Path(root)
        self.base_patch = Path(base_patch)
        self.builtin_plugins: dict[str, Plugin] = {plugin.name: plugin for plugin in plugins}
        self.services: dict[str, Any] = {}
        self.providers: dict[tuple[str, str], InspectProvider] = {}
        self.fibers: dict[str, Fiber] = {}
        self.order: list[str] = []
        self.warnings: list[str] = []
        self.revision = 0
        self.client_manifest: dict[str, Any] = {}
        self.client_manifest_at = 0.0
        self._listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._approvals: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._bundle_modules: dict[str, ModuleType] = {}
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    @property
    def profile_dir(self) -> Path:
        return self.root / "profile"

    @property
    def bundles_dir(self) -> Path:
        return self.profile_dir / "bundles"

    @property
    def workspace_dir(self) -> Path:
        return self.root / "workspace"

    @property
    def permissions_file(self) -> Path:
        return self.root / "permissions.json"

    @property
    def full_access(self) -> bool:
        """DSH's danger-full-access: plugin changes apply without asking each time."""
        try:
            return json.loads(self.permissions_file.read_text(encoding="utf-8")).get("full_access") is True
        except (OSError, json.JSONDecodeError):
            return False

    def set_full_access(self, enabled: bool) -> None:
        _atomic_write(self.permissions_file, json.dumps({"full_access": bool(enabled)}) + "\n")
        self.publish("harness/permissions", {"full_access": bool(enabled)})

    @property
    def profile_patch(self) -> Path:
        return self.profile_dir / PROFILE_PATCH

    @property
    def profile_manifest(self) -> Path:
        return self.profile_dir / PROFILE_MANIFEST

    # ------------------------------------------------------------------ services
    def _provide(self, name: str, value: Any) -> None:
        self.services[name] = value

    def _unprovide(self, name: str, value: Any) -> None:
        if self.services.get(name) is value:
            del self.services[name]

    def _add_provider(self, provider: InspectProvider) -> None:
        key = (provider.platform, provider.id)
        if key in self.providers:
            raise HarnessError("INSPECT_PROVIDER_DUPLICATE", f"Inspect provider {provider.id} is already registered.")
        self.providers[key] = provider

    def _remove_provider(self, provider: InspectProvider) -> None:
        if self.providers.get((provider.platform, provider.id)) is provider:
            del self.providers[(provider.platform, provider.id)]

    # ------------------------------------------------------------------ profile
    def read_selection(self) -> list[dict[str, Any]]:
        if not self.profile_manifest.is_file():
            return []
        try:
            data = json.loads(self.profile_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HarnessError("PROFILE_READ_FAILED", f"{PROFILE_MANIFEST} is not valid JSON: {exc}") from exc
        selection = data.get("bundles", [])
        return [item for item in selection if isinstance(item, dict) and isinstance(item.get("name"), str)]

    def write_selection(self, selection: list[dict[str, Any]]) -> None:
        payload = {"bundles": [{"name": item["name"], "enabled": bool(item.get("enabled", True))} for item in selection]}
        _atomic_write(self.profile_manifest, json.dumps(payload, indent=2) + "\n")

    def read_profile_patches(self) -> list[dict[str, Any]]:
        layer = read_layer(self.profile_patch, "profile")
        return [dict(patch) for patch in layer.patches]

    def write_profile_patches(self, patches: list[dict[str, Any]]) -> None:
        parse_layer(patches, "profile")  # never write something composition would reject
        _atomic_write(self.profile_patch, dump_layer(patches))

    def bundle_dir(self, name: str) -> Path:
        return self.bundles_dir / _safe_dir(name)

    def read_bundle(self, directory: Path) -> Bundle:
        manifest_path = directory / BUNDLE_MANIFEST
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HarnessError("NOT_A_PACKAGE", f"{directory} has no {BUNDLE_MANIFEST}.") from exc
        except json.JSONDecodeError as exc:
            raise HarnessError("NOT_A_PACKAGE", f"{BUNDLE_MANIFEST} is not valid JSON: {exc}") from exc
        name = manifest.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HarnessError("NOT_A_PACKAGE", f"{BUNDLE_MANIFEST} needs a name.")
        vellum = manifest.get("vellum") or {}
        bundle_meta = vellum.get("bundle") if isinstance(vellum, dict) else None
        if not isinstance(bundle_meta, dict) or not isinstance(bundle_meta.get("patch"), str):
            raise HarnessError("NOT_A_BUNDLE", f"{name} declares no vellum.bundle.patch, so it is not a bundle.")

        def member(relative: Any, label: str) -> Path | None:
            if not relative:
                return None
            if not isinstance(relative, str):
                raise HarnessError("NOT_A_BUNDLE", f"{label} must be a relative path.")
            path = (directory / relative).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise HarnessError("NOT_A_BUNDLE", f"{label} must stay inside the bundle directory.")
            if not path.is_file():
                raise HarnessError("NOT_A_BUNDLE", f"{label} {relative} does not exist.")
            return path

        patch = member(bundle_meta["patch"], "vellum.bundle.patch")
        client_meta = vellum.get("client") or {}
        host_meta = vellum.get("host") or {}
        client = member(client_meta.get("entry") if isinstance(client_meta, dict) else None, "vellum.client.entry")
        host = member(host_meta.get("entry") if isinstance(host_meta, dict) else None, "vellum.host.entry")
        return Bundle(
            name=name,
            version=str(manifest.get("version") or "0.0.0"),
            description=str(manifest.get("description") or ""),
            directory=directory,
            patch=patch,
            client=client,
            host=host,
            digest=_digest_dir(directory),
            meta=vellum.get("meta") if isinstance(vellum.get("meta"), dict) else {},
        )

    def installed_bundles(self) -> list[Bundle]:
        bundles = []
        for item in self.read_selection():
            directory = self.bundle_dir(item["name"])
            try:
                bundles.append(self.read_bundle(directory))
            except HarnessError as exc:
                bundles.append(Bundle(item["name"], "", "", directory, None, None, None, "", error=str(exc)))
        return bundles

    # ------------------------------------------------------------------ composition
    def layers(self) -> list[Layer]:
        layers = [read_layer(self.base_patch, "base")]
        enabled = {item["name"] for item in self.read_selection() if item.get("enabled", True)}
        for bundle in self.installed_bundles():
            if bundle.name not in enabled or bundle.error or bundle.patch is None:
                continue
            layers.append(read_layer(bundle.patch, f"bundle:{bundle.name}"))
        layers.append(read_layer(self.profile_patch, "profile"))
        return layers

    def resolve_plugin(self, name: str) -> Plugin | None:
        if name in self.builtin_plugins:
            return self.builtin_plugins[name]
        for bundle in self.installed_bundles():
            if bundle.name != name or bundle.error:
                continue
            apply = None
            config = None
            if bundle.host is not None:
                module = self._load_host_module(bundle)
                apply = getattr(module, "apply", None)
                config = getattr(module, "Config", None)
            return Plugin(
                name=bundle.name,
                description=bundle.description,
                config=config if isinstance(config, type) and issubclass(config, BaseModel) else None,
                apply=apply,
                client=f"/api/harness/bundles/{bundle.name}/client?v={bundle.digest[:12]}" if bundle.client else "",
                bundle=bundle.name,
            )
        return None

    def _load_host_module(self, bundle: Bundle) -> ModuleType:
        key = f"{bundle.name}@{bundle.digest}"
        module = self._bundle_modules.get(key)
        if module is None:
            module_name = "vellum_bundle_" + hashlib.sha1(key.encode()).hexdigest()[:16]
            spec = importlib.util.spec_from_file_location(module_name, bundle.host)
            if spec is None or spec.loader is None:
                raise HarnessError("BUNDLE_LOAD_FAILED", f"{bundle.name} host entry cannot be imported.")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            self._bundle_modules[key] = module
        return module

    def recompose(self, reason: str = "") -> dict[str, Any]:
        """Compose the tree and hot-reload entries whose identity changed."""

        with self._lock:
            try:
                rows, warnings = compose(self.layers())
            except (PatchError, HarnessError) as exc:
                self.warnings = [str(exc)]
                raise HarnessError("COMPOSITION_FAILED", str(exc)) from exc
            digests = {bundle.name: bundle.digest for bundle in self.installed_bundles()}
            wanted = {row.id: row for row in rows}
            keys = {
                row.id: json.dumps(
                    [row.name, row.config, row.disabled, digests.get(row.name, "")],
                    sort_keys=True, default=str,
                )
                for row in rows
            }
            started: list[str] = []
            stopped: list[str] = []
            # Dispose in reverse order so dependants stop before what they used.
            for entry_id in reversed(self.order):
                fiber = self.fibers.get(entry_id)
                if fiber is None:
                    continue
                if entry_id not in wanted or keys[entry_id] != fiber.key:
                    self._stop(fiber)
                    del self.fibers[entry_id]
                    stopped.append(entry_id)
            for row in rows:
                if row.id in self.fibers:
                    self.fibers[row.id].row = row
                    continue
                self.fibers[row.id] = self._start(row, keys[row.id])
                started.append(row.id)
            self.order = [row.id for row in rows]
            self.warnings = warnings
            changed = bool(started or stopped)
            if changed:
                self.revision += 1
            result = {
                "revision": self.revision,
                "started": started,
                "stopped": stopped,
                "errors": {fid: f.error for fid, f in self.fibers.items() if f.phase == "error"},
                "warnings": warnings,
            }
        if changed:
            self.publish("harness/changed", {"revision": self.revision, "reason": reason, "started": started, "stopped": stopped})
        return result

    def _start(self, row: Row, key: str) -> Fiber:
        if row.disabled:
            return Fiber(row=row, key=key, phase="disabled")
        plugin = self.resolve_plugin(row.name)
        if plugin is None:
            return Fiber(row=row, key=key, phase="error", error=f"No plugin named {row.name} is installed.")
        config: Any = row.config
        if plugin.config is not None:
            try:
                config = plugin.config.model_validate(row.config or {})
            except ValidationError as exc:
                return Fiber(row=row, key=key, phase="error", plugin=plugin,
                             error=f"Invalid config: {_validation_summary(exc)}")
        context = Context(self, row)
        try:
            if plugin.apply is not None:
                plugin.apply(context, config)
        except Exception as exc:  # a broken plugin must not take the harness down
            log.exception("harness plugin %s failed to apply", row.name)
            context.dispose()
            return Fiber(row=row, key=key, phase="error", plugin=plugin, error=f"apply failed: {exc}")
        return Fiber(row=row, key=key, phase="active", plugin=plugin, context=context, config=config)

    @staticmethod
    def _stop(fiber: Fiber) -> None:
        if fiber.context is not None:
            fiber.context.dispose()

    # ------------------------------------------------------------------ reads
    def entry(self, entry_id: str) -> Fiber | None:
        return self.fibers.get(entry_id)

    def config_of(self, entry_id: str) -> Any:
        fiber = self.fibers.get(entry_id)
        if fiber is None or fiber.phase != "active":
            return None
        config = fiber.config
        return config.model_dump(mode="json") if isinstance(config, BaseModel) else config

    def is_active(self, entry_id: str) -> bool:
        fiber = self.fibers.get(entry_id)
        return fiber is not None and fiber.phase == "active"

    def client_payload(self) -> dict[str, Any]:
        """What the page needs to mount client plugins for the current tree."""

        entries = []
        for entry_id in self.order:
            fiber = self.fibers[entry_id]
            if fiber.phase != "active" or fiber.plugin is None or not fiber.plugin.client:
                continue
            entries.append({
                "id": entry_id,
                "name": fiber.row.name,
                "config": self.config_of(entry_id),
                "module": fiber.plugin.client,
            })
        return {"revision": self.revision, "runtimeVersion": RUNTIME_VERSION, "entries": entries}

    # ------------------------------------------------------------------ config editor
    def edit_config(self, entry_id: str, change: Callable[[Any], Any]) -> dict[str, Any]:
        """The DSH config editor: rewrite one row's config in the profile patch."""

        with self._lock:
            fiber = self.fibers.get(entry_id)
            if fiber is None:
                raise HarnessError("INSPECT_TARGET_NOT_FOUND", f"No entry {entry_id}.")
            current = self.config_of(entry_id) if fiber.phase == "active" else fiber.row.config
            candidate = change(json.loads(json.dumps(current)) if current is not None else {})
            plugin = fiber.plugin or self.resolve_plugin(fiber.row.name)
            if plugin is not None and plugin.config is not None:
                try:
                    candidate = plugin.config.model_validate(candidate).model_dump(mode="json")
                except ValidationError as exc:
                    raise HarnessError("INVALID_CONFIG", _validation_summary(exc)) from exc
            patches = self.read_profile_patches()
            override = next((p for p in reversed(patches) if "insert" not in p and p.get("id") == entry_id), None)
            if override is None:
                override = {"id": entry_id}
                patches.append(override)
            override["config"] = candidate
            self.write_profile_patches(patches)
        return self.recompose(f"config:{entry_id}")

    # ------------------------------------------------------------------ events
    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append((loop, queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers = [(loop, q) for loop, q in self._subscribers if q is not queue]

    def publish(self, event: str, payload: dict[str, Any]) -> None:
        message = {"event": event, **payload}
        for listener in list(self._listeners.get(event, [])):
            try:
                listener(message)
            except Exception:
                log.exception("harness listener for %s failed", event)
        for loop, queue in list(self._subscribers):
            def put(queue=queue) -> None:
                if not queue.full():
                    queue.put_nowait(message)
            try:
                loop.call_soon_threadsafe(put)
            except RuntimeError:
                self.unsubscribe(queue)

    # ------------------------------------------------------------------ approvals
    def request_approval(self, title: str, details: dict[str, Any], *, timeout: float = APPROVAL_TIMEOUT_SECONDS) -> str:
        """Block the calling tool until the user approves or denies this one call."""

        approval_id = uuid4().hex
        record = {"id": approval_id, "title": title, "details": details, "status": "pending",
                  "created_at": time.time(), "event": threading.Event()}
        self._approvals[approval_id] = record
        self.publish("harness/approval", self.public_approval(record))
        try:
            if not record["event"].wait(timeout):
                record["status"] = "expired"
                self.publish("harness/approval", self.public_approval(record))
            return record["status"]
        finally:
            self._approvals.pop(approval_id, None)

    def resolve_approval(self, approval_id: str, approved: bool) -> dict[str, Any]:
        record = self._approvals.get(approval_id)
        if record is None or record["status"] != "pending":
            raise HarnessError("APPROVAL_NOT_PENDING", "That approval is no longer pending.")
        record["status"] = "approved" if approved else "denied"
        record["event"].set()
        public = self.public_approval(record)
        self.publish("harness/approval", public)
        return public

    def pending_approvals(self) -> list[dict[str, Any]]:
        return [self.public_approval(r) for r in self._approvals.values() if r["status"] == "pending"]

    @staticmethod
    def public_approval(record: dict[str, Any]) -> dict[str, Any]:
        return {key: record[key] for key in ("id", "title", "details", "status", "created_at")}

    # ------------------------------------------------------------------ client manifest
    def set_client_manifest(self, manifest: dict[str, Any]) -> None:
        self.client_manifest = manifest
        self.client_manifest_at = time.time()

    # ------------------------------------------------------------------ install helpers
    def copy_bundle(self, source: Path, bundle: Bundle) -> Path:
        target = self.bundle_dir(bundle.name)
        staging = target.with_name(target.name + ".staging")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns("node_modules", ".git", "__pycache__"))
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        return target


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _safe_dir(name: str) -> str:
    return name.replace("@", "").replace("/", "__")


def _digest_dir(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _validation_summary(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error.get("loc", ())) or "config"
        parts.append(f"{location}: {error.get('msg')}")
    return "; ".join(parts)
