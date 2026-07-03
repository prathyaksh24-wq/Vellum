from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_skill_ui_uses_persisted_api_actions_and_exposes_archived_state() -> None:
    api_source = (ROOT / "frontend" / "ui" / "api" / "plugins.js").read_text(encoding="utf-8")
    ui_source = (ROOT / "frontend" / "ui" / "vellum-default.html").read_text(encoding="utf-8")

    assert 'client.request("/api/skills/action"' in api_source
    assert "API.plugins.skillAction({action, name: id, confirm: true})" in ui_source
    assert "Archived: skills.archived || []" in ui_source
    assert "const approveSkill = id => mutateSkill('approve', id)" in ui_source
