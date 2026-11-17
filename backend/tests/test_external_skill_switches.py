from agent.skills.external_switches import ExternalSkillSwitches
from agent.skills.registry import SkillRegistry


def _external_skill(root, name="demo"):
    package = root / "external" / name
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(f"---\nname: {name}\ndescription: External skill\n---\n# Demo\n", encoding="utf-8")
    return package


def test_turning_off_an_external_skill_hides_it_without_touching_files(tmp_path):
    package = _external_skill(tmp_path)
    switches = ExternalSkillSwitches(tmp_path / "skills")
    registry = SkillRegistry(local_root=tmp_path / "skills" / "packages", external_dirs=[tmp_path / "external"],
                             disabled_external=switches.disabled)
    assert [p.metadata.name for p in registry.list_packages()] == ["demo"]

    assert switches.set_enabled("demo", False) is False
    assert registry.list_packages() == []  # the agent no longer loads it
    assert [p.metadata.name for p in registry.list_packages(include_unavailable=True)] == ["demo"]
    assert (package / "SKILL.md").exists()

    switches.set_enabled("demo", True)
    assert [p.metadata.name for p in registry.list_packages()] == ["demo"]
    assert ExternalSkillSwitches(tmp_path / "skills").disabled() == set()


def test_switches_ignore_a_corrupt_file(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "external-disabled.json").write_text("{not json", encoding="utf-8")
    assert ExternalSkillSwitches(root).disabled() == set()
