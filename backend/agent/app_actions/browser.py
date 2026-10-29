"""Browser controls enter the canonical App Action dispatch and receipt path."""
from agent.app_actions.models import AppActionDefinition
from pydantic import ValidationError
from agent.contracts.browser import BrowserControl, BrowserSettingsCommand
from agent.mcp.playwright_tools import browser_session

BROWSER_CONTROL_ACTION = "browser.session.control"
BROWSER_SETTINGS_ACTION = "browser.settings.manage"
BROWSER_DATA_ACTION = "browser.settings.data"
BROWSER_SETTINGS_ACTIONS = {BROWSER_SETTINGS_ACTION, BROWSER_DATA_ACTION}
CONFIRMED_OPERATIONS = {"delete_profile", "clear_data", "save_download", "remove_download"}


def browser_action_definitions() -> list[AppActionDefinition]:
    return [AppActionDefinition(
        id=BROWSER_CONTROL_ACTION, version="1", owner="playwright-browser", title="Control browser",
        description="Open, close, navigate, pause, or manually control Vellum's separate Brave session.",
        scope="user", access_class="write", executor_location="server", confirmation_rule="none",
        supports_undo=False, idempotent=False, argument_schema=BrowserControl.model_json_schema(),
        result_schema={"type":"object", "required":["changed", "control"]},
        ui_reference="browser-panel", audit_label=BROWSER_CONTROL_ACTION,
    ), *[AppActionDefinition(
        id=identity, version="1", owner="playwright-browser", title=title,
        description="Manage Vellum-owned browser profiles, preferences, permissions and browsing data.",
        scope="user", access_class="write", executor_location="server", confirmation_rule=confirmation,
        supports_undo=False, idempotent=False, argument_schema=BrowserSettingsCommand.model_json_schema(),
        result_schema={"type":"object", "required":["changed"]}, ui_reference="browser-settings", audit_label=identity,
    ) for identity, title, confirmation in [
        (BROWSER_SETTINGS_ACTION, "Manage browser settings", "none"),
        (BROWSER_DATA_ACTION, "Change browser data", "operation_bound"),
    ]]]


def validate_browser_settings(action_id: str, arguments: dict, context) -> BrowserSettingsCommand:
    if context.source != "ui":
        raise ValueError("Browser settings can only be changed from Settings.")
    try:
        command = BrowserSettingsCommand.model_validate(arguments)
    except ValidationError:
        raise ValueError("Invalid browser settings arguments.") from None
    if (command.operation in CONFIRMED_OPERATIONS) != (action_id == BROWSER_DATA_ACTION):
        raise ValueError("This browser operation requires the matching settings action.")
    if command.operation in CONFIRMED_OPERATIONS and not command.profile_id:
        raise ValueError("Choose the browser profile before changing its data.")
    return command


def execute_browser_settings(action_id: str, arguments: dict, context) -> dict:
    command = validate_browser_settings(action_id, arguments, context)
    try:
        view = browser_session("manage", command.model_dump())
    except ValueError:
        raise
    except Exception:
        raise ValueError("Browser settings could not be changed. Refresh Settings and try again.") from None
    return {"changed":True, "running":view.running, "_target_kind":"browser_profile",
            "_target_id":command.profile_id or view.preferences.active_profile_id,
            "_message":"Browser " + command.operation.replace("_", " ") + " completed."}


def execute_browser_control(arguments: dict, context) -> dict:
    # Model/NLP-originated actions cannot impersonate manual takeover or keyboard input.
    if context.source != "ui":
        raise ValueError("Browser tasks must be delegated to BrowserAgent.")
    try:
        control = BrowserControl.model_validate(arguments)
    except ValidationError:
        raise ValueError("Invalid browser control arguments.") from None
    try:
        status = browser_session("control", control.model_dump())
    except ValueError:
        raise
    except Exception:
        raise ValueError("The browser operation failed. Refresh the panel or reopen the session.") from None
    # Receipts contain metadata only, never text input, screenshots, URLs or cookies.
    return {"changed":True, "control":status.control, "running":status.running,
        "_target_kind":"browser_session", "_target_id":status.session_id or "dedicated",
        "_message":"Browser " + control.operation.replace("_", " ") + " completed."}
