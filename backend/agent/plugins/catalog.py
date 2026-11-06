"""Shared local status projection for the UI and agent's plugin inventory.

These are the existing provider status readers, not live connection probes.
Listing never fetches remote schemas, refreshes OAuth or starts MCP processes.
"""
from importlib import import_module


_READERS = {
    "gitmcp": ("agent.mcp.gitmcp_tools", "plugin_status"),
    "spotify": ("agent.plugins.spotify_runtime", "portable_spotify_status"),
    "discord": ("agent.plugins.discord_runtime", "portable_discord_status"),
    "google-calendar": ("agent.plugins.google_calendar_runtime", "portable_google_calendar_status"),
    "app-69b7bed23a9481919d2378ab225cddeb": ("agent.plugins.product_hunt", "product_hunt_plugin_status"),
    "linear": ("agent.plugins.linear", "linear_plugin_status"),
    "github": ("agent.plugins.github_connection", "github_plugin_status"),
    "slack": ("agent.plugins.slack", "slack_plugin_status"),
    "airtable": ("agent.plugins.airtable", "airtable_plugin_status"),
    "notion": ("agent.plugins.notion", "notion_plugin_status"),
    "apify": ("agent.plugins.apify_connection", "apify_plugin_status"),
    "serpapi": ("agent.plugins.serpapi_connection", "serpapi_plugin_status"),
    "asana": ("agent.plugins.asana_connection", "asana_plugin_status"),
    "hubspot": ("agent.plugins.hubspot_connection", "hubspot_plugin_status"),
    "clickup": ("agent.plugins.clickup_connection", "clickup_plugin_status"),
    "swiggy": ("agent.plugins.swiggy_connection", "swiggy_plugin_status"),
    "zomato": ("agent.plugins.zomato_connection", "zomato_plugin_status"),
    "district": ("agent.plugins.district_connection", "district_plugin_status"),
    "vercel": ("agent.plugins.vercel_connection", "vercel_plugin_status"),
    "supabase": ("agent.plugins.supabase_connection", "supabase_plugin_status"),
    "exa": ("agent.plugins.exa_connection", "exa_plugin_status"),
    "tavily": ("agent.plugins.tavily_connection", "tavily_plugin_status"),
    "firecrawl": ("agent.plugins.firecrawl_connection", "firecrawl_plugin_status"),
}


def runtime_statuses(*, plugin_ids: set[str] | None = None, memory_orchestrator=None) -> list[dict]:
    statuses = []
    for identity, (module, function) in _READERS.items():
        if plugin_ids is not None and identity not in plugin_ids:
            continue
        try:
            statuses.append(getattr(import_module(module), function)())
        except Exception:
            statuses.append({"id": identity, "configured": False, "status": "unavailable",
                             "notes": "Connection state could not be read. Check plugin settings."})
    from agent.plugins.keyed_mcp import keyed_mcp_status
    for identity in ("brave", "context7"):
        if plugin_ids is None or identity in plugin_ids:
            statuses.append(keyed_mcp_status(identity))
    if plugin_ids is None or plugin_ids & {"google-workspace", "gmail", "google-drive", "google-calendar", "google-contacts"}:
        from agent.plugins.google_workspace import google_plugin_statuses
        statuses.extend(google_plugin_statuses())
    if plugin_ids is None or "agent-reach" in plugin_ids:
        from agent.tools.capabilities.agent_reach_x_provider import AgentReachXProvider
        statuses.append(AgentReachXProvider().status(probe=False).model_dump())
    if memory_orchestrator is not None:
        from agent.plugins.memory_orchestrator import memory_orchestrator_plugin_status
        statuses.append(memory_orchestrator_plugin_status(memory_orchestrator).model_dump())
    return statuses
