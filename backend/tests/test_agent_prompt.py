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
    assert "Legacy desktop compatibility actions remain available" in prompt


def test_agent_prompt_prefers_direct_browser_search_for_youtube_tasks():
    assert "youtube.com/results?search_query=" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Do not stop after opening Chrome" in agent_graph.VELLUM_SYSTEM_PROMPT


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
    assert not any(getattr(tool, "name", "") == "fetch_sports_if_curious" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "should_fetch_sports" for tool in captured["tools"])


def test_prompt_describes_main_agent_as_router_with_specialists():
    assert "Specialist agents advise; Vellum decides" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "SportsAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "XAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "YoutubeAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "on-demand public sports research" in agent_graph.VELLUM_SYSTEM_PROMPT
