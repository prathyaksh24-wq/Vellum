from pathlib import Path

from langchain_core.messages import HumanMessage

from agent.graph.agent import vellum_prompt
from agent.graph import agent as agent_graph
from agent.memory import project_context as pc


def test_vellum_prompt_includes_identity(tmp_path: Path, monkeypatch):
    meta = tmp_path / "Meta"
    meta.mkdir()
    (meta / "profile.md").write_text("My name is Test")

    monkeypatch.setattr(
        "agent.graph.agent._prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1"}}
    messages = vellum_prompt(state, config)
    assert any("<PROTECTED>" in m.content for m in messages)


def test_vellum_prompt_no_meta_falls_back(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent.graph.agent._prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )
    state = {"messages": [HumanMessage(content="hi")]}
    config = {"configurable": {"thread_id": "t1"}}
    messages = vellum_prompt(state, config)
    assert all("<PROTECTED>" not in m.content for m in messages)


def test_vellum_prompt_includes_runtime_date_grounding(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent.graph.agent._prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )

    messages = vellum_prompt({"messages": [HumanMessage(content="which year are you in?")]}, {})

    assert "Runtime current date:" in messages[0].content
    assert "Do not answer from training cutoff dates" in messages[0].content


def test_vellum_prompt_documents_x_action_safety_rules():
    assert "x_action" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "X_TOOL_ALLOW_POSTS=true" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_prompt_documents_workspace_mode():
    assert "mode='workspace'" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "visible workspace" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_prompt_documents_native_desktop_routing():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "list_windows" in prompt
    assert "action='observe'" in prompt
    assert "target window IDs" in prompt
    assert "accessibility element indexes" in prompt
    assert "blue edge-glow/status-pill Esc overlay" in prompt
    assert "action='open_app'" in prompt
    assert "action='launch_app'" in prompt
    assert "Installed-app, visible-terminal, and OS tab/window switching desktop actions were removed" not in prompt


def test_agent_prompt_prefers_direct_browser_search_for_youtube_tasks():
    assert "youtube.com/results?search_query=" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Do not stop after opening Chrome" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_prompt_documents_computer_use_routing_policy():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "computer_use_route" in prompt
    assert "browser first, workspace second, desktop last" in prompt
    assert "CUA driver and cloud VM control are coming soon" in prompt


def test_agent_prompt_checks_permissions_before_asking_again():
    assert "action='permissions'" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Do not ask again for a permission that is already true" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_tool_list_includes_x_action(monkeypatch):
    captured = {}

    def fake_create_react_agent(**kwargs):
        captured["tools"] = kwargs["tools"]
        return object()

    monkeypatch.setattr(agent_graph, "create_react_agent", fake_create_react_agent)
    monkeypatch.setattr(agent_graph, "build_llm", lambda model=None: object())
    monkeypatch.setattr(agent_graph, "build_checkpointer", lambda: object())

    agent_graph.build_agent()

    assert any(getattr(tool, "name", "") == "x_action" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_research" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_extract" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "computer_use_route" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "fetch_sports_if_curious" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "should_fetch_sports" for tool in captured["tools"])


def test_async_agent_tool_list_includes_computer_use_route(monkeypatch):
    captured = {}

    def fake_create_react_agent(**kwargs):
        captured["tools"] = kwargs["tools"]
        return object()

    async def fake_checkpointer():
        return object()

    monkeypatch.setattr(agent_graph, "create_react_agent", fake_create_react_agent)
    monkeypatch.setattr(agent_graph, "build_llm", lambda model=None: object())
    monkeypatch.setattr(agent_graph, "build_async_checkpointer", fake_checkpointer)

    import asyncio

    asyncio.run(agent_graph.build_async_agent())

    assert any(getattr(tool, "name", "") == "computer_use_route" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_research" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_extract" for tool in captured["tools"])


def test_agent_prompt_documents_tavily_and_firecrawl_tools():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "web_research" in prompt
    assert "Tavily" in prompt
    assert "web_extract" in prompt
    assert "Firecrawl" in prompt


def test_prompt_describes_main_agent_as_router_with_specialists():
    assert "Specialist agents advise; Vellum decides" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "SportsAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "XAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "YoutubeAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "on-demand public sports research" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "transcript-backed summaries" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "durable memory lookup" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "contract-compatible stubs" not in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_prompt_forbids_live_access_refusal_when_tools_exist():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "Do not tell the user you lack live information access" in prompt
    assert "use web_search" in prompt
