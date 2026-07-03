from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

import yaml

from agent.skills.parser import SkillPackageParser


@dataclass
class MigrationReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


class JsonSkillMigrator:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.parser = SkillPackageParser()

    def migrate(self) -> MigrationReport:
        report = MigrationReport()
        sources = sorted((self.root / "active").glob("*.json")) if (self.root / "active").exists() else []
        candidates: list[tuple[str, dict[str, Any]]] = []
        for source in sources:
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report.invalid.append(source.stem)
                continue
            if not isinstance(payload, dict) or not payload.get("instructions"):
                report.invalid.append(source.stem)
                continue
            slug = self._slug(str(payload.get("id") or source.stem))
            target = self.root / "packages" / "uncategorized" / slug
            if target.exists():
                report.skipped.append(slug)
                continue
            candidates.append((slug, payload))
        if not candidates:
            return report

        self.root.mkdir(parents=True, exist_ok=True)
        staging_parent = Path(tempfile.mkdtemp(prefix="skill-migration-", dir=self.root))
        try:
            staged_packages = staging_parent / "packages"
            usage_updates: dict[str, Any] = {}
            for slug, payload in candidates:
                package_root = staged_packages / "uncategorized" / slug
                package_root.mkdir(parents=True)
                (package_root / "SKILL.md").write_text(self._render(slug, payload), encoding="utf-8")
                self.parser.parse(package_root)
                usage_updates[slug] = self._usage(payload)
            live_packages = self.root / "packages"
            live_packages.mkdir(parents=True, exist_ok=True)
            category = live_packages / "uncategorized"
            category.mkdir(parents=True, exist_ok=True)
            published: list[Path] = []
            try:
                for slug, _payload in candidates:
                    source = staged_packages / "uncategorized" / slug
                    target = category / slug
                    if target.exists():
                        raise FileExistsError(f"canonical skill appeared during migration: {slug}")
                    os.replace(source, target)
                    published.append(target)
                self._merge_usage(usage_updates)
            except Exception:
                for target in reversed(published):
                    shutil.rmtree(target, ignore_errors=True)
                raise
            report.created.extend(slug for slug, _payload in candidates)
            return report
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

    def _render(self, slug: str, payload: dict[str, Any]) -> str:
        route = payload.get("route_to_agent")
        frontmatter = {
            "name": slug,
            "description": str(payload.get("name") or slug)[:120],
            "version": "1.0.0",
            "metadata": {
                "hermes": {
                    "category": "uncategorized",
                    "tags": ["migrated", "vellum"],
                },
                "vellum": {
                    "trigger": list(payload.get("trigger") or []),
                    "negative_trigger": list(payload.get("negative_trigger") or []),
                    "confidence_threshold": float(payload.get("confidence_threshold", 0.75)),
                    "route_to_agent": route,
                    "routing_critical": bool(route),
                },
            },
            "x-vellum-legacy-id": str(payload.get("id") or slug),
            "x-vellum-created": payload.get("created"),
            "x-vellum-approved": payload.get("approved"),
        }
        optional = {
            "source": payload.get("source"),
            "install_command": payload.get("install_command"),
        }
        frontmatter.update({key: value for key, value in optional.items() if value})
        sections = [
            f"# {payload.get('name') or slug}",
            "## When to Use\n" + self._trigger_text(payload),
            "## Procedure\n" + str(payload["instructions"]).strip(),
        ]
        if payload.get("when_not_to_use"):
            sections.append("## Pitfalls\n" + str(payload["when_not_to_use"]).strip())
        verification = []
        if payload.get("citation_style"):
            verification.append(f"Citation style: {payload['citation_style']}")
        if payload.get("output_format"):
            verification.append(f"Output format: {payload['output_format']}")
        sections.append("## Verification\n" + ("\n".join(verification) or "Confirm the requested workflow completed."))
        dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{dumped}\n---\n\n" + "\n\n".join(sections) + "\n"

    @staticmethod
    def _trigger_text(payload: dict[str, Any]) -> str:
        triggers = [str(value) for value in payload.get("trigger") or []]
        return "Use when the request matches: " + ", ".join(triggers) + "."

    @staticmethod
    def _usage(payload: dict[str, Any]) -> dict[str, Any]:
        created = payload.get("created")
        if created and "T" not in str(created):
            created = f"{created}T00:00:00Z"
        return {
            "view_count": 0,
            "use_count": int(payload.get("use_count") or 0),
            "patch_count": 0,
            "last_viewed_at": None,
            "last_used_at": payload.get("last_used"),
            "last_patched_at": None,
            "created_at": created or datetime.now(timezone.utc).isoformat(),
            "created_by": None,
            "state": "active",
            "pinned": False,
            "archived_at": None,
        }

    def _merge_usage(self, updates: dict[str, Any]) -> None:
        path = self.root / ".usage.json"
        current: dict[str, Any] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        for name, value in updates.items():
            current.setdefault(name, value)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
        if not slug or not slug[0].isalpha():
            slug = f"skill-{slug or 'migrated'}"
        return slug
