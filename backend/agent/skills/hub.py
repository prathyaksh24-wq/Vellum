from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import tempfile
from typing import Any

from agent.skills.hub_models import HubSkillBundle
from agent.skills.parser import SkillPackageError, SkillPackageParser
from agent.skills.security import SkillSecurityScanner, allow_skill_install


class SkillHubError(ValueError):
    pass


def bundle_content_hash(bundle: HubSkillBundle) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(bundle.files.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content if isinstance(content, bytes) else content.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


class HubLockFile:
    def __init__(self, root: str | Path):
        self.path = Path(root) / ".hub" / "lock.json"

    def all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return {}
        skills = loaded.get("skills", {})
        return skills if isinstance(skills, dict) else {}

    def get(self, name: str) -> dict[str, Any] | None:
        entry = self.all().get(name)
        return dict(entry) if entry else None

    def set(self, name: str, entry: dict[str, Any]) -> None:
        skills = self.all()
        skills[name] = entry
        self._write(skills)

    def remove(self, name: str) -> None:
        skills = self.all()
        skills.pop(name, None)
        self._write(skills)

    def _write(self, skills: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"skills": skills}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


class TapsManager:
    def __init__(self, root: str | Path):
        self.path = Path(root) / ".hub" / "taps.json"

    def list(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        taps = loaded.get("taps", []) if isinstance(loaded, dict) else []
        return sorted(taps, key=lambda item: item["repo"])

    def add(self, repo: str, *, path: str = "skills/", confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise SkillHubError("tap mutation requires confirmation")
        if not self._valid_repo(repo):
            raise SkillHubError("tap repo must use owner/repo format")
        normalized_path = self._valid_path(path)
        taps = self.list()
        if any(item["repo"] == repo for item in taps):
            raise SkillHubError(f"tap already exists: {repo}")
        taps.append({"repo": repo, "path": normalized_path})
        self._write(taps)
        return {"ok": True, "repo": repo, "path": normalized_path}

    def remove(self, repo: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise SkillHubError("tap mutation requires confirmation")
        taps = self.list()
        filtered = [item for item in taps if item["repo"] != repo]
        if len(filtered) == len(taps):
            raise SkillHubError(f"tap not found: {repo}")
        self._write(filtered)
        return {"ok": True, "repo": repo}

    def _write(self, taps: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"taps": taps}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _valid_repo(repo: str) -> bool:
        parts = repo.split("/")
        return len(parts) == 2 and all(part and part not in {".", ".."} for part in parts)

    @staticmethod
    def _valid_path(path: str) -> str:
        posix = PurePosixPath(path.replace("\\", "/"))
        if posix.is_absolute() or ".." in posix.parts:
            raise SkillHubError("tap path must be relative")
        return posix.as_posix().rstrip("/") + "/"


class SkillHub:
    def __init__(
        self,
        root: str | Path,
        *,
        sources: list,
        scanner: SkillSecurityScanner | None = None,
    ):
        self.root = Path(root)
        self.sources = sources
        self.scanner = scanner or SkillSecurityScanner()
        self.parser = SkillPackageParser()
        self.lock = HubLockFile(self.root)
        self.last_search_health: dict[str, dict[str, Any]] = {}

    def search(self, query: str, *, source_filter: str = "all", limit: int = 10) -> list[dict[str, Any]]:
        results = []
        for source in self.sources:
            source_id = getattr(source, "source_id", "unknown")
            if source_filter != "all" and source_id != source_filter:
                continue
            search = getattr(source, "search", None)
            searchable = bool(getattr(source, "searchable", callable(search)))
            if not callable(search) or not searchable:
                self.last_search_health[source_id] = {"status": "install_by_identifier", "searchable": False}
                continue
            try:
                if source_id == "well-known":
                    if not query.startswith(("http://", "https://")):
                        continue
                    found = search(query, query="", limit=limit)
                else:
                    found = search(query, limit=limit)
                self.last_search_health[source_id] = {"status": "available", "searchable": True}
            except (OSError, ValueError, KeyError) as exc:
                self.last_search_health[source_id] = {
                    "status": "error", "searchable": True, "error": str(exc)[:160]
                }
                continue
            for item in found:
                extra = dict(item.extra or {})
                results.append(
                    {
                        "name": item.name,
                        "description": item.description,
                        "source": item.source,
                        "identifier": item.identifier,
                        "trust_level": item.trust_level,
                        "category": str(extra.get("category") or "other"),
                        "repository_url": extra.get("repository_url"),
                        "installs": extra.get("installs") or extra.get("downloads"),
                        "updated_at": extra.get("updated_at"),
                        "author": extra.get("author"),
                        "extra": extra,
                    }
                )
        trust_rank = {"official": 3, "builtin": 3, "trusted": 2, "community": 1}
        results.sort(key=lambda item: (-trust_rank.get(item["trust_level"], 0), item["name"]))
        unique: dict[str, dict[str, Any]] = {}
        for item in results:
            unique.setdefault(self._discovery_key(item), item)
        return list(unique.values())[:limit]

    @staticmethod
    def _discovery_key(item: dict[str, Any]) -> str:
        identifier = str(item.get("identifier") or "")
        parts = identifier.split("/")
        if identifier.startswith("skills-sh/") and len(parts) >= 4:
            return f"github:{parts[1].casefold()}/{parts[2].casefold()}:skills/{'/'.join(parts[3:]).casefold()}"
        if identifier.startswith("skillsmp/github/") and len(parts) >= 7:
            return f"github:{parts[2].casefold()}/{parts[3].casefold()}:{'/'.join(parts[5:]).casefold()}"
        if identifier.startswith("github/") and len(parts) >= 4:
            return f"github:{parts[1].casefold()}/{parts[2].casefold()}:{'/'.join(parts[3:]).casefold()}"
        return f"{item.get('source', 'unknown')}:{identifier.casefold()}"

    def inspect(self, identifier: str) -> dict[str, Any]:
        bundle = self._source_for(identifier).fetch(identifier)
        quarantine_root = self.root / ".hub" / "quarantine"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="inspect-", dir=quarantine_root))
        try:
            package = staging / "package"
            package.mkdir()
            for relative, content in bundle.files.items():
                target = self._bundle_target(package, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content) if isinstance(content, bytes) else target.write_text(content, encoding="utf-8")
            scan = self.scanner.scan(package, source=bundle.source, trust_level=bundle.trust_level)
            skill_md = bundle.files.get("SKILL.md", "") if scan.verdict != "dangerous" else ""
            if isinstance(skill_md, bytes):
                skill_md = skill_md.decode("utf-8", errors="replace")
            return {
                "name": bundle.name,
                "description": bundle.description,
                "source": bundle.source,
                "identifier": bundle.identifier,
                "trust_level": bundle.trust_level,
                "files": sorted(bundle.files),
                "content_hash": bundle_content_hash(bundle),
                "scan_verdict": scan.verdict,
                "findings": [finding.__dict__ for finding in scan.findings],
                "skill_md": skill_md,
                "repository_url": bundle.metadata.get("repository_url"),
                "source_ref": bundle.metadata.get("source_ref"),
                "source_path": bundle.metadata.get("source_path"),
            }
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def audit(self, name: str) -> dict[str, Any]:
        entry = self.lock.get(name)
        if entry is None:
            raise SkillHubError(f"hub skill not found: {name}")
        path = (self.root / entry["install_path"]).resolve()
        result = self.scanner.scan(path, source=entry["source"], trust_level=entry["trust_level"])
        return {
            "name": name,
            "verdict": result.verdict,
            "findings": [finding.__dict__ for finding in result.findings],
        }

    def install(
        self,
        identifier: str,
        *,
        category: str = "uncategorized",
        confirm: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise SkillHubError("skill installation requires confirmation")
        source = self._source_for(identifier)
        bundle = source.fetch(identifier)
        return self._install_bundle(bundle, category=category, force=force, replace=False)

    def list_installed(self) -> list[dict[str, Any]]:
        return [dict(value) for _name, value in sorted(self.lock.all().items())]

    def check(self, name: str) -> dict[str, Any]:
        entry = self.lock.get(name)
        if entry is None:
            raise SkillHubError(f"hub skill not found: {name}")
        bundle = self._source_for(entry["identifier"]).fetch(entry["identifier"])
        upstream_hash = bundle_content_hash(bundle)
        return {
            "name": name,
            "status": "current" if upstream_hash == entry["content_hash"] else "update_available",
            "installed_hash": entry["content_hash"],
            "upstream_hash": upstream_hash,
        }

    def update(self, name: str, *, confirm: bool = False, force: bool = False) -> dict[str, Any]:
        if not confirm:
            raise SkillHubError("skill update requires confirmation")
        entry = self.lock.get(name)
        if entry is None:
            raise SkillHubError(f"hub skill not found: {name}")
        bundle = self._source_for(entry["identifier"]).fetch(entry["identifier"])
        install_path = Path(entry["install_path"])
        category = install_path.parent.name
        return self._install_bundle(bundle, category=category, force=force, replace=True)

    def uninstall(self, name: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise SkillHubError("skill uninstall requires confirmation")
        entry = self.lock.get(name)
        if entry is None:
            raise SkillHubError(f"hub skill not found: {name}")
        target = (self.root / entry["install_path"]).resolve()
        packages_root = (self.root / "packages").resolve()
        if packages_root not in target.parents:
            raise SkillHubError("unsafe install path in hub lock")
        shutil.rmtree(target)
        self.lock.remove(name)
        self._audit("uninstall", name, entry["source"], "ok")
        return {"ok": True, "action": "uninstall", "name": name}

    def _install_bundle(
        self,
        bundle: HubSkillBundle,
        *,
        category: str,
        force: bool,
        replace: bool,
    ) -> dict[str, Any]:
        quarantine_root = self.root / ".hub" / "quarantine"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="install-", dir=quarantine_root))
        package_root = staging / "package"
        package_root.mkdir()
        try:
            for relative, content in bundle.files.items():
                target = self._bundle_target(package_root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    target.write_bytes(content)
                else:
                    target.write_text(content, encoding="utf-8")
            try:
                parsed = self.parser.parse(package_root)
            except SkillPackageError as exc:
                raise SkillHubError(f"invalid remote skill package: {exc}") from exc
            if parsed.metadata.name != bundle.name:
                raise SkillHubError("bundle name does not match SKILL.md name")
            scan = self.scanner.scan(package_root, source=bundle.source, trust_level=bundle.trust_level)
            allowed, reason = allow_skill_install(scan, force=force)
            if not allowed:
                raise SkillHubError(reason)
            target = self.root / "packages" / category / bundle.name
            existing = self.lock.get(bundle.name)
            if target.exists() and not (replace and existing):
                raise SkillHubError(f"skill already exists: {bundle.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = staging / "existing"
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(package_root, target)
                content_hash = bundle_content_hash(bundle)
                entry = {
                    "name": bundle.name,
                    "description": bundle.description,
                    "source": bundle.source,
                    "identifier": bundle.identifier,
                    "trust_level": bundle.trust_level,
                    "install_path": target.relative_to(self.root).as_posix(),
                    "content_hash": content_hash,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                    "scan_verdict": scan.verdict,
                    "repository_url": bundle.metadata.get("repository_url"),
                    "source_ref": bundle.metadata.get("source_ref"),
                    "source_path": bundle.metadata.get("source_path"),
                }
                self.lock.set(bundle.name, entry)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    os.replace(backup, target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            self._audit("update" if replace else "install", bundle.name, bundle.source, scan.verdict)
            return {"ok": True, **entry}
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _source_for(self, identifier: str):
        for source in self.sources:
            matches = getattr(source, "matches", None)
            if callable(matches) and matches(identifier):
                return source
        if len(self.sources) == 1:
            return self.sources[0]
        prefix = identifier.split("/", 1)[0]
        for source in self.sources:
            if getattr(source, "source_id", "") == prefix:
                return source
        raise SkillHubError(f"no source adapter for identifier: {identifier}")

    @staticmethod
    def _bundle_target(package_root: Path, relative: str) -> Path:
        posix = PurePosixPath(relative.replace("\\", "/"))
        windows = PureWindowsPath(relative)
        if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or not posix.parts:
            raise SkillHubError(f"unsafe bundle path: {relative}")
        target = (package_root / Path(*posix.parts)).resolve()
        if package_root.resolve() not in target.parents:
            raise SkillHubError(f"unsafe bundle path: {relative}")
        return target

    def _audit(self, action: str, name: str, source: str, outcome: str) -> None:
        path = self.root / ".hub" / "audit.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "name": name,
            "source": source,
            "outcome": outcome,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
