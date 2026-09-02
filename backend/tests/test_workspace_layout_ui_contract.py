from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UI_PATH = ROOT / "design" / "Velllum" / "uploads" / "Vellum Default Re-designed.html"


def test_registered_surfaces_expose_stable_ui_references_and_accessible_settings() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert 'data-ui-reference="workspace"' in ui_source
    assert 'data-ui-reference="sidebar"' in ui_source
    assert 'data-ui-reference="settings"' in ui_source
    assert 'data-ui-reference="right-panel"' in ui_source
    assert 'data-ui-reference="composer"' in ui_source
    assert 'data-ui-reference="composer.send"' in ui_source
    assert 'role="dialog" aria-modal="true" aria-label="Settings"' in ui_source
    assert "aria-label={sendLabel}" in ui_source


def test_visible_workspace_controls_dispatch_through_app_actions() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert "AppActions.createWorkspaceLayoutRuntime" in ui_source
    assert "dispatchSurfacePresentation('workspace', {properties:{theme:nextTheme}})" in ui_source
    assert "dispatchSurfacePresentation('settings', {visible:true})" in ui_source
    assert "dispatchSurfacePresentation('right-panel', {visible:true})" in ui_source
    assert "onSurfaceChange('composer', {properties:{size}})" in ui_source
    assert "onSurfaceChange('composer.send', {properties:{label:sendLabelDraft}})" in ui_source
    assert "onLayoutReset" in ui_source


def test_interface_actions_remove_the_optimistic_chat_turn() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert "actionRequested: request =>" in ui_source
    assert "rollbackAppActionTurn" in ui_source
    assert "messages:c.messages.filter(m => m.id !== userMsg.id && m.id !== aMsg.id)" in ui_source
    assert "cs.filter(c => c.id !== chatId)" in ui_source
    assert "action_message: opts.submittedText || message" in ui_source
    assert "setAgentConvos(ac =>" in ui_source
