from pathlib import Path

from agent.skills import SkillConfigStore, SkillPackageParser


def test_config_store_sets_nested_values_and_resolves_defaults(tmp_path: Path) -> None:
    store = SkillConfigStore(tmp_path / "config.yaml")
    package_root = tmp_path / "skill"
    package_root.mkdir()
    (package_root / "SKILL.md").write_text(
        """---
name: configured
description: Configured skill
metadata:
  hermes:
    config:
      - key: plugin.path
        description: Plugin data path
        default: ~/default-data
      - key: plugin.domain
        description: Plugin domain
---
# Configured
""",
        encoding="utf-8",
    )
    package = SkillPackageParser().parse(package_root)

    initial = store.resolve(package)
    store.set("plugin.domain", "research")
    resolved = store.resolve(package)

    assert initial == {"values": {"plugin.path": "~/default-data"}, "missing": ["plugin.domain"]}
    assert resolved == {
        "values": {"plugin.path": "~/default-data", "plugin.domain": "research"},
        "missing": [],
    }
    assert store.get("plugin.domain") == "research"
