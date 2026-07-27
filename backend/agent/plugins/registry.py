from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from agent.plugins.portable import PortablePluginManifest, discover_portable_plugins
from agent.plugins.sources import CodexPluginSource, LooseSkillBundleSource, PluginSourceRecord


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGINS_ROOT = REPO_ROOT / "plugins"
PLUGIN_STATE_PATH = REPO_ROOT / "data" / "plugins" / "state.json"
MATT_SKILL_NAMES = (
    "ask-matt",
    "code-review",
    "codebase-design",
    "diagnosing-bugs",
    "domain-modeling",
    "grill-with-docs",
    "implement",
    "improve-codebase-architecture",
    "prototype",
    "research",
    "resolving-merge-conflicts",
    "tdd",
    "to-spec",
    "to-tickets",
    "triage",
    "wayfinder",
)


class PluginRegistryError(ValueError):
    pass


class PluginRegistry:
    """Canonical catalog and enablement owner for every plugin source."""

    def __init__(
        self,
        root: str | Path,
        *,
        state_path: str | Path,
        sources: Iterable[Any] = (),
    ):
        self.root = Path(root)
        self.state_path = Path(state_path)
        self.sources = tuple(sources)
        self._source_records_cache: tuple[PluginSourceRecord, ...] | None = None
        self._lock = RLock()

    def manifests(self) -> list[PortablePluginManifest]:
        return discover_portable_plugins(self.root)

    def source_records(self) -> list[PluginSourceRecord]:
        if self._source_records_cache is not None:
            return list(self._source_records_cache)
        records: dict[str, PluginSourceRecord] = {}
        for source in self.sources:
            for record in source.discover():
                records.setdefault(record.id, record)
        self._source_records_cache = tuple(sorted(records.values(), key=lambda item: item.id))
        return list(self._source_records_cache)

    def is_enabled(self, plugin_id: str) -> bool:
        required = self._required(plugin_id)
        if required:
            return True
        return bool(self._read_state().get(plugin_id, True))

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        if not self._exists(plugin_id):
            raise KeyError(plugin_id)
        if self._required(plugin_id) and not enabled:
            raise PluginRegistryError(f"{plugin_id} is required and cannot be disabled")
        with self._lock:
            state = self._read_state()
            state[plugin_id] = bool(enabled)
            self._write_state(state)
        return self.describe(plugin_id)

    def skill_roots(self) -> dict[Path, str]:
        roots: dict[Path, str] = {}
        for manifest in self.manifests():
            skill_root = manifest.path / "skills"
            if self.is_enabled(manifest.id) and skill_root.exists():
                roots[skill_root] = manifest.id
        for record in self.source_records():
            if self.is_enabled(record.id) and record.skills_root is not None:
                roots[record.skills_root] = record.id
        for source in self.sources:
            owned = getattr(source, "skill_roots", None)
            if not callable(owned):
                continue
            for skill_root, plugin_id in owned().items():
                if self.is_enabled(plugin_id):
                    roots[Path(skill_root)] = plugin_id
        return roots

    def describe(
        self,
        plugin_id: str,
        *,
        runtime_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            manifest = self._manifest(plugin_id)
        except KeyError:
            return self._describe_source(self._source_record(plugin_id), runtime_status=runtime_status)
        status = dict(runtime_status or {})
        enabled = self.is_enabled(manifest.id)
        configured = bool(status.get("configured", True))
        runtime_state = str(status.get("status") or ("available" if configured else "not_configured"))
        return {
            "id": manifest.id,
            "name": manifest.name,
            "type": manifest.type,
            "category": manifest.category,
            "version": manifest.version,
            "description": manifest.description,
            "developer": "Vellum",
            "source": "portable",
            "configured": configured,
            "enabled": enabled,
            "required": manifest.required,
            "manageable": True,
            "status": runtime_state if enabled else "disabled",
            "notes": str(status.get("notes") or manifest.description),
            "capabilities": list(manifest.capabilities),
            "tools": list(manifest.provides_tools),
            "apps": list(manifest.apps),
            "mcp_connectors": list(manifest.mcp_connectors),
            "skills": self._skills(manifest.path / "skills", manifest.id),
            "metadata": {
                **dict(status.get("metadata") or {}),
                "portable_plugin": {
                    "id": manifest.id,
                    "name": manifest.name,
                    "type": manifest.type,
                    "category": manifest.category,
                    "version": manifest.version,
                    "path": manifest.path.as_posix(),
                    "capabilities": list(manifest.capabilities),
                },
            },
        }

    def catalog(
        self,
        *,
        runtime_statuses: Iterable[dict[str, Any]] = (),
        mcp_servers: Iterable[dict[str, Any]] = (),
    ) -> list[dict[str, Any]]:
        status_by_id = {
            str(item.get("id") or ""): dict(item)
            for item in runtime_statuses
            if item.get("id")
        }
        plugin_ids = [manifest.id for manifest in self.manifests()]
        plugin_ids.extend(record.id for record in self.source_records())
        records = [
            self.describe(plugin_id, runtime_status=status_by_id.get(plugin_id))
            for plugin_id in dict.fromkeys(plugin_ids)
        ]
        known_ids = {record["id"] for record in records}
        for server in mcp_servers:
            plugin_id = str(server.get("name") or "")
            if not plugin_id or plugin_id in known_ids:
                continue
            configured = bool(server.get("configured"))
            records.append(
                {
                    "id": plugin_id,
                    "name": plugin_id.replace("_", " ").title(),
                    "type": "mcp",
                    "category": "MCP",
                    "version": None,
                    "description": str(server.get("notes") or ""),
                    "developer": "",
                    "source": "mcp_configuration",
                    "configured": configured,
                    "enabled": configured,
                    "required": False,
                    "manageable": False,
                    "status": str(server.get("status") or "unknown"),
                    "notes": str(server.get("notes") or ""),
                    "capabilities": [],
                    "tools": [],
                    "apps": [],
                    "mcp_connectors": [
                        {
                            "id": plugin_id,
                            "name": plugin_id,
                            "configured": configured,
                            "status": str(server.get("status") or "unknown"),
                        }
                    ],
                    "skills": [],
                    "metadata": {"managed_by": "mcp_configuration"},
                }
            )
        return sorted(
            records,
            key=lambda item: (str(item["category"]).casefold(), str(item["name"]).casefold()),
        )

    def _describe_source(
        self,
        record: PluginSourceRecord,
        *,
        runtime_status: dict[str, Any] | None,
    ) -> dict[str, Any]:
        status = dict(runtime_status or {})
        enabled = self.is_enabled(record.id)
        configured = bool(status.get("configured", True))
        runtime_state = str(status.get("status") or ("available" if configured else "not_configured"))
        skill_roots = [
            root
            for root, owner in self.skill_roots().items()
            if owner == record.id
        ]
        skills: list[dict[str, Any]] = []
        for root in skill_roots:
            skills.extend(self._skills(root, record.id))
        return {
            "id": record.id,
            "name": record.name,
            "type": "bundle",
            "category": record.category,
            "version": record.version,
            "description": record.description,
            "developer": record.developer,
            "source": record.source,
            "configured": configured,
            "enabled": enabled,
            "required": record.required,
            "manageable": True,
            "status": runtime_state if enabled else "disabled",
            "notes": str(status.get("notes") or record.description),
            "capabilities": list(record.capabilities),
            "tools": [],
            "apps": list(record.apps),
            "mcp_connectors": list(record.mcp_connectors),
            "skills": sorted(skills, key=lambda item: item["id"]),
            "metadata": {
                **dict(status.get("metadata") or {}),
                "source": record.source,
                "read_only_source": True,
            },
        }

    def _skills(self, skill_root: Path, owner_plugin: str) -> list[dict[str, Any]]:
        if not skill_root.exists():
            return []
        skills = []
        for skill_file in sorted(skill_root.rglob("SKILL.md")):
            metadata = _skill_frontmatter(skill_file)
            name = str(metadata.get("name") or skill_file.parent.name)
            skills.append(
                {
                    "id": name,
                    "name": name,
                    "description": str(metadata.get("description") or ""),
                    "owner_plugin": owner_plugin,
                    "enabled": self.is_enabled(owner_plugin),
                }
            )
        return skills

    def _exists(self, plugin_id: str) -> bool:
        return any(manifest.id == plugin_id for manifest in self.manifests()) or any(
            record.id == plugin_id for record in self.source_records()
        )

    def _required(self, plugin_id: str) -> bool:
        try:
            return self._manifest(plugin_id).required
        except KeyError:
            return self._source_record(plugin_id).required

    def _manifest(self, plugin_id: str) -> PortablePluginManifest:
        normalized = plugin_id.strip()
        for manifest in self.manifests():
            if manifest.id == normalized:
                return manifest
        raise KeyError(normalized)

    def _source_record(self, plugin_id: str) -> PluginSourceRecord:
        normalized = plugin_id.strip()
        for record in self.source_records():
            if record.id == normalized:
                return record
        raise KeyError(normalized)

    def _read_state(self) -> dict[str, bool]:
        if not self.state_path.exists():
            return {}
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginRegistryError(f"plugin state is unreadable: {exc}") from exc
        values = loaded.get("enabled", loaded) if isinstance(loaded, dict) else {}
        if not isinstance(values, dict):
            raise PluginRegistryError("plugin state must be a JSON object")
        return {str(key): bool(value) for key, value in values.items()}

    def _write_state(self, state: dict[str, bool]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.tmp")
        payload = json.dumps(
            {"version": 1, "enabled": dict(sorted(state.items()))},
            indent=2,
        ) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, self.state_path)


def _skill_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml

        loaded = yaml.safe_load(parts[1]) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        result: dict[str, Any] = {}
        for line in parts[1].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("'\"")
        return result


def _default_sources() -> list[Any]:
    codex_home = Path(os.getenv("CODEX_HOME") or Path.home() / ".codex")
    cache = codex_home / "plugins" / "cache"
    codex_source = CodexPluginSource(
        [
            cache / "openai-curated-remote",
            cache / "openai-curated",
            cache / "openai-bundled",
        ]
    )
    matt_source = LooseSkillBundleSource(
        plugin_id="matt-pocock-engineering",
        name="Matt Pocock Engineering Skills",
        root=codex_home / "skills",
        skill_names=MATT_SKILL_NAMES,
        description="Planning, architecture, diagnosis, testing, and delivery workflows.",
        developer="Matt Pocock",
    )
    return [codex_source, matt_source]


@lru_cache(maxsize=1)
def get_plugin_registry() -> PluginRegistry:
    return PluginRegistry(
        PLUGINS_ROOT,
        state_path=PLUGIN_STATE_PATH,
        sources=_default_sources(),
    )


def reset_plugin_registry() -> None:
    get_plugin_registry.cache_clear()
