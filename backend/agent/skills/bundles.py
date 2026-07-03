from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

import yaml

from agent.skills.parser import SkillPackageError
from agent.skills.registry import SkillRegistry
from agent.skills.hub import HubLockFile
from agent.skills.usage import SkillUsageStore


class SkillBundleError(ValueError):
    pass


class SkillBundleStore:
    def __init__(self, root: str | Path, registry: SkillRegistry):
        self.root = Path(root)
        self.directory = self.root / "bundles"
        self.registry = registry
        self.usage = SkillUsageStore(self.root)
        self.hub_lock = HubLockFile(self.root)

    def create(
        self,
        name: str,
        skills: list[str],
        *,
        description: str = "",
        instruction: str = "",
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise SkillBundleError("bundle mutation requires confirmation")
        slug = self._slug(name)
        members = [member.strip() for member in skills if member.strip()]
        if not members:
            raise SkillBundleError("bundle requires at least one skill")
        for member in members:
            try:
                self.registry.view(member, include_unavailable=True)
            except KeyError as exc:
                raise SkillBundleError(f"unknown skill in bundle: {member}") from exc
        path = self.directory / f"{slug}.yaml"
        if path.exists():
            raise SkillBundleError(f"bundle already exists: {slug}")
        payload = {
            "name": slug,
            "description": description,
            "skills": members,
            "instruction": instruction,
        }
        self._write(path, payload)
        return {"ok": True, **payload}

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []
        return [self._read(path) for path in sorted(self.directory.glob("*.yaml"))]

    def show(self, name: str) -> dict[str, Any]:
        path = self.directory / f"{self._slug(name)}.yaml"
        if not path.is_file():
            raise SkillBundleError(f"bundle not found: {name}")
        return self._read(path)

    def load(self, name: str) -> dict[str, Any]:
        bundle = self.show(name)
        sections = []
        instruction = str(bundle.get("instruction") or "").strip()
        if instruction:
            sections.append(instruction)
        for member in bundle["skills"]:
            try:
                package = self.registry.view(member)
            except KeyError as exc:
                raise SkillBundleError(f"unknown skill in bundle: {member}") from exc
            except SkillPackageError as exc:
                raise SkillBundleError(f"skill unavailable in bundle: {member}: {exc}") from exc
            sections.append(f"## Skill: {member}\n\n{package.body}")
            if self.hub_lock.get(member) is None:
                self.usage.increment_use(member)
        return {
            "ok": True,
            "name": bundle["name"],
            "skills": list(bundle["skills"]),
            "content": "\n\n".join(sections),
        }

    def delete(self, name: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise SkillBundleError("bundle mutation requires confirmation")
        path = self.directory / f"{self._slug(name)}.yaml"
        if not path.is_file():
            raise SkillBundleError(f"bundle not found: {name}")
        path.unlink()
        return {"ok": True, "action": "delete", "name": self._slug(name)}

    def _read(self, path: Path) -> dict[str, Any]:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise SkillBundleError(f"invalid bundle mapping: {path.stem}")
        skills = loaded.get("skills")
        if not isinstance(skills, list) or not skills or not all(isinstance(item, str) and item for item in skills):
            raise SkillBundleError(f"bundle requires at least one skill: {path.stem}")
        return {
            "name": self._slug(str(loaded.get("name") or path.stem)),
            "description": str(loaded.get("description") or ""),
            "skills": skills,
            "instruction": str(loaded.get("instruction") or ""),
        }

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".yaml.tmp")
        temporary.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
        if not slug:
            raise SkillBundleError("bundle name is required")
        if not slug[0].isalpha():
            slug = f"bundle-{slug}"
        return slug
