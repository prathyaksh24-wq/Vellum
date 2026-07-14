from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
from typing import Any

import yaml

from agent.skills.catalog import SkillCatalog, SkillCatalogError, package_content_hash
from agent.skills.parser import SkillPackageParser


@dataclass
class MigrationReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    mappings: list[dict[str, Any]] = field(default_factory=list)
    parity_errors: list[str] = field(default_factory=list)
    exact_collisions: list[list[str]] = field(default_factory=list)
    semantic_collisions: list[list[str]] = field(default_factory=list)
    delete_files: list[str] = field(default_factory=list)
    rollback_snapshot: str | None = None
    clean: bool = False
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonSkillMigrator:
    """One-time, recoverable migration from legacy JSON to Hermes packages."""

    def __init__(self, root: str | Path, *, catalog_path: str | Path | None = None):
        self.root = Path(root)
        self.parser = SkillPackageParser()
        self.catalog_path = Path(catalog_path) if catalog_path else self.root.parent / "data" / "skills" / "catalog.db"
        self.snapshots = self.root / ".migration_snapshots"
        self.state_path = self.root / ".migration_state.json"

    def dry_run(self) -> MigrationReport:
        report = MigrationReport()
        sources = self._sources()
        hashes: dict[str, str] = {}
        for source in sources:
            payload = self._payload(source, report)
            if payload is None:
                continue
            slug = self._slug(str(payload.get("id") or source.stem))
            target = self.root / "packages" / "uncategorized" / slug
            mapping = {
                "source": source.relative_to(self.root).as_posix(),
                "target": target.relative_to(self.root).as_posix(),
                "name": slug,
                "metadata": False,
                "triggers": False,
                "routing": False,
                "instructions": False,
                "usage": False,
            }
            if target.exists():
                try:
                    package = self.parser.parse(target)
                    vellum = package.metadata.metadata.vellum
                    mapping["metadata"] = package.metadata.name == slug and bool(package.metadata.description)
                    mapping["triggers"] = list(vellum.trigger) == list(payload.get("trigger") or []) and list(vellum.negative_trigger) == list(payload.get("negative_trigger") or [])
                    mapping["routing"] = vellum.route_to_agent == payload.get("route_to_agent") and vellum.routing_critical == bool(payload.get("route_to_agent"))
                    mapping["instructions"] = str(payload["instructions"]).strip() in package.body
                    usage = self._read_usage().get(slug, {})
                    mapping["usage"] = int(usage.get("use_count") or 0) == int(payload.get("use_count") or 0)
                    content_hash = package_content_hash(target)
                    if content_hash in hashes:
                        report.exact_collisions.append([hashes[content_hash], slug])
                    hashes[content_hash] = slug
                    report.skipped.append(slug)
                except Exception as exc:
                    report.parity_errors.append(f"{slug}: {exc}")
            else:
                staging = Path(tempfile.mkdtemp(prefix="skill-dry-run-", dir=self.root))
                try:
                    package_root = staging / slug
                    package_root.mkdir()
                    (package_root / "SKILL.md").write_text(self._render(slug, payload), encoding="utf-8")
                    self.parser.parse(package_root)
                    mapping.update({"metadata": True, "triggers": True, "routing": True, "instructions": True, "usage": True})
                    report.created.append(slug)
                except Exception as exc:
                    report.parity_errors.append(f"{slug}: {exc}")
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
            missing = [key for key in ("metadata", "triggers", "routing", "instructions", "usage") if not mapping[key]]
            if missing:
                report.parity_errors.append(f"{slug}: parity failed for {', '.join(missing)}")
            report.mappings.append(mapping)
            report.delete_files.append(source.relative_to(self.root).as_posix())
        snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        report.rollback_snapshot = (self.snapshots / snapshot_id).relative_to(self.root).as_posix()
        report.clean = not report.invalid and not report.parity_errors and not report.exact_collisions
        return report

    def migrate(self) -> MigrationReport:
        return self.apply()

    def apply(self) -> MigrationReport:
        report = self.dry_run()
        if not report.clean:
            raise SkillCatalogError("legacy skill migration dry-run is not clean: " + "; ".join(report.parity_errors + report.invalid))
        if not report.mappings:
            report.applied = True
            return report
        snapshot_id = Path(str(report.rollback_snapshot)).name
        self._snapshot(snapshot_id)
        self._write_state({"status": "applying", "snapshot": snapshot_id, "started_at": datetime.now(timezone.utc).isoformat()})
        staging = Path(tempfile.mkdtemp(prefix="skill-migration-", dir=self.root))
        published: list[Path] = []
        try:
            usage_updates: dict[str, Any] = {}
            for source in self._sources():
                payload = json.loads(source.read_text(encoding="utf-8"))
                slug = self._slug(str(payload.get("id") or source.stem))
                target = self.root / "packages" / "uncategorized" / slug
                if not target.exists():
                    staged = staging / slug
                    staged.mkdir()
                    (staged / "SKILL.md").write_text(self._render(slug, payload), encoding="utf-8")
                    self.parser.parse(staged)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, target)
                    published.append(target)
                usage_updates[slug] = self._usage(payload)
            self._merge_usage(usage_updates)
            catalog = SkillCatalog(self.root, db_path=self.catalog_path)
            catalog.reconcile(embed_semantics=False)
            for source in self._sources():
                source.unlink()
            if (self.root / "active").exists() and not any((self.root / "active").iterdir()):
                (self.root / "active").rmdir()
            if len(report.mappings) != 13 and self.root.resolve() == Path(".skills").resolve():
                raise SkillCatalogError(f"expected 13 repository legacy skills, found {len(report.mappings)}")
            report.applied = True
            self._write_state({"status": "completed", "snapshot": snapshot_id, "completed_at": datetime.now(timezone.utc).isoformat()})
            return report
        except Exception:
            self.rollback(snapshot_id)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def rollback(self, snapshot: str) -> dict[str, Any]:
        archive = self.snapshots / Path(snapshot).name / "skills.tar.gz"
        if not archive.is_file():
            raise SkillCatalogError(f"migration snapshot not found: {snapshot}")
        staging = Path(tempfile.mkdtemp(prefix="skill-rollback-", dir=self.root.parent))
        try:
            with tarfile.open(archive, "r:gz") as handle:
                for member in handle.getmembers():
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                        raise SkillCatalogError("unsafe migration snapshot")
                handle.extractall(staging, filter="data")
            for child in list(self.root.iterdir()):
                if child.name != ".migration_snapshots":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
            for child in staging.iterdir():
                os.replace(child, self.root / child.name)
            self._write_state({"status": "rolled_back", "snapshot": Path(snapshot).name, "rolled_back_at": datetime.now(timezone.utc).isoformat()})
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return {"ok": True, "restored": Path(snapshot).name}

    def recover_interrupted(self) -> dict[str, Any] | None:
        if not self.state_path.is_file():
            return None
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("status") != "applying":
            return None
        return self.rollback(str(state["snapshot"]))

    def _snapshot(self, identifier: str) -> None:
        target = self.snapshots / identifier
        target.mkdir(parents=True, exist_ok=False)
        with tarfile.open(target / "skills.tar.gz", "w:gz") as handle:
            for child in sorted(self.root.iterdir()):
                if child.name in {".migration_snapshots", ".locks", ".staging"}:
                    continue
                handle.add(child, arcname=child.name, recursive=True)

    def _sources(self) -> list[Path]:
        active = self.root / "active"
        return sorted(active.glob("*.json")) if active.exists() else []

    @staticmethod
    def _payload(source: Path, report: MigrationReport) -> dict[str, Any] | None:
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report.invalid.append(source.stem)
            return None
        if not isinstance(payload, dict) or not payload.get("instructions"):
            report.invalid.append(source.stem)
            return None
        return payload

    def _read_usage(self) -> dict[str, Any]:
        path = self.root / ".usage.json"
        if not path.is_file():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}

    def _render(self, slug: str, payload: dict[str, Any]) -> str:
        route = payload.get("route_to_agent")
        frontmatter = {
            "name": slug,
            "description": str(payload.get("name") or slug)[:120],
            "version": "1.0.0",
            "metadata": {"hermes": {"category": "uncategorized", "tags": ["migrated", "vellum"]}, "vellum": {
                "trigger": list(payload.get("trigger") or []), "negative_trigger": list(payload.get("negative_trigger") or []),
                "confidence_threshold": float(payload.get("confidence_threshold", 0.75)), "route_to_agent": route, "routing_critical": bool(route)}},
            "x-vellum-legacy-id": str(payload.get("id") or slug), "x-vellum-created": payload.get("created"), "x-vellum-approved": payload.get("approved"),
        }
        frontmatter.update({key: payload[key] for key in ("source", "install_command") if payload.get(key)})
        sections = [f"# {payload.get('name') or slug}", "## When to Use\n" + self._trigger_text(payload), "## Procedure\n" + str(payload["instructions"]).strip()]
        if payload.get("when_not_to_use"):
            sections.append("## Pitfalls\n" + str(payload["when_not_to_use"]).strip())
        verification = []
        if payload.get("citation_style"):
            verification.append(f"Citation style: {payload['citation_style']}")
        if payload.get("output_format"):
            verification.append(f"Output format: {payload['output_format']}")
        sections.append("## Verification\n" + ("\n".join(verification) or "Confirm the requested workflow completed."))
        return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()}\n---\n\n" + "\n\n".join(sections) + "\n"

    @staticmethod
    def _trigger_text(payload: dict[str, Any]) -> str:
        return "Use when the request matches: " + ", ".join(str(value) for value in payload.get("trigger") or []) + "."

    @staticmethod
    def _usage(payload: dict[str, Any]) -> dict[str, Any]:
        created = payload.get("created")
        if created and "T" not in str(created):
            created = f"{created}T00:00:00Z"
        return {"view_count": 0, "use_count": int(payload.get("use_count") or 0), "patch_count": 0, "last_viewed_at": None,
                "last_used_at": payload.get("last_used"), "last_patched_at": None, "created_at": created or datetime.now(timezone.utc).isoformat(),
                "created_by": None, "origin": "builtin", "state": "active", "pinned": False, "archived_at": None}

    def _merge_usage(self, updates: dict[str, Any]) -> None:
        path = self.root / ".usage.json"
        current = self._read_usage()
        for name, value in updates.items():
            current.setdefault(name, value)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _write_state(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
        return slug if slug and slug[0].isalpha() else f"skill-{slug or 'migrated'}"
