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


def test_memory_query_excludes_injected_conversation_context():
    query = agent_graph._memory_query_from_user_message(
        "what do you know about me?\n\n[Recent Vellum conversation context]\n" + ("old chat " * 3000)
    )

    assert query == "what do you know about me?"


def test_prompt_keeps_learning_context_below_kernel_and_preserves_correction(monkeypatch):
    class FakeProjectContext:
        def build(self, thread_id):
            return "<PROTECTED>Older profile: prefer long answers.</PROTECTED>"

    monkeypatch.setattr(agent_graph, "_prompt_project_ctx", FakeProjectContext())
    monkeypatch.setattr(agent_graph, "_get_skill_registry", lambda: object())
    monkeypatch.setattr(agent_graph, "build_skill_activation_block", lambda *args, **kwargs: "")
    monkeypatch.setattr(agent_graph, "_specialist_directory_block", lambda: "")
    monkeypatch.setattr(
        "agent.memory.memory_context.build_memory_block",
        lambda *args, **kwargs: "Older inferred preference: likes every saved post.",
    )
    correction = HumanMessage(content="Keep answers short. Saving a post doesn't mean I agree.")

    messages = vellum_prompt(
        {"messages": [correction]}, {"configurable": {"thread_id": "test-learning"}}
    )

    system = messages[0].content
    assert system.startswith(agent_graph.VELLUM_SYSTEM_PROMPT)
    boundary = system.index("## Personal context boundary")
    assert boundary < system.index("Older profile:")
    assert boundary < system.index("Older inferred preference:")
    assert "Current explicit statements and corrections take precedence" in system
    assert "default ambiguous stance to unknown" in system
    assert "report the proposal as pending" in system
    assert messages[1] is correction


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


def test_vellum_prompt_uses_one_typed_specialist_surface():
    assert "delegate_to_agent" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "Use only profile IDs from the directory" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "never copy the whole conversation" in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "x_agent" not in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "books_agent" not in agent_graph.VELLUM_SYSTEM_PROMPT
    assert "discord_agent" not in agent_graph.VELLUM_SYSTEM_PROMPT


def test_prompt_routes_natural_and_vague_requests_without_agent_names():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "everyday, indirect, shorthand, or slightly vague language" in prompt
    assert "they need not name an agent" in prompt
    assert '"live NBA score"' in prompt
    assert '"what did Naval tweet about AI?"' in prompt
    assert "Apply the same routing to books, YouTube, Discord, calendars, and personal memory" in prompt
    assert "If evidence is inadequate, report the gap" in prompt
    assert "if relevant specialists and authorized searches return no evidence, say you could not verify the answer" in prompt
    assert "Never substitute the runtime date, stale knowledge, a greeting, or a guess" in prompt


def test_agent_prompt_documents_workspace_mode():
    assert "Observe before computer or browser actions and verify the result" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_prompt_documents_native_desktop_routing():
    prompt = agent_graph.VELLUM_SYSTEM_PROMPT

    assert "Observe before computer or browser actions" in prompt
    assert "computer_use_route" in {tool.name for tool in agent_graph.core_tools()}


def test_main_agent_delegates_browser_tasks_and_keeps_general_web_search():
    names = {tool.name for tool in agent_graph.core_tools()}
    assert "delegate_to_agent" in names
    assert not any(name.startswith(("browser_", "browser.")) for name in names)
    assert "web_search" in names
    assert "Delegate websites, tabs and downloads to BrowserAgent" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_prompt_documents_computer_use_routing_policy():
    assert "computer_use_route" in {tool.name for tool in agent_graph.core_tools()}


def test_agent_prompt_checks_permissions_before_asking_again():
    assert "permission and confirmation requirements" in agent_graph.VELLUM_SYSTEM_PROMPT


def test_agent_tool_list_has_one_delegation_tool_and_no_domain_wrappers(monkeypatch):
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

    assert any(getattr(tool, "name", "") == "delegate_to_agent" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") in {"books_agent", "calendar_agent", "discord_agent", "x_agent"} for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "x_action" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_research" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "web_extract" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "computer_use_route" for tool in captured["tools"])
    assert any(getattr(tool, "name", "") == "memory_orchestrator" for tool in captured["tools"])
    assert not any(getattr(tool, "name", "") == "spotify_playback" for tool in captured["tools"])
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
    assert not any(getattr(tool, "name", "") == "spotify_playback" for tool in captured["tools"])


def test_agent_prompt_documents_tavily_and_firecrawl_tools():
    names = {tool.name for tool in agent_graph.core_tools()}
    assert {"web_research", "web_extract"} <= names


def test_prompt_describes_main_agent_as_router_with_specialists():
    block = agent_graph._specialist_directory_block()
    assert "SportsAgent" in block
    assert "XAgent" in block
    assert "YoutubeAgent" in block
    assert "DiscordAgent" in block
    assert "BrowserAgent" in block
    manifest = agent_graph.get_agent_catalog().delegation_manifest()
    assert all(set(entry) == {"id", "description"} for entry in manifest)
    assert not any(name in block for name in ("browser_navigate", "browser_click", "browser.confirmed_action"))
    assert "allowed_skills" not in block
    assert "skill_ids" not in block


def test_agent_prompt_forbids_live_access_refusal_when_tools_exist():
    assert "web_search" in {tool.name for tool in agent_graph.core_tools()}


def test_agent_prompt_documents_memory_orchestrator_tool():
    assert "memory_orchestrator" in {tool.name for tool in agent_graph.core_tools()}


def test_vellum_prompt_keeps_skill_context_relevant_and_hides_specialist_catalog(tmp_path: Path, monkeypatch):
    class FakeRegistry:
        pass

    class FakeCatalog:
        def delegation_manifest(self):
            return [{"id": "BooksAgent", "description": "Installed Book evidence."}]

        def specialist_skill_ids(self):
            return frozenset({"book-to-skill"})

    seen = {}

    def activate(query, registry, *, excluded_skills):
        seen["query"] = query
        seen["registry"] = registry
        seen["excluded_skills"] = excluded_skills
        return "## Relevant skills\n\n### code-review\nInspect the current diff."

    monkeypatch.setattr(agent_graph, "_prompt_skill_registry", FakeRegistry(), raising=False)
    monkeypatch.setattr(agent_graph, "get_agent_catalog", lambda: FakeCatalog())
    monkeypatch.setattr(agent_graph, "build_skill_activation_block", activate)
    monkeypatch.setattr(
        agent_graph,
        "_prompt_project_ctx",
        pc.ProjectContext(vault_root=tmp_path, sessions_db=tmp_path / "s.db"),
        raising=False,
    )

    messages = agent_graph.vellum_prompt({"messages": [HumanMessage(content="Review this diff")]}, {})

    assert seen == {
        "query": "Review this diff",
        "registry": agent_graph._prompt_skill_registry,
        "excluded_skills": frozenset({"book-to-skill"}),
    }
    assert "## Specialist directory" in messages[0].content
    assert "BooksAgent" in messages[0].content
    assert "## Available Skills" not in messages[0].content
    assert "book-to-skill" not in messages[0].content
    assert "Inspect the current diff." in messages[0].content


def test_vellum_prompt_activates_matching_skill_for_current_task(tmp_path: Path, monkeypatch):
    class FakeRegistry:
        def list_skills(self):
            return []

    class FakeCatalog:
        def specialist_skill_ids(self):
            return frozenset()

    registry = FakeRegistry()
    seen = {}

    def activate(query, active_registry, *, excluded_skills):
        seen["query"] = query
        seen["registry"] = active_registry
        seen["excluded_skills"] = excluded_skills
        return "## Activated Vellum Skills\n\n### code-review\nInspect the diff first."

    monkeypatch.setattr(agent_graph, "_prompt_skill_registry", registry, raising=False)
    monkeypatch.setattr(agent_graph, "get_agent_catalog", lambda: FakeCatalog())
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

    assert seen == {
        "query": "Review this pull request",
        "registry": registry,
        "excluded_skills": frozenset(),
    }
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

    assert "tool_search" in prompt
    assert "permission and confirmation requirements" in prompt
    assert "skill_manage" not in prompt
    assert len(prompt) < 7500


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


def test_lazy_agent_prepare_builds_the_cached_runtime(monkeypatch):
    builds = []

    class FakeRuntime:
        async def ainvoke(self, *_args, **_kwargs):
            return "ready"

    async def fake_build(model=None, reasoning_mode=None):
        builds.append((model, reasoning_mode.value if reasoning_mode is not None else None))
        return FakeRuntime()

    monkeypatch.setattr(agent_graph, "build_async_agent", fake_build)
    lazy = agent_graph.LazyAgent()

    async def run_case():
        from agent.llm.reasoning import ReasoningMode

        prepared = await lazy.prepare("model-a", ReasoningMode.high)
        invoked = await lazy.ainvoke({}, model="model-a", reasoning_mode=ReasoningMode.high)
        return prepared, invoked

    prepared, invoked = asyncio.run(run_case())

    assert isinstance(prepared, FakeRuntime)
    assert invoked == "ready"
    assert builds == [("model-a", "high")]
