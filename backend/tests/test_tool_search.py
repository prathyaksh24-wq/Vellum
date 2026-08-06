"""Tests for progressive tool search (Hermes-style bridge tools)."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from agent.tools import tool_search as ts
from agent.graph import agent as agent_mod


def _def(name: str, description: str = "", params: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": params
            or {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def test_assemble_defers_marked_tools_and_adds_bridge():
    defs = [_def("search_my_notes"), _def("plugin_mcp"), _def("spotify_play", "Play Spotify tracks")]
    result = ts.assemble_tool_defs(
        defs,
        deferred_names={"plugin_mcp", "spotify_play"},
        source_labels={"plugin_mcp": "mcp", "spotify_play": "plugin"},
        config=ts.ToolSearchConfig(enabled="on"),
    )
    visible_names = [ts._def_name(d) for d in result.tool_defs]
    assert "search_my_notes" in visible_names
    assert "plugin_mcp" not in visible_names
    assert "spotify_play" not in visible_names
    assert {ts.TOOL_SEARCH_NAME, ts.TOOL_DESCRIBE_NAME, ts.TOOL_CALL_NAME} <= set(visible_names)
    assert result.activated is True
    assert result.tier == 1
    assert result.deferred_count == 2
    assert set(result.deferred_names) == {"plugin_mcp", "spotify_play"}
    assert result.listing_form in {"full", "names"}


def test_assemble_passthrough_when_disabled():
    defs = [_def("search_my_notes"), _def("plugin_mcp")]
    result = ts.assemble_tool_defs(
        defs,
        deferred_names={"plugin_mcp"},
        config=ts.ToolSearchConfig(enabled="off"),
    )
    assert result.activated is False
    assert result.tier == 0
    assert [ts._def_name(d) for d in result.tool_defs] == ["search_my_notes", "plugin_mcp"]


def test_should_activate_modes():
    cfg = ts.ToolSearchConfig(enabled="auto")
    assert ts.should_activate(cfg, deferred_tokens=9000, threshold_tokens=6400) is True
    assert ts.should_activate(cfg, deferred_tokens=1000, threshold_tokens=6400) is False
    assert ts.should_activate(ts.ToolSearchConfig(enabled="off"), deferred_tokens=99999, threshold_tokens=1) is False
    assert ts.should_activate(ts.ToolSearchConfig(enabled="on"), deferred_tokens=10, threshold_tokens=1) is True


def test_config_from_raw_shapes():
    assert ts.ToolSearchConfig.from_raw(True).enabled == "on"
    assert ts.ToolSearchConfig.from_raw(False).enabled == "off"
    assert ts.ToolSearchConfig.from_raw("auto").enabled == "auto"
    config = ts.ToolSearchConfig.from_raw({"enabled": "on", "threshold_ratio": 0.1, "listing_max_tokens": 500})
    assert config.enabled == "on"
    assert config.threshold_ratio == 0.1
    assert config.listing_max_tokens == 500


def test_runtime_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "RUNTIME_CONFIG_PATH", tmp_path / "tool_search.config.json")
    assert ts.load_runtime_config() == {}
    ts.save_runtime_config({"enabled": "on", "listing_max_tokens": 2000})
    assert ts.load_runtime_config() == {"enabled": "on", "listing_max_tokens": 2000}


def test_bm25_ranks_name_match_over_description():
    defs = [
        _def("github_write", "Create and update GitHub repositories through the GitHub MCP connector."),
        _def("search_amazon", "Search product listings on Amazon for pricing and comparisons."),
    ]
    catalog = ts.build_catalog(defs)
    matches = ts.search_catalog(catalog, "github", limit=5)
    assert [entry.name for entry in matches] == ["github_write"]


def test_search_catalog_empty_returns_no_matches():
    catalog = ts.build_catalog([_def("github_write", "GitHub writes")])
    assert ts.search_catalog(catalog, "zzzzz", limit=5) == []


def test_bridge_tools_dispatch_to_real_tool():
    def echo_plugin(query: str) -> str:
        return f"echo:{query}"

    echo_tool = StructuredTool.from_function(echo_plugin, name="plugin_echo", description="Echo a query")
    catalog = ts.build_catalog(ts.to_openai_defs([echo_tool]), source_labels={"plugin_echo": "plugin"})
    search_bridge, describe_bridge, call_bridge = ts.build_bridge_tools([echo_tool], catalog)

    search_result = json.loads(search_bridge.invoke({"query": "echo"}))
    assert [match["name"] for match in search_result["matches"]] == ["plugin_echo"]
    assert search_result["matches"][0]["source"] == "plugin"

    describe_result = json.loads(describe_bridge.invoke({"name": "plugin_echo"}))
    assert describe_result["name"] == "plugin_echo"
    assert describe_result["required"] == ["query"]

    call_result = json.loads(call_bridge.invoke({"name": "plugin_echo", "arguments": {"query": "hi"}}))
    assert call_result["output"] == "echo:hi"


def test_bridge_search_reports_available_sources_on_miss():
    echo_tool = StructuredTool.from_function(lambda query: "ok", name="plugin_echo", description="Echo")
    catalog = ts.build_catalog(ts.to_openai_defs([echo_tool]), source_labels={"plugin_echo": "plugin"})
    search_bridge, _, _ = ts.build_bridge_tools([echo_tool], catalog)
    result = json.loads(search_bridge.invoke({"query": "zzzzz"}))
    assert result["matches"] == []
    assert "plugin" in result["available_sources"]


def test_unwrap_bridge_call():
    assert ts.unwrap_bridge_call("web_search", {"query": "x"}) == ("web_search", {"query": "x"})
    inner, args = ts.unwrap_bridge_call("tool_call", {"name": "spotify_play", "arguments": {"uri": "abc"}})
    assert inner == "spotify_play"
    assert args == {"uri": "abc"}


def test_estimate_tokens_from_schemas_is_positive():
    assert ts.estimate_tokens_from_schemas([_def("search_my_notes")]) > 0


class _StubModel:
    def __init__(self):
        self.seen = None
        self.bound = None

    def bind_tools(self, tools, **kwargs):
        self.bound = tools
        return self

    def invoke(self, messages, config=None):
        self.seen = messages
        return AIMessage(content="done")


def test_build_agent_runtime_compiles_graph_with_vellum_prompt():
    stub = _StubModel()
    tools = [StructuredTool.from_function(lambda: "ok", name="plugin_mcp", description="MCP dispatch")]
    compiled = agent_mod._build_agent_runtime(
        llm=stub,
        tools=tools,
        deferred_names={"plugin_mcp"},
        checkpointer=InMemorySaver(),
    )
    assert set(compiled.get_graph().nodes) >= {"agent", "tools"}
    result = compiled.invoke(
        {"messages": [HumanMessage(content="hi")]},
        {"configurable": {"thread_id": "tool-search-test"}},
    )
    assert result["messages"][-1].content == "done"
    assert any(
        isinstance(message, SystemMessage) and "Always search the vault first" in message.content
        for message in stub.seen
    )


def test_build_agent_runtime_activates_bridge_with_on_config(monkeypatch):
    stub = _StubModel()
    tools = [
        StructuredTool.from_function(lambda: "ok", name="search_my_notes", description="Vault search"),
        StructuredTool.from_function(lambda: "ok", name="plugin_mcp", description="MCP dispatch"),
    ]
    monkeypatch.setattr(agent_mod, "load_tool_search_config", lambda: ts.ToolSearchConfig(enabled="on"))
    compiled = agent_mod._build_agent_runtime(
        llm=stub,
        tools=tools,
        deferred_names={"plugin_mcp"},
        checkpointer=InMemorySaver(),
    )
    bound_names = [ts._def_name(d) for d in stub.bound]
    assert "plugin_mcp" not in bound_names
    assert "tool_call" in bound_names
    assert {"agent", "tools"} <= set(compiled.get_graph().nodes)
