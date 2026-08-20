import asyncio
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


def test_vellum_prompt_reports_request_scoped_runtime_model(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent.graph.agent._prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
    )

    messages = vellum_prompt(
        {"messages": [HumanMessage(content="which model?")]},
        {"configurable": {"thread_id": "t1"}},
        runtime_model="openai/gpt-5.6-sol",
    )

    assert "Runtime selected model: openai/gpt-5.6-sol" in messages[0].content


def test_vellum_prompt_delegates_x_work_to_x_agent():
    assert "x_agent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Delegate all X interactions to XAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "x_action" not in agent_graph.VELLUM_SYSTEM_PROMPT


def test_vellum_prompt_delegates_book_reasoning_to_books_agent():
    assert "books_agent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Delegate Book reasoning to BooksAgent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Do not activate Book skills directly" in agent_graph.VELLUM_SYSTEM_PROMPT


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


def test_agent_tool_list_includes_x_agent(monkeypatch):
    captured = {}

    def fake_build_agent_runtime(**kwargs):
        captured["tools"] = kwargs["tools"]
        return object()

    monkeypatch.setattr(agent_graph, "_build_agent_runtime", fake_build_agent_runtime)
    monkeypatch.setattr(agent_graph, "build_llm", lambda model=None, reasoning_mode=None: object())
    monkeypatch.setattr(agent_graph, "build_checkpointer", lambda: object())
    spotify_tool = type("SpotifyTool", (), {"name": "spotify_playback"})()
    monkeypatch.setattr(agent_graph, "portable_agent_tools", lambda: [spotify_tool])

    agent_graph.build_agent()

    assert any(getattr(tool, "name", "") == "x_agent" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "x_action" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_research" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_extract" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "computer_use_route" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "memory_orchestrator" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "spotify_playback" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "fetch_sports_if_curious" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "should_fetch_sports" for tool in captured["tools"])


def test_async_agent_tool_list_includes_computer_use_route(monkeypatch):
    captured = {}

    def fake_build_agent_runtime(**kwargs):
        captured["tools"] = kwargs["tools"]
        return object()

    async def fake_checkpointer():
        return object()

    monkeypatch.setattr(agent_graph, "_build_agent_runtime", fake_build_agent_runtime)
    monkeypatch.setattr(agent_graph, "build_llm", lambda model=None, reasoning_mode=None: object())
    monkeypatch.setattr(agent_graph, "build_async_checkpointer", fake_checkpointer)
    spotify_tool = type("SpotifyTool", (), {"name": "spotify_playback"})()
    monkeypatch.setattr(agent_graph, "portable_agent_tools", lambda: [spotify_tool])

    import asyncio

    asyncio.run(agent_graph.build_async_agent())

    assert any(getattr(tool, "name", "") == "computer_use_route" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_research" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_extract" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "memory_orchestrator" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "spotify_playback" for tool in captured["tools"])


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


def test_agent_prompt_documents_memory_orchestrator_tool():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "memory_orchestrator" in prompt
    assert "Dreaming status" in prompt
    assert "Do not infer Dreaming" in prompt


def test_vellum_prompt_includes_compact_skill_index_without_skill_body(tmp_path: Path, monkeypatch):
    class FakeRegistry:
        def list_skills(self):
            from agent.skills import SkillIndexEntry

            return [
                SkillIndexEntry(
                    name="sports-brief",
                    description="Prepare sports briefs",
                    category="research",
                    state="active",
                    available=True,
                    package_root="C:/private/path",
                    is_external=False,
                )
            ]

    monkeypatch.setattr(agent_graph, "_prompt_skill_registry", FakeRegistry(), raising=False)
    monkeypatch.setattr(
        agent_graph,
        "_prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )

    messages = agent_graph.vellum_prompt({"messages": [HumanMessage(content="sports update")]}, {})

    assert "## Available Skills" in messages[0].content
    assert "sports-brief" in messages[0].content
    assert "C:/private/path" not in messages[0].content


def test_vellum_prompt_activates_matching_skill_for_current_task(tmp_path: Path, monkeypatch):
    class FakeRegistry:
        def list_skills(self):
            return []

    registry = FakeRegistry()
    seen = {}

    def activate(query, active_registry):
        seen["query"] = query
        seen["registry"] = active_registry
        return "## Activated Vellum Skills\n\n### code-review\nInspect the diff first."

    monkeypatch.setattr(agent_graph, "_prompt_skill_registry", registry, raising=False)
    monkeypatch.setattr(agent_graph, "build_skill_activation_block", activate, raising=False)
    monkeypatch.setattr(
        agent_graph,
        "_prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )

    messages = agent_graph.vellum_prompt(
        {"messages": [HumanMessage(content="Review this pull request")]},
        {},
    )

    assert seen == {"query": "Review this pull request", "registry": registry}
    assert "### code-review" in messages[0].content
    assert "Inspect the diff first." in messages[0].content


def test_agent_tool_list_includes_progressive_skill_tools(monkeypatch):
    captured = {}

    def fake_build_agent_runtime(**kwargs):
        captured["tools"] = kwargs["tools"]
        return object()

    monkeypatch.setattr(agent_graph, "_build_agent_runtime", fake_build_agent_runtime)
    monkeypatch.setattr(agent_graph, "build_llm", lambda model=None, reasoning_mode=None: object())
    monkeypatch.setattr(agent_graph, "build_checkpointer", lambda: object())
    monkeypatch.setattr(agent_graph, "portable_agent_tools", lambda: [])

    agent_graph.build_agent()

    names = {getattr(item, "name", "") for item in captured["tools"]}
    assert {
        "skills_list",
        "skill_view",
        "skill_manage",
        "skill_learn",
        "skill_bundles",
        "skill_hub",
        "skill_curator",
    } <= names


def test_agent_prompt_documents_skill_mutation_safety():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "skill_manage" in prompt
    assert "confirm=true" in prompt
    assert "background_review" in prompt
    assert "foreground" in prompt
    assert "blueprint" in prompt
    assert "suggestion" in prompt
    assert "never schedules" in prompt
    assert "quarantine" in prompt
    assert "dangerous" in prompt
    assert "force" in prompt
    assert "never auto-deletes" in prompt
    assert "rollback" in prompt


def test_lazy_agent_caches_async_runtimes_by_model(monkeypatch):
    builds = []

    class FakeRuntime:
        def __init__(self, model):
            self.model = model

        async def ainvoke(self, *_args, **_kwargs):
            return self.model

    async def fake_build(model=None, reasoning_mode=None):
        await asyncio.sleep(0)
        builds.append((model, reasoning_mode.value if reasoning_mode is not None else None))
        return FakeRuntime((model, reasoning_mode))

    monkeypatch.setattr(agent_graph, "build_async_agent", fake_build)
    lazy = agent_graph.LazyAgent()

    async def run_case():
        return await asyncio.gather(
            lazy.ainvoke({}, model="model-a"),
            lazy.ainvoke({}, model="model-b"),
            lazy.ainvoke({}, model="model-a"),
        )

    assert asyncio.run(run_case()) == [
        ("model-a", None),
        ("model-b", None),
        ("model-a", None),
    ]
    assert sorted(builds) == [("model-a", None), ("model-b", None)]


def test_lazy_agent_caches_separately_per_reasoning_mode(monkeypatch):
    builds = []

    class FakeRuntime:
        def __init__(self, model, reasoning_mode):
            self.key = (model, reasoning_mode)

        async def ainvoke(self, *_args, **_kwargs):
            return self.key

    async def fake_build(model=None, reasoning_mode=None):
        await asyncio.sleep(0)
        builds.append((model, reasoning_mode.value if reasoning_mode is not None else None))
        return FakeRuntime(model, reasoning_mode)

    monkeypatch.setattr(agent_graph, "build_async_agent", fake_build)
    lazy = agent_graph.LazyAgent()

    async def run_case():
        from agent.llm.reasoning import ReasoningMode

        return await asyncio.gather(
            lazy.ainvoke({}, model="model-a", reasoning_mode=ReasoningMode.high),
            lazy.ainvoke({}, model="model-a", reasoning_mode=ReasoningMode.ultra),
            lazy.ainvoke({}, model="model-a", reasoning_mode=ReasoningMode.high),
        )

    assert asyncio.run(run_case()) == [
        ("model-a", "high"),
        ("model-a", "ultra"),
        ("model-a", "high"),
    ]
    assert sorted(builds) == [
        ("model-a", "high"),
        ("model-a", "ultra"),
    ]
