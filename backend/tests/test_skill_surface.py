from pathlib import Path

from agent.skills import SkillManager, SkillSurfaceService


def skill_md(name: str, description: str = "Skill description") -> str:
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  vellum:\n    trigger: [alpha, beta]\n---\n# {name}\n\n## Procedure\nRun it.\n"


def test_surface_catalog_reads_real_lifecycle_states_without_paths(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("active-skill"), confirm=True)
    proposed = root / "proposed" / "research" / "proposed-skill"
    proposed.mkdir(parents=True)
    (proposed / "SKILL.md").write_text(skill_md("proposed-skill"), encoding="utf-8")
    retired = root / "retired" / "research" / "retired-skill"
    retired.mkdir(parents=True)
    (retired / "SKILL.md").write_text(skill_md("retired-skill"), encoding="utf-8")
    service = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[])

    payload = service.catalog()

    assert [item["id"] for item in payload["skills"]["active"]] == ["active-skill"]
    assert [item["id"] for item in payload["skills"]["proposed"]] == ["proposed-skill"]
    assert [item["id"] for item in payload["skills"]["retired"]] == ["retired-skill"]
    assert payload["skills"]["active"][0]["trigger"] == "alpha · beta"
    assert str(tmp_path) not in str(payload)


def test_surface_actions_persist_approval_and_retirement(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    proposed = root / "proposed" / "research" / "proposed-skill"
    proposed.mkdir(parents=True)
    (proposed / "SKILL.md").write_text(skill_md("proposed-skill"), encoding="utf-8")
    service = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[])

    approve_pending = service.action("approve", name="proposed-skill", confirm=True)
    approved = service.action("pending_approve", name=approve_pending["id"])
    retire_pending = service.action("retire", name="proposed-skill", confirm=True)
    retired = service.action("pending_approve", name=retire_pending["id"])

    assert approved["state"] == "active"
    assert retired["state"] == "retired"
    assert [item["id"] for item in service.catalog()["skills"]["retired"]] == ["proposed-skill"]


def test_surface_expands_learn_direct_skill_and_lists_management_commands(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    SkillManager(root).create(skill_md("active-skill"), confirm=True)
    service = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[])

    learned = service.slash("/learn the deployment workflow from this conversation")
    direct = service.slash("/active-skill deploy staging")
    listed = service.slash("/skills")

    assert learned["handled"] is False
    assert 'skill_manage(action="create"' in learned["expanded"]
    assert direct == {
        "handled": False,
        "expanded": "Load active-skill with skill_view, then follow it for this request: deploy staging",
    }
    assert listed["handled"] is True
    assert "active-skill" in listed["answer"]


def test_surface_exposes_stable_skill_origins(tmp_path: Path) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(skill_md("user-skill"), origin="foreground", confirm=True)
    manager.create(skill_md("agent-skill"), origin="background_review", confirm=True)
    builtin = root / "packages" / "system" / "builtin-skill"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(
        "---\nname: builtin-skill\ndescription: Built in\nmetadata:\n  hermes:\n    tags: [migrated, vellum]\n---\n# Built in\n",
        encoding="utf-8",
    )
    surface = SkillSurfaceService(root, logs_root=tmp_path / "logs", sources=[])

    origins = {item["id"]: item["origin"] for item in surface.catalog()["skills"]["active"]}

    assert origins == {"agent-skill": "agent_learned", "builtin-skill": "builtin", "user-skill": "user_learned"}
