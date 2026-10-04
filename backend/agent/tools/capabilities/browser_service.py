"""BrowserAgent is the only specialist allowed to invoke browser capabilities."""
from agent.mcp.playwright_tools import browser_session
from agent.tools import browser
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry

BROWSER_TOOL_NAMES = ["browser_navigate", "browser_snapshot", "browser_tabs", "browser_click", "browser_type",
    "browser_scroll", "browser_press", "browser_back", "browser_get_images", "browser_vision", "browser_console",
    "browser_press_key", "browser_select_option", "browser_hover", "browser_wait", "browser_close", "browser_forward", "browser_reload"]
CONFIRMED_BROWSER_TOOLS = {"browser_click", "browser_type", "browser_press", "browser_press_key", "browser_select_option"}


class BrowserCapabilityService:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for name in BROWSER_TOOL_NAMES:
            access = CapabilityAccess.READ if name in {"browser_snapshot", "browser_get_images", "browser_vision", "browser_console"} else CapabilityAccess.WRITE
            registry.register_langchain(getattr(browser, name), access=access,
                allowed_agents=frozenset({"BrowserAgent"}), namespace="browser",
                requires_confirmation=name in CONFIRMED_BROWSER_TOOLS)
        for name, operation in [("browser.session.open", "control"), ("browser.session.status", "status")]:
            registry.register(CapabilityRecord(name=name, namespace="browser", access=CapabilityAccess.READ,
                allowed_agents=frozenset({"BrowserAgent"}), stream_label="Browser session",
                adapter=lambda _payload, op=operation: browser_session(op, {"operation":"open"} if op == "control" else None).model_dump()))
        registry.register(CapabilityRecord(name="browser.confirmed_action", namespace="browser", access=CapabilityAccess.WRITE,
            allowed_agents=frozenset({"BrowserAgent"}), requires_confirmation=True, stream_label="Confirmed browser interaction",
            adapter=lambda payload: browser_session("confirmed", payload)))
        return registry
