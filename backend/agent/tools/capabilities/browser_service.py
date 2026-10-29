"""BrowserAgent is the only specialist allowed to invoke browser capabilities."""
from agent.mcp.playwright_tools import browser_session
from agent.tools import browser
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry

BROWSER_TOOL_NAMES = ["browser_navigate", "browser_snapshot", "browser_tabs", "browser_click", "browser_type",
    "browser_scroll", "browser_press", "browser_back", "browser_get_images", "browser_vision", "browser_console",
    "browser_press_key", "browser_select_option", "browser_hover", "browser_wait", "browser_close", "browser_forward", "browser_reload"]
CONFIRMED_BROWSER_TOOLS = {"browser_click", "browser_type", "browser_press", "browser_press_key", "browser_select_option"}


def _select_search_engine(payload):
    from agent.contracts.browser import BrowserSearchEngineSelection
    selection = BrowserSearchEngineSelection.model_validate(payload)
    return browser_session("control", {"operation":"preferences", **selection.model_dump()}).model_dump()


class BrowserCapabilityService:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for name in BROWSER_TOOL_NAMES:
            access = CapabilityAccess.READ if name in {"browser_snapshot", "browser_get_images", "browser_vision", "browser_console"} else CapabilityAccess.WRITE
            registry.register_langchain(getattr(browser, name), access=access,
                allowed_agents=frozenset({"BrowserAgent"}), namespace="browser",
                requires_confirmation=name in CONFIRMED_BROWSER_TOOLS)
        for name, operation in [("browser.session.open", "agent_open"), ("browser.session.status", "status")]:
            registry.register(CapabilityRecord(name=name, namespace="browser", access=CapabilityAccess.READ,
                allowed_agents=frozenset({"BrowserAgent"}), stream_label="Browser session",
                adapter=lambda _payload, op=operation: browser_session(op).model_dump()))
        from agent.contracts.browser import BrowserSearchEngineSelection
        registry.register(CapabilityRecord(name="browser.session.search_engine", namespace="browser", access=CapabilityAccess.WRITE,
            allowed_agents=frozenset({"BrowserAgent"}), stream_label="Change search engine",
            input_schema=BrowserSearchEngineSelection.model_json_schema(), adapter=_select_search_engine))
        registry.register(CapabilityRecord(name="browser.confirmed_action", namespace="browser", access=CapabilityAccess.WRITE,
            allowed_agents=frozenset({"BrowserAgent"}), requires_confirmation=True, stream_label="Confirmed browser interaction",
            adapter=lambda payload: browser_session("confirmed", payload)))
        registry.register(CapabilityRecord(name="browser.routine_action", namespace="browser", access=CapabilityAccess.WRITE,
            allowed_agents=frozenset({"BrowserAgent"}), stream_label="Browser interaction",
            adapter=lambda payload: browser_session("routine", payload)))
        registry.register(CapabilityRecord(name="browser.session.permission", namespace="browser", access=CapabilityAccess.READ,
            allowed_agents=frozenset({"BrowserAgent"}), stream_label="Browser session permission", adapter=lambda payload: browser_session("permission", payload)))
        registry.register(CapabilityRecord(name="browser.confirmed_navigation", namespace="browser", access=CapabilityAccess.WRITE,
            allowed_agents=frozenset({"BrowserAgent"}), requires_confirmation=True, stream_label="Confirmed browser navigation",
            adapter=lambda payload: browser_session("confirmed_navigation", payload)))
        return registry
