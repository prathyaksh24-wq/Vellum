import json
from pathlib import Path

from agent.skills import SkillConfigStore, SkillRegistry, SkillUsageStore
from agent.tools import skills as skill_tools


def make_registry(tmp_path: Path) -> SkillRegistry:
    package = tmp_path / "packages" / "research" / "sports-brief"
    package.mkdir(parents=True)
    (package / "references").mkdir()
    (package / "references" / "format.md").write_text("Use three bullets.", encoding="utf-8")
    (package / "SKILL.md").write_text(
        """---
name: sports-brief
description: Prepare sports briefs
metadata:
  hermes:
    category: research
---
# Sports Brief

## Procedure
Use source-backed facts.
""",
        encoding="utf-8",
    )
    return SkillRegistry(local_root=tmp_path / "packages")


def test_skills_list_returns_compact_metadata_without_machine_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skills_list.invoke({}))

    assert payload["skills"] == [
        {"name": "sports-brief", "description": "Prepare sports briefs", "category": "research", "available": True}
    ]
    assert str(tmp_path) not in json.dumps(payload)


def test_skill_view_returns_full_body_without_absolute_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skill_view.invoke({"name": "sports-brief"}))

    assert payload["name"] == "sports-brief"
    assert "Use source-backed facts" in payload["content"]
    assert "package_root" not in payload
    assert str(tmp_path) not in json.dumps(payload)


def test_skill_view_reads_one_relative_support_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(
        skill_tools.skill_view.invoke({"name": "sports-brief", "path": "references/format.md"})
    )

    assert payload == {"name": "sports-brief", "path": "references/format.md", "content": "Use three bullets."}


def test_skill_view_reports_missing_skill_without_crashing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))

    payload = json.loads(skill_tools.skill_view.invoke({"name": "missing"}))

    assert payload == {"ok": False, "error": "Skill not found: missing"}


def test_skill_view_resolves_config_and_reports_setup_without_secret_values(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "packages" / "configured"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        """---
name: configured
description: Configured skill
metadata:
  hermes:
    config:
      - key: plugin.path
        description: Local data path
        default: C:/private/data
      - key: plugin.domain
        description: Domain
required_environment_variables:
  - name: PRIVATE_API_KEY
required_credential_files:
  - path: credentials/oauth.json
---
# Configured
""",
        encoding="utf-8",
    )
    config = SkillConfigStore(tmp_path / "config.yaml")
    config.set("plugin.domain", "research")
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: SkillRegistry(local_root=tmp_path / "packages"))
    monkeypatch.setattr(skill_tools, "_config_store", lambda: config)
    monkeypatch.delenv("PRIVATE_API_KEY", raising=False)

    payload = json.loads(skill_tools.skill_view.invoke({"name": "configured"}))

    assert payload["resolved_config"] == {
        "plugin.path": "[LOCAL_PATH_CONFIGURED]",
        "plugin.domain": "research",
    }
    assert payload["setup_needed"] == {
        "environment_variables": ["PRIVATE_API_KEY"],
        "credential_files": ["credentials/oauth.json"],
        "config_keys": [],
    }
    assert "C:/private/data" not in json.dumps(payload)


def test_skill_view_records_view_and_use_without_exposing_sidecar(tmp_path: Path, monkeypatch) -> None:
    usage = SkillUsageStore(tmp_path)
    monkeypatch.setattr(skill_tools, "get_skill_registry", lambda: make_registry(tmp_path))
    monkeypatch.setattr(skill_tools, "_usage_store", lambda: usage)

    skill_tools.skill_view.invoke({"name": "sports-brief"})

    assert usage.get("sports-brief")["view_count"] == 1
    assert usage.get("sports-brief")["use_count"] == 1
