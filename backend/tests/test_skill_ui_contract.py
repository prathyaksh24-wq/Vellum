from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_skill_ui_uses_persisted_api_actions_and_exposes_archived_state() -> None:
    api_source = (ROOT / "design" / "Velllum" / "uploads" / "api" / "plugins.js").read_text(encoding="utf-8")
    ui_source = (ROOT / "design" / "Velllum" / "uploads" / "Vellum Default Re-designed.html").read_text(encoding="utf-8")

    assert 'client.request("/api/skills/action"' in api_source
    assert "API.plugins.skillAction({action,name:payload.name})" in ui_source
    assert "['archived','Archived']" in ui_source
    assert "API.plugins.pendingApprove(payload.id)" in ui_source
    assert "detail.skill_md" in ui_source
    assert "repository_url" in ui_source


def test_reasoning_composer_exposes_codex_style_categorized_slash_menu() -> None:
    ui_source = (ROOT / "design" / "Velllum" / "uploads" / "Vellum Default Re-designed.html").read_text(encoding="utf-8")

    assert "buildReasoningSlashItems" in ui_source
    assert "Commands" in ui_source
    assert "Skills" in ui_source
    assert "Plugins" in ui_source
    assert "Apps" in ui_source
    assert "MCPs" in ui_source
    assert "Agents" in ui_source
    assert 'aria-label="Slash commands"' in ui_source
    assert 'role="listbox"' in ui_source
    assert "onOpenPlugins" in ui_source
    assert "plugin-manage" in ui_source
    assert "[['plugins','Plugins'],['apps','Apps'],['mcps','MCPs'],['skills','Skills']]" in ui_source
    assert "Select an item to inspect its apps, MCPs, skills, and status." in ui_source
    assert "onOpenSkills={() => nav('skills')}" in ui_source
