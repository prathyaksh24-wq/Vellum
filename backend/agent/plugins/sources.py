from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PluginSourceRecord:
    id: str
    name: str
    version: str
    description: str
    category: str
    developer: str
    source: str
    root: Path
    skills_root: Path | None = None
    apps: list[dict[str, Any]] = field(default_factory=list)
    mcp_connectors: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    required: bool = False


class CodexPluginSource:
    """Read-only adapter for installed OpenAI/Codex plugin bundles."""

    def __init__(self, cache_roots: Iterable[str | Path]):
        self.cache_roots = [Path(root) for root in cache_roots]

    def discover(self) -> list[PluginSourceRecord]:
        records: dict[str, PluginSourceRecord] = {}
        for cache_root in self.cache_roots:
            if not cache_root.exists():
                continue
            for manifest_path in sorted(cache_root.rglob(".codex-plugin/plugin.json")):
                record = self._read(manifest_path)
                records.setdefault(record.id, record)
        return sorted(records.values(), key=lambda item: item.id)

    def _read(self, manifest_path: Path) -> PluginSourceRecord:
        root = manifest_path.parent.parent.resolve()
        data = _read_json(manifest_path)
        plugin_id = str(data.get("name") or root.name).strip()
        interface = data.get("interface") if isinstance(data.get("interface"), dict) else {}
        skills_root = _declared_path(root, data.get("skills"))
        apps = _named_records(_declared_json(root, data.get("apps")), "apps")
        connectors = _named_records(_declared_json(root, data.get("mcpServers")), "mcpServers")
        return PluginSourceRecord(
            id=plugin_id,
            name=str(interface.get("displayName") or plugin_id),
            version=str(data.get("version") or "0.0.0"),
            description=str(interface.get("shortDescription") or data.get("description") or ""),
            category=str(interface.get("category") or "OpenAI"),
            developer=str(
                interface.get("developerName")
                or (data.get("author") or {}).get("name")
                or "OpenAI"
            ),
            source="openai_plugin",
            root=root,
            skills_root=skills_root if skills_root and skills_root.is_dir() else None,
            apps=apps,
            mcp_connectors=connectors,
            capabilities=[str(item) for item in interface.get("capabilities", [])],
        )


class LooseSkillBundleSource:
    """Adapter that presents a curated set of standalone skills as one plugin."""

    def __init__(
        self,
        *,
        plugin_id: str,
        name: str,
        root: str | Path,
        skill_names: Iterable[str],
        description: str,
        developer: str,
        category: str = "Engineering",
    ):
        self.plugin_id = plugin_id
        self.name = name
        self.root = Path(root)
        self.skill_names = tuple(dict.fromkeys(str(name) for name in skill_names))
        self.description = description
        self.developer = developer
        self.category = category

    def discover(self) -> list[PluginSourceRecord]:
        if not self.root.exists():
            return []
        available = [
            self.root / name
            for name in self.skill_names
            if (self.root / name / "SKILL.md").is_file()
        ]
        if not available:
            return []
        return [
            PluginSourceRecord(
                id=self.plugin_id,
                name=self.name,
                version="local",
                description=self.description,
                category=self.category,
                developer=self.developer,
                source="local_skill_bundle",
                root=self.root,
                capabilities=["Skills"],
            )
        ]

    def skill_roots(self) -> dict[Path, str]:
        return {
            self.root / name: self.plugin_id
            for name in self.skill_names
            if (self.root / name / "SKILL.md").is_file()
        }


def _declared_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _declared_json(root: Path, value: Any) -> dict[str, Any]:
    path = _declared_path(root, value)
    if path is None or not path.is_file():
        return {}
    return _read_json(path)


def _named_records(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key, {})
    if not isinstance(values, dict):
        return []
    return [
        {"name": str(name), **(dict(value) if isinstance(value, dict) else {})}
        for name, value in sorted(values.items())
    ]


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return loaded
