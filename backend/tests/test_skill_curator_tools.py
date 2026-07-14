import json

from agent.skills import SkillCurator, SkillManager
from agent.tools import skill_curator as curator_tools


def test_curator_tool_exposes_status_backup_pause_and_resume(tmp_path, monkeypatch) -> None:
    root = tmp_path / ".skills"
    SkillManager(root).create(
        "---\nname: agent-skill\ndescription: Agent skill\n---\n# Agent\n",
        origin="background_review",
        confirm=True,
    )
    curator = SkillCurator(root, logs_root=tmp_path / "logs")
    monkeypatch.setattr(curator_tools, "_CURATOR", curator)

    status = json.loads(curator_tools.skill_curator.invoke({"action": "status"}))
    backup = json.loads(curator_tools.skill_curator.invoke({"action": "backup", "reason": "manual"}))
    paused = json.loads(curator_tools.skill_curator.invoke({"action": "pause"}))
    resumed = json.loads(curator_tools.skill_curator.invoke({"action": "resume"}))

    assert status["enabled"] is True
    assert backup["id"]
    assert paused == {"ok": True, "paused": True}
    assert resumed == {"ok": True, "paused": False}


def test_curator_tool_pins_and_lists_archived_skills(tmp_path, monkeypatch) -> None:
    root = tmp_path / ".skills"
    manager = SkillManager(root)
    manager.create(
        "---\nname: agent-skill\ndescription: Agent skill\n---\n# Agent\n",
        origin="background_review",
        confirm=True,
    )
    curator = SkillCurator(root, logs_root=tmp_path / "logs")
    monkeypatch.setattr(curator_tools, "_CURATOR", curator)

    pinned = json.loads(curator_tools.skill_curator.invoke({"action": "pin", "name": "agent-skill"}))
    curator_tools.skill_curator.invoke({"action": "unpin", "name": "agent-skill"})
    archived = json.loads(
        curator_tools.skill_curator.invoke({"action": "archive", "name": "agent-skill", "confirm": True})
    )
    applied = curator.mutations.approve(archived["id"])
    listed = json.loads(curator_tools.skill_curator.invoke({"action": "list_archived"}))

    assert pinned["ok"] is True
    assert archived["status"] == "pending"
    assert applied["state"] == "archived"
    assert listed["skills"] == ["agent-skill"]
