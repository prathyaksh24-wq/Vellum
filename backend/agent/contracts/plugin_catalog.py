"""Public relationship metadata projected by the canonical PluginRegistry."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class PluginComponent(BaseModel):
    kind: Literal['app', 'mcp', 'skill']
    id: str = Field(max_length=512)
    name: str = Field(max_length=256)
    owner_plugin_id: str = Field(max_length=512)
    canonical_id: str = Field(default='', max_length=512)
    description: str = Field(default='', max_length=1000)
    enabled: bool
    configured: bool | None = None
    connected: bool | None = None


class PluginRelationships(BaseModel):
    schema_version: Literal[1] = 1
    package_id: str
    is_package: bool = True
    canonical_app_id: str = ''
    app_ids: list[str] = Field(default_factory=list)
    remote_plugin_id: str = ''
    components: list[PluginComponent] = Field(default_factory=list)


class PluginProvenance(BaseModel):
    source: str = ''
    marketplace_id: str = ''
    source_id: str = ''


def _text(value: Any, limit: int = 512) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int)) and not isinstance(value, bool) else ''


def _boolean(value: Any) -> bool | None:
    return value if type(value) is bool else None


def plugin_relationship_metadata(record: dict[str, Any], *, relationships: dict | None = None,
                                 provenance: dict | None = None) -> dict[str, Any]:
    """Normalize declared identities; never inspect credentials or start a server.

    A portable `connector` is a registered app integration itself. Bundles are
    packages whose apps/MCPs/skills are declared children. Configured MCP records
    represent servers rather than installable packages. Names never decide type.
    """
    declared = relationships if isinstance(relationships, dict) else {}
    origin = provenance if isinstance(provenance, dict) else {}
    package_id = _text(record.get('id'))
    is_package = record.get('source') != 'mcp_configuration'
    enabled = record.get('enabled') is not False and record.get('installed') is not False
    apps = [row for row in record.get('apps', []) if isinstance(row, dict)]
    implicit = record.get('source') == 'portable' and record.get('type') == 'connector' and not apps
    if implicit:
        apps = [{'id': package_id, 'name': record.get('name'), 'description': record.get('description'),
                 'configured': record.get('configured'),
                 'connected': (record.get('metadata', {}).get('connection') or {}).get('connected')}]
    canonical = _text(declared.get('canonical_app_id') or declared.get('canonicalAppId'))
    if implicit and not canonical:
        canonical = package_id
    components = []
    seen = set()
    for kind, rows in [('app', apps), ('mcp', record.get('mcp_connectors', [])), ('skill', record.get('skills', []))]:
        for row in rows:
            if not isinstance(row, dict):
                continue
            identity = _text(row.get('id') or row.get('name'))
            if not identity or (kind, identity) in seen:
                continue
            seen.add((kind, identity))
            components.append(PluginComponent(
                kind=kind, id=identity, name=_text(row.get('display_name') or row.get('name') or identity, 256),
                owner_plugin_id=package_id,
                canonical_id=_text(row.get('canonical_app_id') or row.get('canonicalAppId') or
                                   row.get('app_id') or ((canonical if len(apps)==1 and canonical else identity) if kind == 'app' else '')),
                description=_text(row.get('description'), 1000), enabled=enabled and row.get('enabled') is not False,
                configured=_boolean(row.get('configured')), connected=_boolean(row.get('connected')),
            ))
    declared_apps = declared.get('app_ids') or declared.get('appIds') or []
    declared_apps = [_text(value) for value in declared_apps[:500] if isinstance(value, str) and value.strip()] if isinstance(declared_apps, list) else []
    app_ids = list(dict.fromkeys([*(component.canonical_id for component in components if component.kind == 'app'), *declared_apps]))
    metadata = PluginRelationships(package_id=package_id, is_package=is_package,
        canonical_app_id=canonical, app_ids=app_ids,
        remote_plugin_id=_text(declared.get('remote_plugin_id') or declared.get('remotePluginId')),
        components=components)
    source = PluginProvenance(source=_text(record.get('source'), 128),
        marketplace_id=_text(origin.get('marketplace_id') or origin.get('marketplaceId')),
        source_id=_text(origin.get('source_id') or origin.get('sourceId')))
    return {'relationships': metadata.model_dump(mode='json'), 'provenance': source.model_dump(mode='json')}
