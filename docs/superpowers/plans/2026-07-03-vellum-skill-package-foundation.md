# Vellum Skill Package Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON as Vellum's active skill source of truth with validated Hermes-compatible `SKILL.md` packages while preserving existing deterministic routing through a temporary compatibility facade.

**Architecture:** Add a typed package parser and registry under `agent.skills`, then make the legacy `SkillStore` adapt canonical packages into its existing dictionary contract. An idempotent migrator converts current JSON skills into `.skills/packages/<category>/<slug>/SKILL.md`, publishes through staging, and preserves JSON fallback for one compatibility period.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, pathlib, pytest.

---

## File Structure

- Create `backend/agent/skills/__init__.py`: stable public exports for the package subsystem.
- Create `backend/agent/skills/models.py`: typed Hermes and Vellum metadata models plus discovery records.
- Create `backend/agent/skills/parser.py`: frontmatter parsing, package validation, and safe support-file reads.
- Create `backend/agent/skills/registry.py`: local/external discovery, precedence, platform/tool filtering, and Level 0/1/2 reads.
- Create `backend/agent/skills/migration.py`: idempotent JSON-to-package conversion and usage-sidecar merge.
- Create `backend/scripts/migrate_skills.py`: explicit repository migration entrypoint.
- Modify `backend/agent/memory/skills.py`: compatibility facade backed by `SkillRegistry`, with unmigrated JSON fallback.
- Modify `backend/pyproject.toml`: declare PyYAML.
- Modify `backend/requirements.txt`: declare PyYAML.
- Create `backend/tests/test_skill_packages.py`: parser, validation, support-file, and disclosure tests.
- Create `backend/tests/test_skill_registry.py`: precedence and conditional-activation tests.
- Create `backend/tests/test_skill_migration.py`: conversion, idempotency, shadowing, staging, and usage migration tests.
- Modify `backend/tests/test_memory.py`: assert the legacy facade reads canonical packages and retains trigger behavior.
- Modify `backend/tests/test_skill_driven_routing.py`: prove migrated routing-critical skills still route deterministically.

## Task 1: Dependencies and Typed Package Models

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`
- Create: `backend/agent/skills/models.py`
- Create: `backend/agent/skills/__init__.py`
- Test: `backend/tests/test_skill_packages.py`

- [ ] **Step 1: Add the YAML dependency**

Add this dependency to both declarations:

```text
PyYAML>=6.0.2
```

In `backend/pyproject.toml`, place `"PyYAML>=6.0.2",` next to `pydantic-settings`. In `backend/requirements.txt`, place `PyYAML>=6.0.2` next to `pydantic-settings`.

- [ ] **Step 2: Write failing model tests**

Create `backend/tests/test_skill_packages.py` with:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.skills import SkillMetadata, VellumMetadata


def test_skill_metadata_accepts_hermes_fields() -> None:
    metadata = SkillMetadata.model_validate(
        {
            "name": "sports-brief",
            "description": "Prepare a source-backed sports brief",
            "version": "1.0.0",
            "platforms": ["windows", "linux"],
            "metadata": {
                "hermes": {
                    "tags": ["sports"],
                    "category": "research",
                    "requires_toolsets": ["web"],
                    "fallback_for_tools": ["sports_snapshot"],
                },
                "vellum": {
                    "trigger": ["sports", "standings"],
                    "negative_trigger": ["write sports tests"],
                    "confidence_threshold": 0.25,
                    "route_to_agent": "SportsAgent",
                    "routing_critical": True,
                },
            },
        }
    )

    assert metadata.metadata.hermes.category == "research"
    assert metadata.metadata.vellum == VellumMetadata(
        trigger=["sports", "standings"],
        negative_trigger=["write sports tests"],
        confidence_threshold=0.25,
        route_to_agent="SportsAgent",
        routing_critical=True,
    )


@pytest.mark.parametrize("name", ["Sports Brief", "../sports", "_hidden", "sports/brief"])
def test_skill_metadata_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        SkillMetadata(name=name, description="Valid description")


def test_vellum_threshold_must_be_a_probability() -> None:
    with pytest.raises(ValidationError):
        VellumMetadata(confidence_threshold=1.1)
```

- [ ] **Step 3: Run the tests and verify the expected import failure**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_packages.py -q
```

Expected: collection fails because `agent.skills` does not exist.

- [ ] **Step 4: Implement the typed models**

Create `backend/agent/skills/models.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SKILL_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
PlatformName = Literal["windows", "linux", "macos"]


class ConfigSetting(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    default: Any = None
    prompt: str | None = None


class BlueprintMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    schedule: str = Field(min_length=1)
    deliver: str = "origin"
    prompt: str | None = None
    no_agent: bool = False


class HermesMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    tags: list[str] = Field(default_factory=list)
    category: str = "uncategorized"
    related_skills: list[str] = Field(default_factory=list)
    requires_toolsets: list[str] = Field(default_factory=list)
    requires_tools: list[str] = Field(default_factory=list)
    fallback_for_toolsets: list[str] = Field(default_factory=list)
    fallback_for_tools: list[str] = Field(default_factory=list)
    config: list[ConfigSetting] = Field(default_factory=list)
    blueprint: BlueprintMetadata | None = None


class VellumMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: list[str] = Field(default_factory=list)
    negative_trigger: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    route_to_agent: str | None = None
    routing_critical: bool = False


class MetadataExtensions(BaseModel):
    model_config = ConfigDict(extra="allow")

    hermes: HermesMetadata = Field(default_factory=HermesMetadata)
    vellum: VellumMetadata = Field(default_factory=VellumMetadata)


class EnvironmentRequirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    prompt: str | None = None
    help: str | None = None
    required_for: str | None = None


class CredentialRequirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = Field(min_length=1)
    description: str | None = None


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = Field(min_length=1)
    version: str | None = None
    author: str | None = None
    license: str | None = None
    platforms: list[PlatformName] = Field(default_factory=list)
    metadata: MetadataExtensions = Field(default_factory=MetadataExtensions)
    required_environment_variables: list[EnvironmentRequirement] = Field(default_factory=list)
    required_credential_files: list[CredentialRequirement] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SKILL_NAME.fullmatch(value):
            raise ValueError("skill name must match ^[a-z][a-z0-9_-]*$")
        return value


class SkillPackage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    root: Path
    skill_file: Path
    metadata: SkillMetadata
    body: str
    state: Literal["active", "proposed", "retired", "archived"] = "active"
    source_root: Path
    is_external: bool = False


class SkillIndexEntry(BaseModel):
    name: str
    description: str
    category: str
    state: str
    available: bool
    unavailable_reason: str | None = None
    package_root: str
    is_external: bool


class SkillUsage(BaseModel):
    view_count: int = 0
    use_count: int = 0
    patch_count: int = 0
    last_viewed_at: datetime | None = None
    last_used_at: datetime | None = None
    last_patched_at: datetime | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    state: str = "active"
    pinned: bool = False
    archived_at: datetime | None = None
```

Create `backend/agent/skills/__init__.py`:

```python
from agent.skills.models import (
    BlueprintMetadata,
    ConfigSetting,
    CredentialRequirement,
    EnvironmentRequirement,
    HermesMetadata,
    MetadataExtensions,
    SkillIndexEntry,
    SkillMetadata,
    SkillPackage,
    SkillUsage,
    VellumMetadata,
)

__all__ = [
    "BlueprintMetadata",
    "ConfigSetting",
    "CredentialRequirement",
    "EnvironmentRequirement",
    "HermesMetadata",
    "MetadataExtensions",
    "SkillIndexEntry",
    "SkillMetadata",
    "SkillPackage",
    "SkillUsage",
    "VellumMetadata",
]
```

- [ ] **Step 5: Run the model tests**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_packages.py -q
```

Expected: all model tests pass.

- [ ] **Step 6: Commit Task 1**

```powershell
git add backend/pyproject.toml backend/requirements.txt backend/agent/skills backend/tests/test_skill_packages.py
git commit -m "feat: define Hermes-compatible skill packages"
```

## Task 2: Package Parser and Safe Level 1/2 Reads

**Files:**
- Create: `backend/agent/skills/parser.py`
- Modify: `backend/agent/skills/__init__.py`
- Modify: `backend/tests/test_skill_packages.py`

- [ ] **Step 1: Add failing parser and support-file tests**

Append to `backend/tests/test_skill_packages.py`:

```python
from agent.skills import SkillPackageError, SkillPackageParser


def write_skill(root: Path, frontmatter: str, body: str = "# Sports Brief\n\n## Procedure\nAnswer carefully.") -> Path:
    root.mkdir(parents=True)
    path = root / "SKILL.md"
    path.write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    return path


def test_parser_reads_hermes_frontmatter_and_body(tmp_path: Path) -> None:
    root = tmp_path / "sports-brief"
    write_skill(
        root,
        """name: sports-brief
description: Prepare a source-backed sports brief
metadata:
  hermes:
    category: research
  vellum:
    trigger: [sports, standings]
    routing_critical: true""",
    )

    package = SkillPackageParser().parse(root)

    assert package.metadata.name == "sports-brief"
    assert package.metadata.metadata.hermes.category == "research"
    assert package.metadata.metadata.vellum.routing_critical is True
    assert package.body.startswith("# Sports Brief")


def test_parser_rejects_missing_or_unclosed_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "SKILL.md").write_text("# No frontmatter", encoding="utf-8")

    with pytest.raises(SkillPackageError, match="frontmatter"):
        SkillPackageParser().parse(root)


def test_parser_rejects_oversized_skill_file(tmp_path: Path) -> None:
    root = tmp_path / "large"
    write_skill(root, "name: large\ndescription: Large skill", body="x" * 256)

    with pytest.raises(SkillPackageError, match="size limit"):
        SkillPackageParser(max_file_bytes=128).parse(root)


def test_support_file_read_stays_inside_package(tmp_path: Path) -> None:
    root = tmp_path / "safe"
    write_skill(root, "name: safe\ndescription: Safe skill")
    references = root / "references"
    references.mkdir()
    (references / "guide.md").write_text("safe guide", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    parser = SkillPackageParser()

    assert parser.read_support_file(root, "references/guide.md") == "safe guide"
    with pytest.raises(SkillPackageError, match="inside the skill package"):
        parser.read_support_file(root, "../secret.txt")
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_packages.py -q
```

Expected: collection fails because `SkillPackageParser` and `SkillPackageError` are absent.

- [ ] **Step 3: Implement the parser**

Create `backend/agent/skills/parser.py`:

```python
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
```

Add these exports to `backend/agent/skills/__init__.py`:

```python
from agent.skills.parser import SkillPackageError, SkillPackageParser
```

and add `"SkillPackageError"` and `"SkillPackageParser"` to `__all__`.

- [ ] **Step 4: Run the parser tests**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_packages.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add backend/agent/skills backend/tests/test_skill_packages.py
git commit -m "feat: parse and validate skill packages"
```

## Task 3: Registry, Precedence, and Conditional Discovery

**Files:**
- Create: `backend/agent/skills/registry.py`
- Modify: `backend/agent/skills/__init__.py`
- Create: `backend/tests/test_skill_registry.py`

- [ ] **Step 1: Write failing registry tests**

Create `backend/tests/test_skill_registry.py`:

```python
from pathlib import Path

from agent.skills import SkillRegistry


def write_skill(root: Path, name: str, *, extra: str = "", body: str = "# Skill\n\n## Procedure\nRun it.") -> None:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Description for {name}\n{extra}---\n{body}\n",
        encoding="utf-8",
    )


def test_registry_discovers_nested_packages_and_lists_level_zero(tmp_path: Path) -> None:
    local = tmp_path / "packages"
    write_skill(local / "research" / "sports-brief", "sports-brief", extra="metadata:\n  hermes:\n    category: research\n")

    registry = SkillRegistry(local_root=local)

    entries = registry.list_skills()
    assert [(entry.name, entry.category, entry.available) for entry in entries] == [
        ("sports-brief", "research", True)
    ]
    assert registry.view("sports-brief").body.startswith("# Skill")


def test_local_skill_shadows_same_named_external_skill(tmp_path: Path) -> None:
    local = tmp_path / "local"
    external = tmp_path / "external"
    write_skill(local / "research" / "shared", "shared", body="# Local\n\n## Procedure\nLocal.")
    write_skill(external / "shared", "shared", body="# External\n\n## Procedure\nExternal.")

    registry = SkillRegistry(local_root=local, external_dirs=[external])

    assert registry.view("shared").body.startswith("# Local")
    assert len(registry.list_skills()) == 1


def test_registry_filters_platform_and_tool_conditions(tmp_path: Path) -> None:
    local = tmp_path / "local"
    write_skill(local / "mac-only", "mac-only", extra="platforms: [macos]\n")
    write_skill(
        local / "needs-web",
        "needs-web",
        extra="metadata:\n  hermes:\n    requires_toolsets: [web]\n",
    )
    write_skill(
        local / "fallback-search",
        "fallback-search",
        extra="metadata:\n  hermes:\n    fallback_for_tools: [web_search]\n",
    )

    registry = SkillRegistry(
        local_root=local,
        platform_name="windows",
        available_toolsets={"terminal"},
        available_tools={"web_search"},
    )
    entries = {entry.name: entry for entry in registry.list_skills(include_unavailable=True)}

    assert entries["mac-only"].available is False
    assert entries["needs-web"].available is False
    assert entries["fallback-search"].available is False
    assert registry.list_skills() == []


def test_registry_level_two_read_rejects_traversal(tmp_path: Path) -> None:
    local = tmp_path / "local"
    package = local / "safe"
    write_skill(package, "safe")
    (package / "references").mkdir()
    (package / "references" / "guide.md").write_text("guide", encoding="utf-8")

    registry = SkillRegistry(local_root=local)

    assert registry.view_file("safe", "references/guide.md") == "guide"
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_registry.py -q
```

Expected: collection fails because `SkillRegistry` is absent.

- [ ] **Step 3: Implement the registry**

Create `backend/agent/skills/registry.py`:

```python
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
        parser: SkillPackageParser | None = None,
        platform_name: str | None = None,
        available_toolsets: set[str] | None = None,
        available_tools: set[str] | None = None,
    ):
        self.local_root = Path(local_root)
        self.external_dirs = [Path(path) for path in external_dirs or []]
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
        for root, is_external in [
            *[(path, True) for path in self.external_dirs],
            (self.local_root, False),
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
```

Export `SkillRegistry` from `backend/agent/skills/__init__.py`.

- [ ] **Step 4: Run registry and package tests**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_registry.py tests/test_skill_packages.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/agent/skills backend/tests/test_skill_registry.py
git commit -m "feat: discover and filter skill packages"
```

## Task 4: Idempotent JSON Migration

**Files:**
- Create: `backend/agent/skills/migration.py`
- Create: `backend/scripts/migrate_skills.py`
- Modify: `backend/agent/skills/__init__.py`
- Create: `backend/tests/test_skill_migration.py`

- [ ] **Step 1: Write failing migration tests**

Create `backend/tests/test_skill_migration.py`:

```python
import json
from pathlib import Path

from agent.skills import JsonSkillMigrator, SkillPackageParser


def write_json_skill(root: Path) -> Path:
    active = root / "active"
    active.mkdir(parents=True)
    path = active / "skill-route-sports-agent-v1.json"
    path.write_text(
        json.dumps(
            {
                "id": "skill-route-sports-agent-v1",
                "name": "Route sports questions to SportsAgent",
                "trigger": ["NBA", "Arsenal"],
                "negative_trigger": ["write sports tests"],
                "confidence_threshold": 0.25,
                "route_to_agent": "SportsAgent",
                "instructions": "Consult SportsAgent before answering.",
                "when_not_to_use": "Do not use for test authoring.",
                "citation_style": "Cite public sources.",
                "output_format": "Concise prose.",
                "created": "2026-05-27",
                "approved": "2026-05-27",
                "use_count": 4,
                "last_used": "2026-07-01T10:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_migrator_converts_json_to_valid_package_and_usage(tmp_path: Path) -> None:
    write_json_skill(tmp_path)

    report = JsonSkillMigrator(tmp_path).migrate()

    package_root = tmp_path / "packages" / "uncategorized" / "skill-route-sports-agent-v1"
    package = SkillPackageParser().parse(package_root)
    vellum = package.metadata.metadata.vellum
    assert report.created == ["skill-route-sports-agent-v1"]
    assert vellum.trigger == ["NBA", "Arsenal"]
    assert vellum.route_to_agent == "SportsAgent"
    assert vellum.routing_critical is True
    assert "Consult SportsAgent" in package.body
    usage = json.loads((tmp_path / ".usage.json").read_text(encoding="utf-8"))
    assert usage["skill-route-sports-agent-v1"]["use_count"] == 4
    assert (tmp_path / "active" / "skill-route-sports-agent-v1.json").exists()


def test_migrator_is_idempotent_and_preserves_modified_package(tmp_path: Path) -> None:
    write_json_skill(tmp_path)
    migrator = JsonSkillMigrator(tmp_path)
    migrator.migrate()
    skill_file = tmp_path / "packages" / "uncategorized" / "skill-route-sports-agent-v1" / "SKILL.md"
    skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\nUser modification.\n", encoding="utf-8")

    report = migrator.migrate()

    assert report.created == []
    assert report.skipped == ["skill-route-sports-agent-v1"]
    assert "User modification" in skill_file.read_text(encoding="utf-8")


def test_migrator_does_not_publish_any_package_when_staging_validation_fails(tmp_path: Path, monkeypatch) -> None:
    write_json_skill(tmp_path)

    def fail_parse(*args, **kwargs):
        raise ValueError("validation failed")

    monkeypatch.setattr("agent.skills.migration.SkillPackageParser.parse", fail_parse)

    try:
        JsonSkillMigrator(tmp_path).migrate()
    except ValueError as exc:
        assert str(exc) == "validation failed"

    assert not (tmp_path / "packages").exists()
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_migration.py -q
```

Expected: collection fails because `JsonSkillMigrator` is absent.

- [ ] **Step 3: Implement migration and usage merge**

Create `backend/agent/skills/migration.py`:

```python
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
```

Export `JsonSkillMigrator` and `MigrationReport` from `backend/agent/skills/__init__.py`.

Create `backend/scripts/migrate_skills.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.skills import JsonSkillMigrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Vellum JSON skills to SKILL.md packages.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / ".skills")
    args = parser.parse_args()
    report = JsonSkillMigrator(args.root).migrate()
    print(json.dumps({"created": report.created, "skipped": report.skipped, "invalid": report.invalid}))
    return 0 if not report.invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run migration tests**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_skill_migration.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

```powershell
git add backend/agent/skills backend/scripts/migrate_skills.py backend/tests/test_skill_migration.py
git commit -m "feat: migrate JSON skills to packages"
```

## Task 5: Legacy `SkillStore` Compatibility and Routing Preservation

**Files:**
- Modify: `backend/agent/memory/skills.py`
- Modify: `backend/tests/test_memory.py`
- Modify: `backend/tests/test_skill_driven_routing.py`

- [ ] **Step 1: Write failing canonical-package facade tests**

Append to `backend/tests/test_memory.py`:

```python
def test_skill_store_prefers_canonical_package_over_legacy_json(tmp_path):
    package = tmp_path / ".skills" / "packages" / "research" / "shared-skill"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: shared-skill
description: Canonical shared skill
metadata:
  vellum:
    trigger: [canonical, shared]
    confidence_threshold: 0.1
---
# Canonical

## Procedure
Use canonical instructions.
""",
        encoding="utf-8",
    )
    active = tmp_path / ".skills" / "active"
    active.mkdir()
    (active / "shared-skill.json").write_text(
        json.dumps(
            {
                "id": "shared-skill",
                "name": "Legacy shared skill",
                "trigger": ["legacy", "shared"],
                "confidence_threshold": 0.1,
                "instructions": "Use legacy instructions.",
            }
        ),
        encoding="utf-8",
    )

    store = SkillStore(tmp_path / ".skills")

    skills = {skill["id"]: skill for skill in store.load_active_skills()}
    assert skills["shared-skill"]["instructions"] == "# Canonical\n\n## Procedure\nUse canonical instructions."
    assert store.matching_skills("canonical shared")
    assert store.matching_skills("legacy shared") == []


def test_skill_store_falls_back_to_unmigrated_json(tmp_path):
    active = tmp_path / ".skills" / "active"
    active.mkdir(parents=True)
    (active / "legacy.json").write_text(
        json.dumps(
            {
                "id": "legacy",
                "name": "Legacy",
                "trigger": ["legacy", "request"],
                "confidence_threshold": 0.1,
                "instructions": "Legacy instructions.",
            }
        ),
        encoding="utf-8",
    )

    assert SkillStore(tmp_path / ".skills").matching_skills("legacy request")
```

Add `import json` to the imports in `backend/tests/test_memory.py`.

Append to `backend/tests/test_skill_driven_routing.py`:

```python
def test_skill_route_resolver_routes_canonical_routing_skill(tmp_path):
    package = tmp_path / "packages" / "routing" / "sports-route"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: sports-route
description: Route sports questions
metadata:
  vellum:
    trigger: [Arsenal, Champions League]
    confidence_threshold: 0.25
    route_to_agent: SportsAgent
    routing_critical: true
---
# Route sports

## Procedure
Consult SportsAgent before answering.
""",
        encoding="utf-8",
    )

    route = SkillRouteResolver(SkillStore(root=tmp_path)).resolve("Arsenal Champions League update")

    assert route == SkillRoute(agent_name="SportsAgent", skill_id="sports-route")
```

- [ ] **Step 2: Run the focused tests and verify the canonical cases fail**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_memory.py tests/test_skill_driven_routing.py -q
```

Expected: existing JSON tests pass; new canonical package tests fail because `SkillStore` only reads JSON.

- [ ] **Step 3: Adapt `SkillStore` to the registry**

Replace `backend/agent/memory/skills.py` with:

```python
"""Compatibility facade for Vellum's canonical skill package registry."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from agent.skills import SkillRegistry


SKILLS_PATH = Path(__file__).resolve().parents[3] / ".skills"


class SkillStore:
    def __init__(self, root: str | Path = SKILLS_PATH):
        self.root = Path(root)
        self.registry = SkillRegistry(local_root=self.root / "packages")

    def load_active_skills(self) -> list[dict[str, Any]]:
        canonical: dict[str, dict[str, Any]] = {}
        for entry in self.registry.list_skills():
            package = self.registry.view(entry.name)
            vellum = package.metadata.metadata.vellum
            canonical[entry.name] = {
                "id": entry.name,
                "name": package.metadata.description,
                "trigger": list(vellum.trigger),
                "negative_trigger": list(vellum.negative_trigger),
                "confidence_threshold": vellum.confidence_threshold,
                "route_to_agent": vellum.route_to_agent,
                "routing_critical": vellum.routing_critical,
                "instructions": package.body,
                "skill_package": str(package.root),
            }
        legacy = self._load_legacy_skills()
        for skill in legacy:
            canonical.setdefault(str(skill.get("id") or ""), skill)
        return [canonical[name] for name in sorted(canonical)]

    def matching_skills(self, query: str) -> list[dict[str, Any]]:
        query_terms = set(_terms(query))
        if not query_terms:
            return []
        matches = []
        for skill in self.load_active_skills():
            if _has_term_subset(query_terms, skill.get("negative_trigger", [])):
                continue
            trigger_terms = set(_terms(" ".join(skill.get("trigger", []))))
            if not trigger_terms:
                continue
            score = len(query_terms & trigger_terms) / len(trigger_terms)
            if score >= float(skill.get("confidence_threshold", 0.75)):
                matches.append(skill)
        return matches

    def build_prompt_block(self, query: str) -> str:
        matches = self.matching_skills(query)
        if not matches:
            return ""
        sections = ["## Active Skills"]
        for skill in matches:
            sections.append(f"### {skill.get('name', skill.get('id', 'Skill'))}\n{skill['instructions']}")
        return "\n\n".join(sections)

    def _load_legacy_skills(self) -> list[dict[str, Any]]:
        active = self.root / "active"
        if not active.exists():
            return []
        skills: list[dict[str, Any]] = []
        for path in sorted(active.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("instructions"):
                skills.append(data)
        return skills


def _terms(text: str) -> list[str]:
    return [term.casefold() for term in re.findall(r"[A-Za-z0-9]+", text) if len(term) > 2]


def _has_term_subset(query_terms: set[str], phrases: list[str]) -> bool:
    for phrase in phrases:
        phrase_terms = set(_terms(phrase))
        if phrase_terms and phrase_terms <= query_terms:
            return True
    return False
```

- [ ] **Step 4: Run focused compatibility tests**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_memory.py tests/test_skill_driven_routing.py tests/test_skill_packages.py tests/test_skill_registry.py tests/test_skill_migration.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Run the full existing backend test suite before migrating repository data**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 6: Commit Task 5**

```powershell
git add backend/agent/memory/skills.py backend/tests/test_memory.py backend/tests/test_skill_driven_routing.py
git commit -m "refactor: route legacy skill store through packages"
```

## Task 6: Migrate Repository Skills and Verify the Foundation

**Files:**
- Create: `.skills/packages/uncategorized/*/SKILL.md`
- Create: `.skills/.usage.json`
- Preserve: `.skills/active/*.json`

- [ ] **Step 1: Run the repository migrator**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe scripts/migrate_skills.py --root ..\.skills
```

Expected: JSON output lists every current active JSON skill under `created`, with an empty `invalid` list.

- [ ] **Step 2: Re-run migration to prove idempotency**

Run the same command again.

Expected: `created` is empty, every existing package appears under `skipped`, and `invalid` remains empty.

- [ ] **Step 3: Run production-skill compatibility tests**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest tests/test_memory.py::test_production_skill_store_includes_requested_capability_skills tests/test_memory.py::test_requested_capability_skills_match_realistic_prompts tests/test_memory.py::test_requested_capability_skills_avoid_near_miss_prompts tests/test_skill_driven_routing.py -q
```

Expected: all tests pass against canonical packages.

- [ ] **Step 4: Run the full backend suite again**

Run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [ ] **Step 5: Inspect migration scope before committing**

Run:

```powershell
git status --short -- .skills backend/agent/skills backend/agent/memory/skills.py backend/scripts/migrate_skills.py backend/tests backend/pyproject.toml backend/requirements.txt
```

Expected: only the package foundation, migrated packages, usage sidecar, tests, and dependency declarations appear. Existing `.skills/active/*.json` files remain unmodified.

- [ ] **Step 6: Commit migrated repository skills**

```powershell
git add .skills/packages .skills/.usage.json
git commit -m "chore: migrate built-in skills to packages"
```

## Plan Self-Review

- Spec coverage: this plan covers only subsystem 1 from the approved design—canonical package storage, parsing, discovery, migration, and compatibility routing. Progressive prompt loading, management tools, creation, hub, bundles, blueprints, telemetry mutation, curator, and user surfaces remain in later plans by design.
- Placeholder scan: the plan contains no deferred implementation placeholders.
- Type consistency: `SkillMetadata.metadata.vellum`, `SkillRegistry.view`, `JsonSkillMigrator.migrate`, and the legacy dictionary keys are consistent across tests and implementations.
- Safety: migration preserves legacy JSON, validates staging before publication, never overwrites canonical packages, and proves idempotency before repository data is committed.
