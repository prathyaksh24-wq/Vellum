import json
from pathlib import Path

import pytest

from agent.skills import SkillBundleError, SkillBundleStore, SkillRegistry, SkillUsageStore
from agent.tools import skill_bundles as bundle_tools


def write_skill(root: Path, name: str, *, platforms: str = "") -> None:
    package = root / "packages" / name
    package.mkdir(parents=True)
    platform_line = f"platforms: [{platforms}]\n" if platforms else ""
    (package / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\n{platform_line}---\n# {name}\n\n## Procedure\nRun {name}.\n",
        encoding="utf-8",
    )


def test_bundle_store_creates_lists_shows_loads_and_deletes(tmp_path: Path) -> None:
    write_skill(tmp_path, "first")
    write_skill(tmp_path, "second")
    store = SkillBundleStore(tmp_path, SkillRegistry(local_root=tmp_path / "packages"))

    created = store.create(
        "Backend Dev",
        ["first", "second"],
        description="Backend workflow",
        instruction="Start with tests.",
        confirm=True,
    )
    shown = store.show("backend-dev")
    loaded = store.load("backend-dev")

    assert created["name"] == "backend-dev"
    assert store.list() == [shown]
    assert shown["skills"] == ["first", "second"]
    assert loaded["skills"] == ["first", "second"]
    assert loaded["content"].index("# first") < loaded["content"].index("# second")
    assert loaded["content"].startswith("Start with tests.")
    assert str(tmp_path) not in json.dumps(loaded)
    assert SkillUsageStore(tmp_path).get("first")["use_count"] == 1
    assert SkillUsageStore(tmp_path).get("second")["use_count"] == 1

    store.delete("backend-dev", confirm=True)
    assert store.list() == []


def test_bundle_store_rejects_empty_unknown_and_unavailable_members(tmp_path: Path) -> None:
    write_skill(tmp_path, "mac-only", platforms="macos")
    registry = SkillRegistry(local_root=tmp_path / "packages", platform_name="windows")
    store = SkillBundleStore(tmp_path, registry)

    with pytest.raises(SkillBundleError, match="at least one"):
        store.create("empty", [], confirm=True)
    with pytest.raises(SkillBundleError, match="unknown skill"):
        store.create("unknown", ["missing"], confirm=True)

    store.create("platform", ["mac-only"], confirm=True)
    with pytest.raises(SkillBundleError, match="unavailable"):
        store.load("platform")


def test_bundle_tool_requires_confirmation_and_loads(tmp_path: Path, monkeypatch) -> None:
    write_skill(tmp_path, "first")
    store = SkillBundleStore(tmp_path, SkillRegistry(local_root=tmp_path / "packages"))
    monkeypatch.setattr(bundle_tools, "_STORE", store)

    blocked = json.loads(
        bundle_tools.skill_bundles.invoke({"action": "create", "name": "bundle", "skills": ["first"]})
    )
    created = json.loads(
        bundle_tools.skill_bundles.invoke(
            {"action": "create", "name": "bundle", "skills": ["first"], "confirm": True}
        )
    )
    loaded = json.loads(bundle_tools.skill_bundles.invoke({"action": "load", "name": "bundle"}))

    assert blocked["ok"] is False
    assert created["ok"] is True
    assert "Run first" in loaded["content"]
