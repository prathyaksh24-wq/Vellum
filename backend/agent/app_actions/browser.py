"""Browser controls enter the canonical App Action dispatch and receipt path."""
from agent.app_actions.models import AppActionDefinition
from pydantic import ValidationError
from agent.contracts.browser import BrowserControl
from agent.mcp.playwright_tools import browser_session

BROWSER_CONTROL_ACTION = "browser.session.control"


def browser_action_definitions() -> list[AppActionDefinition]:
    return [AppActionDefinition(
        id=BROWSER_CONTROL_ACTION, version="1", owner="playwright-browser", title="Control browser",
        description="Open, close, navigate, pause, or manually control Vellum's separate Brave session.",
        scope="user", access_class="write", executor_location="server", confirmation_rule="none",
        supports_undo=False, idempotent=False, argument_schema=BrowserControl.model_json_schema(),
        result_schema={"type":"object", "required":["changed", "control"]},
        ui_reference="browser-panel", audit_label=BROWSER_CONTROL_ACTION,
    )]


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
