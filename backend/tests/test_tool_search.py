"""Tests for progressive tool search (Hermes-style bridge tools)."""

from __future__ import annotations

import json
import asyncio
import pytest

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


def test_describe_preserves_complete_linear_contract_and_write_instructions():
    from agent.plugins.linear_mcp import agent_tools
    save_issue=next(tool for tool in agent_tools() if tool.name=='linear_save_issue')
    definitions=ts.to_openai_defs([save_issue])
    catalog=ts.build_catalog(definitions)
    described=json.loads(ts.build_tool_describe_bridge(catalog).invoke({'name':'linear_save_issue'}))
    assert described['parameters']==ts._def_parameters(definitions[0])
    assert 'confirmation' in described['description']
    assert 'body' in described['parameters']['properties']
    assert 'description' not in described['parameters']['properties']


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


@pytest.mark.parametrize("streaming",[False,True])
def test_search_exposes_the_real_tool_on_the_next_model_and_budget_turn(monkeypatch,streaming):
    from langchain_core.messages import ToolMessage
    from agent.llm import context as context_module
    turns=[]
    budgets=[]
    original_project=context_module.project_context
    def project(messages,definitions,*args,**kwargs):
        budgets.append({ts._def_name(item) for item in definitions})
        return original_project(messages,definitions,*args,**kwargs)
    monkeypatch.setattr(context_module,"project_context",project)
    class DiscoveringModel(_StubModel):
        def invoke(self,messages,config=None):
            turns.append({ts._def_name(item) for item in self.bound})
            if len(turns)==1:
                return AIMessage(content="",tool_calls=[{"name":"tool_search","args":{"query":"echo"},"id":"search-1"}])
            if len(turns)==2:
                assert "deferred_echo" in turns[-1], "Discovered tool must be declared to the provider"
                return AIMessage(content="",tool_calls=[{"name":"deferred_echo","args":{"query":"hi"},"id":"echo-1"}])
            return AIMessage(content="done")
    if streaming:
        from langchain_core.messages import AIMessageChunk
        async def stream(self,messages,config=None):
            response=self.invoke(messages,config)
            yield AIMessageChunk(content=response.content,tool_calls=response.tool_calls)
        DiscoveringModel.astream=stream
    tool=StructuredTool.from_function(lambda query:"echo:"+query,name="deferred_echo",description="Echo a query")
    monkeypatch.setattr(agent_mod,"load_tool_search_config",lambda:ts.ToolSearchConfig(enabled="on"))
    compiled=agent_mod._build_agent_runtime(llm=DiscoveringModel(),tools=[tool],deferred_names={tool.name},checkpointer=InMemorySaver())
    state={"messages":[HumanMessage(content="Echo hi")]}
    config={"configurable":{"thread_id":"discovered-tool-contract"}}
    result=asyncio.run(compiled.ainvoke(state,config)) if streaming else compiled.invoke(state,config)
    assert "deferred_echo" not in turns[0] and "deferred_echo" in turns[1]
    assert "deferred_echo" not in budgets[0] and "deferred_echo" in budgets[1]
    assert any(isinstance(message,ToolMessage) and message.content=="echo:hi" for message in result["messages"])


def test_promotion_is_bounded_uses_registry_definitions_and_does_not_leak_between_chats():
    from langchain_core.messages import ToolMessage
    base=[_def("tool_search")]
    definitions=[_def(name) for name in ["alpha","beta","gamma"]]
    catalog=ts.build_catalog(definitions)
    results=ToolMessage(name="tool_search",tool_call_id="one",content=json.dumps({"matches":[
        {"name":"beta","parameters":{"malicious":"ignored"}}, {"name":"unknown"},
        {"name":"alpha"},{"name":"beta"},{"name":"gamma"}]}))
    promoted=ts.activate_discovered_tool_defs(base,catalog,[results],max_active=2)
    assert [ts._def_name(item) for item in promoted]==["tool_search","beta","alpha"]
    assert promoted[1] is definitions[1] and promoted[2] is definitions[0]
    assert ts.activate_discovered_tool_defs(base,catalog,[])==base
    assert ts.activate_discovered_tool_defs(base,catalog,[results],max_active=0)==base


def test_user_and_provider_data_cannot_promote_tools():
    from langchain_core.messages import ToolMessage
    catalog=ts.build_catalog([_def("alpha")])
    payload=json.dumps({"matches":[{"name":"alpha"}]})
    assert ts.activate_discovered_tool_defs([],catalog,[HumanMessage(content=payload),
        ToolMessage(content=payload,name="web_search",tool_call_id="one")])==[]
    inspected=ToolMessage(content=json.dumps({"name":"alpha"}),name="tool_describe",tool_call_id="two")
    assert ts.activate_discovered_tool_defs([],catalog,[inspected])==[catalog[0].tool_def]


def test_source_limits_bound_large_google_schemas_without_trusting_provider_labels():
    from langchain_core.messages import ToolMessage
    definitions=[_def(name) for name in ['google_one','google_two','google_three','other']]
    catalog=ts.build_catalog(definitions,{'google_one':'google','google_two':'google','google_three':'google','other':'other'})
    result=ToolMessage(content=json.dumps({'matches':[{'name':name,'source':'ignored'} for name in ['google_one','google_two','google_three','other']]}),name='tool_search',tool_call_id='fixture')
    visible=ts.activate_discovered_tool_defs([],catalog,[result],source_limits={'google':2})
    assert [ts._def_name(item) for item in visible]==['google_one','google_two','other']


def test_exact_tool_name_ranks_before_lexically_similar_long_descriptions():
    catalog=ts.build_catalog([_def('google_contacts_people_search_contacts'),_def('google_contacts_people_create_contact')])
    assert ts.search_catalog(catalog,'google_contacts_people_create_contact')[0].name=='google_contacts_people_create_contact'


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
        isinstance(message, SystemMessage) and "Use local vault and memory evidence" in message.content
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
