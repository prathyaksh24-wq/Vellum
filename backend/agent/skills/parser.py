from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agent.skills.models import SkillMetadata, SkillPackage


class SkillPackageError(ValueError):
    pass


class SkillPackageParser:
    def __init__(self, *, max_file_bytes: int = 256_000, max_package_bytes: int = 2_000_000):
        self.max_file_bytes = max_file_bytes
        self.max_package_bytes = max_package_bytes

    def parse(
        self,
        root: str | Path,
        *,
        state: str = "active",
        source_root: str | Path | None = None,
        is_external: bool = False,
    ) -> SkillPackage:
        package_root = Path(root).resolve()
        skill_file = package_root / "SKILL.md"
        if not skill_file.is_file():
            raise SkillPackageError("skill package must contain SKILL.md")
        self._validate_tree(package_root)
        text = self._read_text(skill_file)
        frontmatter, body = self._split_frontmatter(text)
        try:
            raw: Any = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError as exc:
            raise SkillPackageError(f"invalid YAML frontmatter: {exc}") from exc
        if not isinstance(raw, dict):
            raise SkillPackageError("skill frontmatter must be a mapping")
        try:
            metadata = SkillMetadata.model_validate(raw)
        except ValidationError as exc:
            raise SkillPackageError(f"invalid skill metadata: {exc}") from exc
        if not body.strip():
            raise SkillPackageError("skill body cannot be empty")
        resolved_source = Path(source_root).resolve() if source_root else package_root.parent
        return SkillPackage(
            root=package_root,
            skill_file=skill_file,
            metadata=metadata,
            body=body.strip(),
            state=state,
            source_root=resolved_source,
            is_external=is_external,
        )

    def read_support_file(self, root: str | Path, relative_path: str) -> str:
        package_root = Path(root).resolve()
        target = (package_root / relative_path).resolve()
        if target == package_root or package_root not in target.parents:
            raise SkillPackageError("support file must stay inside the skill package")
        if target.name == "SKILL.md":
            raise SkillPackageError("use package parsing to read SKILL.md")
        if target.is_symlink() or not target.is_file():
            raise SkillPackageError("support file is missing or unsafe")
        return self._read_text(target)

    def _read_text(self, path: Path) -> str:
        if path.stat().st_size > self.max_file_bytes:
            raise SkillPackageError("skill file exceeds size limit")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SkillPackageError(f"cannot read skill file: {exc}") from exc

    def _validate_tree(self, root: Path) -> None:
        total = 0
        for path in root.rglob("*"):
            if path.is_symlink():
                raise SkillPackageError("skill packages cannot contain symlinks")
            if path.is_file():
                size = path.stat().st_size
                if size > self.max_file_bytes:
                    raise SkillPackageError("skill file exceeds size limit")
                total += size
                if total > self.max_package_bytes:
                    raise SkillPackageError("skill package exceeds size limit")

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[str, str]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillPackageError("SKILL.md must start with YAML frontmatter")
        try:
            closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        except StopIteration as exc:
            raise SkillPackageError("SKILL.md frontmatter is not closed") from exc
        return "\n".join(lines[1:closing]), "\n".join(lines[closing + 1 :])
