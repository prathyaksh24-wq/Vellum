from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


@dataclass(frozen=True)
class PortablePluginManifest:
    id: str
    name: str
    type: str
    category: str
    version: str = "0.1.0"
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    path: Path = Path()


@dataclass
class PortablePlugin:
    manifest: PortablePluginManifest
    module: ModuleType

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def type(self) -> str:
        return self.manifest.type

    @property
    def category(self) -> str:
        return self.manifest.category

    @property
    def capabilities(self) -> list[str]:
        return self.manifest.capabilities

    def register(self, ctx: Any) -> None:
        register = getattr(self.module, "register", None)
        if not callable(register):
            raise ValueError(f"Portable plugin {self.id} does not expose register(ctx).")
        register(ctx)


class PortablePluginContext:
    """Minimal Hermes-compatible registration context for Vellum wrappers."""

    def __init__(self) -> None:
        self.connectors: dict[str, dict[str, Any]] = {}
        self.system_plugins: dict[str, dict[str, Any]] = {}
        self.memory_providers: dict[str, dict[str, Any]] = {}

    def register_connector(self, **kwargs: Any) -> None:
        self.connectors[str(kwargs["id"])] = dict(kwargs)

    def register_system_plugin(self, **kwargs: Any) -> None:
        self.system_plugins[str(kwargs["id"])] = dict(kwargs)

    def register_memory_provider(self, **kwargs: Any) -> None:
        self.memory_providers[str(kwargs["id"])] = dict(kwargs)


def discover_portable_plugins(root: str | Path) -> list[PortablePluginManifest]:
    root = Path(root)
    if not root.exists():
        return []
    manifests = []
    for manifest_path in sorted(root.rglob("plugin.yaml")):
        manifests.append(_read_manifest(manifest_path))
    return manifests


def load_portable_plugin(plugin_dir: str | Path) -> PortablePlugin:
    plugin_dir = Path(plugin_dir)
    manifest = _read_manifest(plugin_dir / "plugin.yaml")
    init_path = plugin_dir / "__init__.py"
    if not init_path.exists():
        raise FileNotFoundError(f"Portable plugin missing __init__.py: {init_path}")
    module_name = "vellum_portable_plugin_" + manifest.id.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, init_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load portable plugin: {plugin_dir}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return PortablePlugin(manifest=manifest, module=module)


def register_portable_plugins(root: str | Path, ctx: PortablePluginContext | None = None) -> PortablePluginContext:
    context = ctx or PortablePluginContext()
    for manifest in discover_portable_plugins(root):
        load_portable_plugin(manifest.path).register(context)
    return context


def _read_manifest(path: Path) -> PortablePluginManifest:
    data = _parse_simple_yaml(path)
    return PortablePluginManifest(
        id=str(data["id"]),
        name=str(data.get("name") or data["id"]),
        type=str(data["type"]),
        category=str(data["category"]),
        version=str(data.get("version") or "0.1.0"),
        description=str(data.get("description") or ""),
        capabilities=[str(item) for item in data.get("capabilities", [])],
        path=path.parent,
    )


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass

    data: dict[str, Any] = {}
    current_list: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list:
            data.setdefault(current_list, []).append(stripped[2:].strip().strip("'\""))
            continue
        current_list = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list = key
        else:
            data[key] = value.strip("'\"")
    return data
