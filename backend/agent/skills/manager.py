from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Callable

from agent.skills.models import SkillPackage
from agent.skills.parser import SkillPackageError, SkillPackageParser
from agent.skills.registry import SkillRegistry
from agent.skills.suggestions import BlueprintSuggestionStore
from agent.skills.usage import SkillUsageStore


_CATEGORY = re.compile(r"^[a-z][a-z0-9_-]*$")


class SkillMutationError(ValueError):
    pass


class SkillManager:
    def __init__(self, root: str | Path, *, require_confirmation: bool = True):
        self.root = Path(root)
        self.require_confirmation = require_confirmation
        self.parser = SkillPackageParser()
        self.registry = SkillRegistry(local_root=self.root / "packages")
        self.usage = SkillUsageStore(self.root)
        self.suggestions = BlueprintSuggestionStore(self.root)

    def package(self, name: str) -> SkillPackage:
        try:
            return self.registry.view(name)
        except KeyError as exc:
            raise SkillMutationError(f"skill not found: {name}") from exc

    def create(
        self,
        skill_md: str,
        *,
        category: str = "uncategorized",
        origin: str = "foreground",
        confirm: bool = False,
    ) -> dict:
        self._require_confirmation(confirm)
        clean_category = self._category(category)
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="skill-create-", dir=self.root))
        try:
            staged_package = staging / "package"
            staged_package.mkdir()
            (staged_package / "SKILL.md").write_text(skill_md, encoding="utf-8")
            package = self._parse(staged_package)
            name = package.metadata.name
            if self._name_exists(name):
                raise SkillMutationError(f"skill already exists: {name}")
            target = self.root / "packages" / clean_category / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_package, target)
            self.usage.mark_created(name, origin=origin)
            result = {"ok": True, "action": "create", "name": name, "state": "active"}
            blueprint = package.metadata.metadata.hermes.blueprint
            if blueprint is not None:
                suggestion = self.suggestions.observe(
                    skill_name=name,
                    schedule=blueprint.schedule,
                    deliver=blueprint.deliver,
                    prompt=blueprint.prompt,
                    no_agent=blueprint.no_agent,
                )
                result["suggestion_id"] = suggestion["id"]
            return result
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def patch(self, name: str, old_text: str, new_text: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)
        if not old_text:
            raise SkillMutationError("patch requires non-empty old_text")

        def mutate(root: Path) -> None:
            path = root / "SKILL.md"
            current = path.read_text(encoding="utf-8")
            if current.count(old_text) != 1:
                raise SkillMutationError("patch old_text must occur exactly once")
            path.write_text(current.replace(old_text, new_text, 1), encoding="utf-8")

        return self._mutate_package(name, "patch", mutate)

    def edit(self, name: str, skill_md: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)

        def mutate(root: Path) -> None:
            (root / "SKILL.md").write_text(skill_md, encoding="utf-8")

        return self._mutate_package(name, "edit", mutate, expected_name=name)

    def write_file(self, name: str, path: str, content: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)

        def mutate(root: Path) -> None:
            target = self._safe_target(root, path)
            if target.name == "SKILL.md":
                raise SkillMutationError("use edit to replace SKILL.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        return self._mutate_package(name, "write_file", mutate)

    def remove_file(self, name: str, path: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)

        def mutate(root: Path) -> None:
            target = self._safe_target(root, path)
            if target.name == "SKILL.md":
                raise SkillMutationError("SKILL.md cannot be removed")
            if not target.is_file() or target.is_symlink():
                raise SkillMutationError(f"support file not found: {path}")
            target.unlink()

        return self._mutate_package(name, "remove_file", mutate)

    def archive(self, name: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)
        package = self.package(name)
        category = package.root.parent.name
        target = self.root / ".archive" / category / name
        if target.exists():
            raise SkillMutationError(f"archived skill already exists: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(package.root, target)
        self.usage.set_state(name, "archived")
        return {"ok": True, "action": "archive", "name": name, "state": "archived"}

    def approve(self, name: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)
        source = self._locate(self.root / "proposed", name)
        if source is None:
            raise SkillMutationError(f"proposed skill not found: {name}")
        package = self._parse(source)
        if package.metadata.name != name:
            raise SkillMutationError("proposed package name does not match directory")
        category = source.parent.name
        target = self.root / "packages" / category / name
        if target.exists():
            raise SkillMutationError(f"active skill already exists: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        if name not in self.usage.all():
            self.usage.mark_created(name, origin="background_review")
        self.usage.set_state(name, "active")
        return {"ok": True, "action": "approve", "name": name, "state": "active"}

    def retire(self, name: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)
        package = self.package(name)
        category = package.root.parent.name
        target = self.root / "retired" / category / name
        if target.exists():
            raise SkillMutationError(f"retired skill already exists: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(package.root, target)
        self.usage.set_state(name, "retired")
        return {"ok": True, "action": "retire", "name": name, "state": "retired"}

    def restore(self, name: str, *, confirm: bool = False) -> dict:
        self._require_confirmation(confirm)
        source = self._locate(self.root / ".archive", name)
        if source is None:
            raise SkillMutationError(f"archived skill not found: {name}")
        category = source.parent.name
        target = self.root / "packages" / category / name
        if target.exists():
            raise SkillMutationError(f"active skill already exists: {name}")
        self._parse(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        self.usage.set_state(name, "active")
        return {"ok": True, "action": "restore", "name": name, "state": "active"}

    def delete(self, name: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise SkillMutationError("skill deletion requires confirmation")
        if self.usage.get(name).get("pinned") is True:
            raise SkillMutationError(f"skill is pinned; unpin before deletion: {name}")
        source = self._locate(self.root / "packages", name) or self._locate(self.root / ".archive", name)
        if source is None:
            raise SkillMutationError(f"skill not found: {name}")
        shutil.rmtree(source)
        self.usage.remove(name)
        return {"ok": True, "action": "delete", "name": name}

    def _mutate_package(
        self,
        name: str,
        action: str,
        mutate: Callable[[Path], None],
        *,
        expected_name: str | None = None,
    ) -> dict:
        source = self.package(name).root
        staging = Path(tempfile.mkdtemp(prefix="skill-edit-", dir=self.root))
        staged_package = staging / "package"
        backup = staging / "original"
        try:
            shutil.copytree(source, staged_package)
            mutate(staged_package)
            parsed = self._parse(staged_package)
            if expected_name and parsed.metadata.name != expected_name:
                raise SkillMutationError("skill name cannot change during edit")
            os.replace(source, backup)
            try:
                os.replace(staged_package, source)
            except Exception:
                os.replace(backup, source)
                raise
            shutil.rmtree(backup, ignore_errors=True)
            self.usage.increment_patch(name)
            return {"ok": True, "action": action, "name": name}
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _parse(self, root: Path) -> SkillPackage:
        try:
            return self.parser.parse(root)
        except SkillPackageError as exc:
            raise SkillMutationError(f"invalid skill package: {exc}") from exc

    def _require_confirmation(self, confirm: bool) -> None:
        if self.require_confirmation and not confirm:
            raise SkillMutationError("skill mutation requires confirmation")

    def _name_exists(self, name: str) -> bool:
        return any(
            self._locate(base, name) is not None
            for base in [self.root / "packages", self.root / "proposed", self.root / "retired", self.root / ".archive"]
        )

    @staticmethod
    def _category(value: str) -> str:
        clean = value.casefold().strip()
        if not _CATEGORY.fullmatch(clean):
            raise SkillMutationError("category must be a lowercase slug")
        return clean

    @staticmethod
    def _safe_target(root: Path, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise SkillMutationError("support file must stay inside the skill package")
        target = (root / candidate).resolve()
        resolved_root = root.resolve()
        if target == resolved_root or resolved_root not in target.parents:
            raise SkillMutationError("support file must stay inside the skill package")
        return target

    def _locate(self, base: Path, name: str) -> Path | None:
        if not base.exists():
            return None
        matches = [path.parent for path in base.rglob("SKILL.md") if path.parent.name == name]
        return sorted(matches)[0] if matches else None
