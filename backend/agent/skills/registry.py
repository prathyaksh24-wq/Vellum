from __future__ import annotations

import platform
from pathlib import Path

from agent.skills.models import SkillIndexEntry, SkillPackage
from agent.skills.parser import SkillPackageError, SkillPackageParser


_PLATFORM_MAP = {"darwin": "macos", "linux": "linux", "windows": "windows"}


class SkillRegistry:
    def __init__(
        self,
        *,
        local_root: str | Path,
        external_dirs: list[str | Path] | None = None,
        owned_external_dirs: dict[str | Path, str] | None = None,
        parser: SkillPackageParser | None = None,
        platform_name: str | None = None,
        available_toolsets: set[str] | None = None,
        available_tools: set[str] | None = None,
    ):
        self.local_root = Path(local_root)
        self.external_dirs = [Path(path) for path in external_dirs or []]
        self.owned_external_dirs = {Path(path): owner for path, owner in (owned_external_dirs or {}).items()}
        self.parser = parser or SkillPackageParser()
        detected = platform_name or _PLATFORM_MAP.get(platform.system().casefold(), platform.system().casefold())
        self.platform_name = detected.casefold()
        self.available_toolsets = available_toolsets or set()
        self.available_tools = available_tools or set()
        self._diagnostics: list[dict[str, str]] = []

    def list_skills(self, *, include_unavailable: bool = False) -> list[SkillIndexEntry]:
        packages = self._packages()
        entries = []
        for name, package in sorted(packages.items()):
            available, reason = self._availability(package)
            if not available and not include_unavailable:
                continue
            entries.append(
                SkillIndexEntry(
                    name=name,
                    description=package.metadata.description,
                    category=package.metadata.metadata.hermes.category,
                    state=package.state,
                    available=available,
                    unavailable_reason=reason,
                    package_root=str(package.root),
                    owner_plugin=package.owner_plugin,
                    is_external=package.is_external,
                )
            )
        return entries

    def view(self, name: str, *, include_unavailable: bool = False) -> SkillPackage:
        package = self._packages().get(name)
        if package is None:
            raise KeyError(name)
        available, reason = self._availability(package)
        if not available and not include_unavailable:
            raise SkillPackageError(reason or "skill is unavailable")
        return package

    def view_file(self, name: str, relative_path: str) -> str:
        package = self.view(name)
        return self.parser.read_support_file(package.root, relative_path)

    def diagnostics(self) -> list[dict[str, str]]:
        self._packages()
        return list(self._diagnostics)

    def _packages(self) -> dict[str, SkillPackage]:
        self._diagnostics = []
        packages: dict[str, SkillPackage] = {}
        for root, is_external, owner_plugin in [
            *[(path, True, None) for path in self.external_dirs],
            *[(path, True, owner) for path, owner in self.owned_external_dirs.items()],
            (self.local_root, False, None),
        ]:
            if not root.exists():
                continue
            for skill_file in sorted(root.rglob("SKILL.md")):
                package_root = skill_file.parent
                try:
                    package = self.parser.parse(
                        package_root,
                        source_root=root,
                        is_external=is_external,
                    )
                    if owner_plugin:
                        package = package.model_copy(update={"owner_plugin": owner_plugin})
                except SkillPackageError as exc:
                    self._diagnostics.append({"path": str(package_root), "error": str(exc)})
                    continue
                if is_external and package.metadata.name in packages:
                    continue
                packages[package.metadata.name] = package
        return packages

    def _availability(self, package: SkillPackage) -> tuple[bool, str | None]:
        metadata = package.metadata
        if metadata.platforms and self.platform_name not in metadata.platforms:
            return False, f"skill is unavailable on {self.platform_name}"
        hermes = metadata.metadata.hermes
        missing_toolsets = set(hermes.requires_toolsets) - self.available_toolsets
        if missing_toolsets:
            return False, f"missing required toolsets: {', '.join(sorted(missing_toolsets))}"
        missing_tools = set(hermes.requires_tools) - self.available_tools
        if missing_tools:
            return False, f"missing required tools: {', '.join(sorted(missing_tools))}"
        present_fallback_toolsets = set(hermes.fallback_for_toolsets) & self.available_toolsets
        if present_fallback_toolsets:
            return False, f"primary toolsets are available: {', '.join(sorted(present_fallback_toolsets))}"
        present_fallback_tools = set(hermes.fallback_for_tools) & self.available_tools
        if present_fallback_tools:
            return False, f"primary tools are available: {', '.join(sorted(present_fallback_tools))}"
        return True, None
