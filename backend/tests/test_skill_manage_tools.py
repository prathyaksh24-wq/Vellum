import json

from agent.skills import SkillManager
from agent.tools import skill_manage as skill_tools


SKILL_MD = """---
name: tool-created
description: Tool-created skill
---
# Tool Created

## Procedure
Run the workflow.
"""


def test_skill_manage_tool_requires_confirmation_and_creates_skill(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "_MANAGER", SkillManager(tmp_path))

    blocked = json.loads(skill_tools.skill_manage.invoke({"action": "create", "skill_md": SKILL_MD}))
    created = json.loads(
        skill_tools.skill_manage.invoke({"action": "create", "skill_md": SKILL_MD, "confirm": True})
    )

    assert blocked["ok"] is False
    assert "confirmation" in blocked["error"]
    assert created == {"ok": True, "action": "create", "name": "tool-created", "state": "active"}


def test_skill_manage_tool_rejects_background_origin_from_foreground(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "_MANAGER", SkillManager(tmp_path))

    payload = json.loads(
        skill_tools.skill_manage.invoke(
            {"action": "create", "skill_md": SKILL_MD, "origin": "background_review", "confirm": True}
        )
    )

    assert payload == {"ok": False, "error": "background_review origin is reserved for the background review path"}


def test_skill_manage_tool_patches_and_archives(tmp_path, monkeypatch) -> None:
    manager = SkillManager(tmp_path)
    manager.create(SKILL_MD, confirm=True)
    monkeypatch.setattr(skill_tools, "_MANAGER", manager)

    patched = json.loads(
        skill_tools.skill_manage.invoke(
            {
                "action": "patch",
                "name": "tool-created",
                "old_text": "Run the workflow.",
                "new_text": "Run the verified workflow.",
                "confirm": True,
            }
        )
    )
    archived = json.loads(
        skill_tools.skill_manage.invoke({"action": "archive", "name": "tool-created", "confirm": True})
    )

    assert patched["ok"] is True
    assert archived["state"] == "archived"


def test_skill_learn_returns_guidance_without_writing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(skill_tools, "_MANAGER", SkillManager(tmp_path))

    payload = json.loads(skill_tools.skill_learn.invoke({"source": "notes from this conversation"}))

    assert payload["ok"] is True
    assert 'skill_manage(action="create"' in payload["prompt"]
    assert not (tmp_path / "packages").exists()
