from __future__ import annotations

import json
import os
from pathlib import Path

from langchain_core.tools import tool

from agent.skills import FilesystemSkillBackend, SkillConfigStore, SkillHub, SkillHubError, SkillMutationCoordinator, SkillRegistry, TapsManager, bundle_content_hash, create_skill_source_router
from agent.skills.runtime import SKILLS_PATH


_HUB: SkillHub | None = None
_TAPS: TapsManager | None = None
_MUTATIONS: SkillMutationCoordinator | None = None


def _hub() -> SkillHub:
    global _HUB
    if _HUB is None:
        _HUB = SkillHub(SKILLS_PATH, sources=create_skill_source_router())
    return _HUB


def _taps() -> TapsManager:
    global _TAPS
    if _TAPS is None:
        _TAPS = TapsManager(SKILLS_PATH)
    return _TAPS


def _mutations() -> SkillMutationCoordinator:
    global _MUTATIONS
    hub = _hub()
    if _MUTATIONS is None or _MUTATIONS.root != hub.root:
        _MUTATIONS = SkillMutationCoordinator(hub.root, backend=FilesystemSkillBackend(hub.root, source_resolver=hub._source_for))
    return _MUTATIONS


def _stage_bundle(action: str, identifier: str, *, category: str, force: bool) -> dict:
    hub = _hub()
    inspected = hub.inspect(identifier)
    if inspected["scan_verdict"] == "dangerous":
        raise SkillHubError("dangerous verdict cannot be approved")
    if inspected["scan_verdict"] == "caution" and not force:
        raise SkillHubError("community caution requires force")
    bundle = hub._source_for(identifier).fetch(identifier)
    if bundle_content_hash(bundle) != inspected["content_hash"]:
        raise SkillHubError("upstream package changed during inspection")
    files = {}
    for path, content in bundle.files.items():
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillHubError("remote skill packages must contain text files") from exc
        files[path] = content
    return _mutations().submit(
        action,
        bundle_name=bundle.name,
        description=bundle.description,
        source=bundle.source,
        identifier=bundle.identifier,
        trust_level=bundle.trust_level,
        files=files,
        metadata=bundle.metadata,
        category=category,
        force=force,
        inspected_hash=inspected["content_hash"],
        verify_upstream=True,
        origin="hub",
        gist=f"{action.replace('_', ' ')} {bundle.name} from {bundle.source}",
    )


def _stage_local_import(name: str, *, category: str) -> dict:
    root = _hub().root
    config = SkillConfigStore(root / "config.yaml")
    external = [Path(os.path.expandvars(os.path.expanduser(str(path)))) for path in config.get_option("external_dirs", []) or []]
    package = SkillRegistry(local_root=root / "packages", external_dirs=external).view(name)
    if not package.is_external:
        raise SkillHubError("skill is already local")
    files = {}
    for path in package.root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files[path.relative_to(package.root).as_posix()] = path.read_text(encoding="utf-8")
    return _mutations().submit(
        "hub_install", bundle_name=name, description=package.metadata.description, source="local-import",
        identifier=f"external/{name}", trust_level="local", files=files, metadata={}, category=category,
        force=False, inspected_hash="local", verify_upstream=False, origin="foreground",
        gist=f"import external skill {name} locally",
    )


@tool
def skill_hub(
    action: str,
    query: str = "",
    identifier: str = "",
    name: str = "",
    source: str = "all",
    category: str = "uncategorized",
    repo: str = "",
    path: str = "skills/",
    limit: int = 10,
    force: bool = False,
    confirm: bool = False,
) -> str:
    """Search, inspect, install, update, audit, uninstall, and manage taps for skills."""
    normalized = action.strip().casefold().replace("-", "_")
    try:
        if normalized in {"search", "browse"}:
            result = {"ok": True, "results": _hub().search(query, source_filter=source, limit=limit)}
        elif normalized == "inspect":
            result = {"ok": True, "skill": _hub().inspect(identifier)}
        elif normalized == "install":
            result = _stage_bundle("hub_install", identifier, category=category, force=force)
        elif normalized == "list":
            result = {"ok": True, "skills": _hub().list_installed()}
        elif normalized == "check":
            result = {"ok": True, "update": _hub().check(name)}
        elif normalized == "update":
            entry = _hub().lock.get(name)
            if entry is None:
                raise SkillHubError(f"hub skill not found: {name}")
            install_path = str(entry["install_path"])
            result = _stage_bundle("hub_update", str(entry["identifier"]), category=install_path.split("/")[-2], force=force)
        elif normalized == "audit":
            result = {"ok": True, "audit": _hub().audit(name)}
        elif normalized == "uninstall":
            if not confirm:
                raise SkillHubError("Confirm uninstall before removing this skill")
            from agent.skills.catalog import SkillCatalog
            from agent.skills.curator import CuratorBackupStore

            snapshot = CuratorBackupStore(_hub().root).create(f"pre-uninstall {name}")
            result = _hub().uninstall(name, confirm=True)
            SkillCatalog(_hub().root).reconcile(embed_semantics=False)
            result["snapshot"] = snapshot
        elif normalized == "import_local":
            result = _stage_local_import(name, category=category)
        elif normalized == "pending":
            result = {"ok": True, "pending": _mutations().list_pending()}
        elif normalized == "approve":
            result = _mutations().approve(identifier or name)
        elif normalized == "reject":
            result = _mutations().reject(identifier or name)
        elif normalized == "tap_list":
            result = {"ok": True, "taps": _taps().list()}
        elif normalized == "tap_add":
            result = _taps().add(repo, path=path, confirm=confirm)
        elif normalized == "tap_remove":
            result = _taps().remove(repo, confirm=confirm)
        else:
            result = {"ok": False, "error": f"Unsupported hub action: {normalized}"}
    except (SkillHubError, OSError, ValueError, KeyError) as exc:
        result = {"ok": False, "error": str(exc)}
    return json.dumps(result, ensure_ascii=False, indent=2)
