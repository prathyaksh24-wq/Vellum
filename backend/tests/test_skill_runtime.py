from pathlib import Path

from agent.skills import SkillRegistry, build_skill_index_block


def write_skill(root: Path, name: str, description: str, body: str) -> None:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  hermes:\n    category: research\n---\n{body}\n",
        encoding="utf-8",
    )


def test_skill_index_contains_only_level_zero_metadata(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    write_skill(
        root / "research" / "sports-brief",
        "sports-brief",
        "Prepare sports briefs",
        "# Secret body\n\nPrivate procedure text.",
    )

    block = build_skill_index_block(SkillRegistry(local_root=root))

    assert "## Available Skills" in block
    assert "sports-brief" in block
    assert "Prepare sports briefs" in block
    assert "research" in block
    assert "Private procedure text" not in block
    assert str(tmp_path) not in block


def test_skill_index_omits_unavailable_skills(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    package = root / "platform" / "mac-only"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: mac-only\ndescription: macOS workflow\nplatforms: [macos]\n---\n# macOS\n",
        encoding="utf-8",
    )

    block = build_skill_index_block(SkillRegistry(local_root=root, platform_name="windows"))

    assert block == ""
