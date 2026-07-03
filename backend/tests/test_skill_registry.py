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
    write_skill(
        local / "research" / "sports-brief",
        "sports-brief",
        extra="metadata:\n  hermes:\n    category: research\n",
    )

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
