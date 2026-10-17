from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UI_PATH = ROOT / "design" / "Velllum" / "uploads" / "Vellum Default Re-designed.html"
API_START_PATH = ROOT / "scripts" / "start-api.ps1"


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
    assert "dispatchSurfacePresentation('workspace', {properties:{theme:nextTheme}}, {learn:true})" in ui_source
    assert "dispatchSurfacePresentation('settings', {visible:true})" in ui_source
    assert "dispatchSurfacePresentation('right-panel', {visible:true})" in ui_source
    appearance = ui_source.split("{tab === 'Appearance' && (", 1)[1].split("{tab === '", 1)[0]
    assert "Workspace layout controls" not in appearance
    assert "Adaptive UI" not in appearance
    assert "onSurfaceChange" not in appearance
    assert "Live &amp; animated" in appearance
    assert "Static scenes" in appearance


def test_interface_actions_retain_submitted_chat_turns_and_receipts() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    requested = re.findall(r"actionRequested: \(request, turn\) => \{(.*?)\n\s*\},", ui_source, re.S)
    assert len(requested) == 2  # Main and specialist chats.
    for handler in requested:
        assert "conversationActionRuntimeRef.current.rememberRequest(request);" in handler
        assert "onAppAction" not in handler
    assert "rollbackAppActionTurn" not in ui_source
    assert "messages:c.messages.filter(m => m.id !== userMsg.id && m.id !== aMsg.id)" not in ui_source
    assert ui_source.count("applyAppActionReceipt(receipt, {notify:true, turn});") == 2
    assert "action_message: opts.submittedText || message" in ui_source
    assert "setAgentConvos(ac =>" in ui_source


def test_chat_navigation_preserves_in_progress_turns_and_persists_user_message() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert "const mergeConversationUpdate = (localChat, serverChat) =>" in ui_source
    assert "hasActiveTurn" in ui_source
    assert "messages: localChat.messages" in ui_source
    assert "mergeConversationUpdate(chat, conversation)" in ui_source
    assert "saveConversation({...record, messages:[userMsg]})" in ui_source
    assert "messages: [...c.messages, userMsg]" in ui_source
    assert "clearTurnTimers(assistantId);" in ui_source


def test_composer_queues_a_message_while_a_turn_is_running() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert "const turnQueueRef = useRef({});" in ui_source
    assert "const enqueueTurn = (queueKey, task) =>" in ui_source
    assert "if (busy && !text.trim())" in ui_source
    assert "deliveryMode: busy ? 'steer' : 'send'" in ui_source
    assert "enqueueTurn('chat:' + chatId" in ui_source
    assert "Queued — this message will run after the current response." in ui_source
    assert "m.streaming && !m.queued" in ui_source


def test_visible_answer_hides_raw_reference_sections_and_heading_markers() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert "const cleanVisibleAnswer = value =>" in ui_source
    assert "references|sources|sources checked|evidence" in ui_source
    assert "const visibleText = cleanVisibleAnswer(msg.text);" in ui_source
    assert '<div className="areply"><window.VellumUI.AnswerMarkdown text={visibleText' in ui_source


def test_api_launcher_exposes_project_cli_dependencies_to_provider_discovery() -> None:
    script = API_START_PATH.read_text(encoding="utf-8")

    assert '$venvScripts = Join-Path $Root ".venv\\Scripts"' in script
    assert '$env:PATH = "$venvScripts;$env:PATH"' in script


def test_x_connect_flow_uses_agent_reach_as_primary_and_oauth_as_optional() -> None:
    ui_source = UI_PATH.read_text(encoding="utf-8")

    assert "/api/x/agent-reach/connect" in ui_source
    assert "Connect with Agent Reach" in ui_source
    assert "Connect official X API (optional)" in ui_source
    assert "Cookie-Editor JSON export" in ui_source
