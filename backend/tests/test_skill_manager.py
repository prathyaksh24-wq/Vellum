from pathlib import Path

import pytest

from agent.skills import SkillManager, SkillMutationError, SkillPackageParser, SkillUsageStore


SKILL_MD = """---
name: sample-skill
description: Sample skill
metadata:
  hermes:
    category: research
---
# Sample Skill

## Procedure
Use the original procedure.
"""


def test_create_requires_confirmation_and_records_origin(tmp_path: Path) -> None:
    manager = SkillManager(tmp_path)

    with pytest.raises(SkillMutationError, match="confirmation"):
        manager.create(SKILL_MD)

    created = manager.create(SKILL_MD, category="research", origin="foreground", confirm=True)

    assert created["name"] == "sample-skill"
    assert (tmp_path / "packages" / "research" / "sample-skill" / "SKILL.md").exists()
    assert SkillUsageStore(tmp_path).get("sample-skill")["created_by"] is None

    background_md = SKILL_MD.replace("sample-skill", "background-skill").replace("Sample skill", "Background skill")
    manager.create(background_md, origin="background_review", confirm=True)
    assert SkillUsageStore(tmp_path).get("background-skill")["created_by"] == "agent"


def test_create_refuses_collision_and_invalid_package_without_partial_publish(tmp_path: Path) -> None:
    manager = SkillManager(tmp_path)
    manager.create(SKILL_MD, confirm=True)

    with pytest.raises(SkillMutationError, match="already exists"):
        manager.create(SKILL_MD, confirm=True)
    with pytest.raises(SkillMutationError, match="invalid skill package"):
        manager.create("---\nname: broken\n---\n", confirm=True)

    assert not (tmp_path / "packages" / "uncategorized" / "broken").exists()


def test_patch_edit_and_support_file_operations_are_validated(tmp_path: Path) -> None:
    manager = SkillManager(tmp_path)
    manager.create(SKILL_MD, confirm=True)

    manager.patch("sample-skill", "original procedure", "patched procedure", confirm=True)
    assert "patched procedure" in manager.package("sample-skill").body

    manager.write_file("sample-skill", "references/guide.md", "Guide", confirm=True)
    assert manager.registry.view_file("sample-skill", "references/guide.md") == "Guide"

    manager.remove_file("sample-skill", "references/guide.md", confirm=True)
    assert not (manager.package("sample-skill").root / "references" / "guide.md").exists()

    edited = SKILL_MD.replace("original procedure", "edited procedure")
    manager.edit("sample-skill", edited, confirm=True)
    assert "edited procedure" in manager.package("sample-skill").body
    assert SkillUsageStore(tmp_path).get("sample-skill")["patch_count"] == 4

    with pytest.raises(SkillMutationError, match="inside the skill package"):
        manager.write_file("sample-skill", "../escape.md", "blocked", confirm=True)


def test_archive_restore_and_confirmed_delete_move_whole_package(tmp_path: Path) -> None:
    manager = SkillManager(tmp_path)
    manager.create(SKILL_MD, category="research", confirm=True)

    manager.archive("sample-skill", confirm=True)
    assert (tmp_path / ".archive" / "research" / "sample-skill" / "SKILL.md").exists()
    assert SkillUsageStore(tmp_path).get("sample-skill")["state"] == "archived"

    manager.restore("sample-skill", confirm=True)
    assert (tmp_path / "packages" / "research" / "sample-skill" / "SKILL.md").exists()

    with pytest.raises(SkillMutationError, match="confirmation"):
        manager.delete("sample-skill", confirm=False)
    manager.delete("sample-skill", confirm=True)
    assert not (tmp_path / "packages" / "research" / "sample-skill").exists()
    assert "sample-skill" not in SkillUsageStore(tmp_path).all()


def test_manager_refuses_to_delete_pinned_skill(tmp_path: Path) -> None:
    manager = SkillManager(tmp_path)
    manager.create(SKILL_MD, confirm=True)
    manager.usage.pin("sample-skill")

    with pytest.raises(SkillMutationError, match="unpin"):
        manager.delete("sample-skill", confirm=True)


def test_manager_approves_proposed_and_retires_active_package(tmp_path: Path) -> None:
    manager = SkillManager(tmp_path)
    proposed = tmp_path / "proposed" / "research" / "sample-skill"
    proposed.mkdir(parents=True)
    (proposed / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (proposed / "references").mkdir()
    (proposed / "references" / "guide.md").write_text("Guide", encoding="utf-8")

    approved = manager.approve("sample-skill", confirm=True)
    retired = manager.retire("sample-skill", confirm=True)

    assert approved["state"] == "active"
    assert retired["state"] == "retired"
    assert (tmp_path / "retired" / "research" / "sample-skill" / "references" / "guide.md").exists()
    assert SkillUsageStore(tmp_path).get("sample-skill")["state"] == "retired"
