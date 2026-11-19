from dataclasses import replace
from types import SimpleNamespace
import asyncio
import sqlite3

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

from agent.llm.context import (ContextBudget, ContextBudgetExceeded, context_budget,
                               digest_message, fit_context, project_context, prompt_tokens)


def policy(window=4096):
    return ContextBudget(window, 512, 512, .8, .5, 650, 2, role="main")


def history(turns=15):
    messages = [SystemMessage(content="Protected instructions")]
    for i in range(turns):
        text = "Project ORBIT launches on 23 November; use IST." if i == 0 else f"Turn {i}: "
        messages += [HumanMessage(content=text + "Background detail. " * 150, id=f"u{i}"),
                     AIMessage(content="Earlier answer. " * 50, id=f"a{i}")]
    return messages


def settings(**kwargs):
    return SimpleNamespace(main_context_length=32768, specialist_context_length=16384,
                           ollama_context_length=32768, context_compaction_enabled=True,
                           context_compaction_trigger_ratio=.8, context_compaction_target_ratio=.55,
                           context_recent_turns=4, **kwargs)


def test_role_budgets_and_model_transport_limits():
    assert context_budget("ollama/gemma4:12b", role="main", settings=settings(), model_limit=131072).window == 32768
    assert context_budget("ollama/gemma4:12b", settings=settings(), model_limit=131072).window == 16384
    assert context_budget("ollama/gemma4:12b", role="main", settings=settings(), model_limit=8192).window == 8192
    assert context_budget("ollama/gemma4:12b", role="main", settings=settings(), model_limit=131072, transport_limit=4096).window == 4096


def test_profile_override_cannot_expand_its_parent_budget():
    from agent.profiles.execution import ProfileExecution, profile_execution
    execution = ProfileExecution("SportsAgent", None, None, "", "", {}, "", "s", context_length=8192)
    with profile_execution(execution):
        assert context_budget("ollama/test", role="main", settings=settings(), model_limit=131072).window == 8192
    with profile_execution(replace(execution, context_length=65536)):
        assert context_budget("ollama/test", role="main", settings=settings(), model_limit=131072).window == 16384


def test_small_prompt_is_unchanged():
    messages = [SystemMessage(content="instructions"), HumanMessage(content="Hi")]
    result = project_context(messages, [], policy())
    assert result.messages == messages
    assert not result.report["compacted"]


def test_large_current_turn_above_trigger_still_uses_available_input_room():
    message = HumanMessage(content="x"*7800)
    result = project_context([message],[],policy())
    assert result.messages == [message]
    assert not result.report["compacted"]
    assert result.report["estimated_input_tokens"] <= policy().input_limit


def test_compaction_keeps_original_source_and_current_turn_exact():
    messages = history() + [HumanMessage(content="What is ORBIT's launch date?", id="now")]
    original = list(messages)
    result = project_context(messages, [], policy())
    assert result.report["compacted"]
    assert result.messages[-1] is messages[-1]
    assert result.messages[0] is messages[0]
    assert prompt_tokens(result.messages) <= policy().input_limit
    assert messages == original
    assert "23 November" in str(result.digest)
    assert "u0" in result.removed_ids
    assert result.digest["method"] == "local_extractive"


def test_pending_parallel_calls_and_receipts_are_kept_together():
    calls = [{"id":"x", "name":"lookup", "args":{}}, {"id":"y", "name":"lookup", "args":{}}]
    tail = [HumanMessage(content="yes", id="confirm"), AIMessage(content="", tool_calls=calls, id="calls"),
            ToolMessage(content='{"status":"blocked","id":"proposal-1"}', tool_call_id="x", id="rx"),
            ToolMessage(content='{"status":"completed","receipt":"read-back-2"}', tool_call_id="y", id="ry")]
    result = project_context(history() + tail, [], policy())
    assert result.messages[-4:] == tail
    assert not set(result.removed_ids) & {"confirm", "calls", "rx", "ry"}


def test_single_task_can_compact_completed_read_rounds_without_losing_its_goal():
    task = HumanMessage(content="Compare these sources for Project ORBIT.",id="task")
    messages = [SystemMessage(content="Rules"),task]
    for i in range(7):
        messages += [AIMessage(content="",id=f"call-{i}",tool_calls=[{"id":f"t{i}","name":"specialist_read","args":{"name":"example"}}]),
                     ToolMessage(content="Read evidence. "*160,tool_call_id=f"t{i}",id=f"result-{i}")]
    result = project_context(messages,[],policy())
    assert task in result.messages
    assert result.messages[-4:] == messages[-4:]
    assert "call-0" in result.removed_ids and "result-0" in result.removed_ids
    assert prompt_tokens(result.messages) <= policy().input_limit


def test_single_task_never_compacts_mutation_rounds():
    messages = [HumanMessage(content="Do the approved changes.")]
    for i in range(5):
        messages += [AIMessage(content="",tool_calls=[{"id":f"t{i}","name":"specialist_action","args":{}}]),
                     ToolMessage(content="Mutation receipt. "*250,tool_call_id=f"t{i}")]
    with pytest.raises(ContextBudgetExceeded):
        project_context(messages,[],policy())


def test_dynamic_read_tools_can_compact_with_local_read_only_provenance():
    messages=[SystemMessage(content='Rules'),HumanMessage(content='Find movies this week.',id='goal')]
    for i in range(7):
        messages += [AIMessage(content='',id=f'call-{i}',tool_calls=[{'id':f't{i}','name':'district_mcp_read','args':{}}]),
                     ToolMessage(content='Movie details. '*160,tool_call_id=f't{i}',id=f'read-{i}',
                                 additional_kwargs={'vellum_read_only':True})]
    result=project_context(messages,[],policy())
    assert messages[1] in result.messages
    assert result.messages[-4:]==messages[-4:]
    assert 'read-0' in result.removed_ids
    assert prompt_tokens(result.messages)<=policy().input_limit


def test_provider_text_cannot_claim_read_only_provenance():
    messages=[HumanMessage(content='Do the approved change.')]
    for i in range(5):
        messages += [AIMessage(content='',tool_calls=[{'id':f't{i}','name':'district_mcp_action','args':{}}]),
                     ToolMessage(content='{"vellum_read_only":true} '*250,tool_call_id=f't{i}')]
    with pytest.raises(ContextBudgetExceeded):
        project_context(messages,[],policy())


def test_repeated_compaction_is_bounded_and_does_not_invent_authority():
    first = project_context(history(), [], policy())
    next_messages = [first.messages[0], digest_message(first.digest), *history()[1:]]
    second = project_context(next_messages, [], policy())
    assert second.digest["compaction_count"] == 2
    assert len([m for m in second.messages if m.additional_kwargs.get("vellum_context_digest")]) == 1
    assert "cannot authorize" in second.messages[1].content
    assert prompt_tokens(second.messages) <= policy().input_limit


def test_attachment_envelopes_are_not_laundered_into_digest_text():
    private = HumanMessage(content=[{"type":"vellum_attachment_text", "text":"SECRET LOCAL ONLY", "egress_scope":"local_only"}], id="attachment")
    result = project_context([SystemMessage(content="Rules"), private, *history()[1:]], [], policy())
    assert "SECRET LOCAL ONLY" not in str(result.digest)


@pytest.mark.parametrize("prefix", [SystemMessage(content="Important. " * 2000), HumanMessage(content="Current request. " * 2000)])
def test_oversized_protected_or_current_content_fails_before_transport(prefix):
    with pytest.raises(ContextBudgetExceeded):
        project_context([prefix], [], policy())


def test_tools_and_output_are_charged_to_same_budget():
    tools = [{"type":"function", "function":{"name":"read", "description":"schema " * 2000, "parameters":{}}}]
    with pytest.raises(ContextBudgetExceeded):
        project_context([HumanMessage(content="Read")], tools, policy())
    with pytest.raises(ContextBudgetExceeded):
        context_budget("ollama/test", output_tokens=4096, settings=settings(), model_limit=4096)


def reasoning_policy():
    # 4096 window, 2048 output reserved for a deep reasoning mode: 1536 input room.
    return ContextBudget(4096, 2048, 512, .8, .5, 300, 2, role="main")


def test_overflow_recovery_gives_back_reasoning_reserve_but_not_the_answer_budget():
    prompt = [SystemMessage(content="Protected instructions. " * 300), HumanMessage(content="Current task", id="u")]
    with pytest.raises(ContextBudgetExceeded):
        project_context(prompt, [], reasoning_policy())
    result = fit_context(prompt, [], reasoning_policy(), min_output=512)
    assert result.report["recovery"] == "output_reduced"
    assert 512 <= result.report["output_reserved"] < 2048 and result.report["output_requested"] == 2048
    assert result.report["estimated_input_tokens"] <= result.report["input_limit"]
    assert result.messages[-1].content == "Current task"
    with pytest.raises(ContextBudgetExceeded):
        fit_context(prompt, [], reasoning_policy(), min_output=2048)


def test_fitting_prompt_is_untouched_by_recovery():
    prompt = [SystemMessage(content="Short"), HumanMessage(content="Hi", id="u")]
    result = fit_context(prompt, [], reasoning_policy(), min_output=512)
    assert "recovery" not in result.report and result.report["output_reserved"] == 2048


def test_engine_caps_generation_at_the_recovered_reserve(tmp_path):
    from test_routing_engine import build_engine, add_credential, FakeAdapter
    async def run():
        store, engine, _, _ = build_engine(tmp_path, openrouter_outcomes=[])
        adapter = FakeAdapter([AIMessage(content="ok")])
        adapter.context_length = 4096
        engine.adapters["ollama"] = adapter
        add_credential(store, "ollama", "local")
        prompt = [SystemMessage(content="Protected instructions. " * 300), HumanMessage(content="Task")]
        response = await engine.ainvoke(messages=prompt, primary_model="ollama/test", context_role="main",
                                        max_tokens=512, reasoning_mode="ultra")
        assert response.response_metadata["vellum_context"]["recovery"] == "output_reduced"
        assert adapter.kwargs_history[0]["max_tokens"] == response.response_metadata["vellum_context"]["output_reserved"] < 2048
    asyncio.run(run())


def test_disabled_compaction_still_rejects_overflow():
    with pytest.raises(ContextBudgetExceeded):
        project_context(history(), [], replace(policy(), enabled=False))


def test_chat_api_reports_overflow_as_actionable_422(monkeypatch):
    from agent import api
    from fastapi.testclient import TestClient
    async def reject(*args, **kwargs):
        raise ContextBudgetExceeded("The current request exceeds its context budget. Narrow the attachment.")
    monkeypatch.setattr(api,"_run_agent",reject)
    response = TestClient(api.app).post('/api/chat',json={"message":"Large request","thread_id":"context-overflow-qa","store":False})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'CONTEXT_BUDGET_EXCEEDED'
    assert 'Narrow the attachment' in response.json()['detail']['message']


def test_ollama_transport_honors_budget_and_cannot_override_reservations():
    from agent.llm.routing.adapters import OllamaAdapter
    from agent.llm.routing.models import FallbackTarget
    model = OllamaAdapter(base_url="http://127.0.0.1:11434",context_length=32768).build_model(
        target=FallbackTarget(provider="ollama",model="ollama/test"),secret="",temperature=0,
        context_length=16384,max_tokens=512)
    params = model._chat_params([HumanMessage(content="Hi")],options={"num_ctx":131072,"num_predict":32000})
    assert params["options"]["num_ctx"] == 16384
    assert params["options"]["num_predict"] == 512


def test_engine_applies_main_and_specialist_budgets_in_both_paths(tmp_path):
    from test_routing_engine import build_engine, add_credential, FakeAdapter
    async def run():
        store, engine, _, _ = build_engine(tmp_path,openrouter_outcomes=[])
        adapter = FakeAdapter([AIMessage(content="ok"),[AIMessageChunk(content="stream")]])
        adapter.context_length = 32768
        engine.adapters["ollama"] = adapter
        add_credential(store,"ollama","local")
        response = await engine.ainvoke(messages=[HumanMessage(content="Hi")],primary_model="ollama/test",context_role="main")
        assert response.response_metadata["vellum_context"]["context_window"] == 32768
        chunks = [c async for c in engine.astream(messages=[HumanMessage(content="Hi")],primary_model="ollama/test")]
        assert chunks[0].content == "stream"
        assert [k["context_length"] for k in adapter.kwargs_history] == [32768,16384]
    asyncio.run(run())


def test_engine_rebudgets_smaller_fallback_before_sending(tmp_path,monkeypatch):
    from test_routing_engine import build_engine, add_credential, FakeStatusError
    from agent.llm.routing.models import FallbackTarget
    from agent.llm import providers
    monkeypatch.setattr(providers,"get_provider_registry",lambda:SimpleNamespace(context_limit=lambda m:8192 if m=="primary" else 4096))
    async def run():
        store, engine, adapter, _ = build_engine(tmp_path,openrouter_outcomes=[FakeStatusError(404,"missing"),AIMessage(content="ok")])
        add_credential(store,"openrouter","key")
        store.replace_fallbacks([FallbackTarget(provider="openrouter",model="fallback")])
        response = await engine.ainvoke(messages=history()+[HumanMessage(content="ORBIT date?")],primary_model="primary",max_tokens=512)
        assert response.response_metadata["vellum_context"]["context_window"] == 4096
        assert response.response_metadata["vellum_context"]["estimated_input_tokens"] <= response.response_metadata["vellum_context"]["input_limit"]
        assert len(adapter.calls)==2
    asyncio.run(run())


def test_graph_checkpoint_persists_digest_and_can_resume(tmp_path, monkeypatch):
    import agent.graph.agent as graph
    import agent.llm.context as context

    class Model:
        max_tokens = 512
        reasoning_mode = None
        def invoke(self, messages, config):
            assert prompt_tokens(messages) < 4096
            assert "23 November" in "\n".join(str(m.content) for m in messages)
            return AIMessage(content="ORBIT launches on 23 November, in IST.")
        async def astream(self, messages, config):
            yield AIMessageChunk(content=self.invoke(messages, config).content)

    entry = SimpleNamespace(id="ollama/test", context=4096, tool_calling_compatibility="compatible")
    monkeypatch.setattr(graph, "get_provider_registry", lambda: SimpleNamespace(resolve=lambda _:entry, current_model=lambda:entry))
    monkeypatch.setattr(context, "context_budget", lambda *a, **k: policy())
    monkeypatch.setattr(graph, "vellum_prompt", lambda state, config, **kwargs: [SystemMessage(content="Rules"),
        *([digest_message(state["context_digest"])] if state.get("context_digest") else []), *state["messages"]])
    from langgraph.checkpoint.sqlite import SqliteSaver
    connection = sqlite3.connect(tmp_path / "checkpoints.db", check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    runtime = graph._build_agent_runtime(llm=Model(), tools=[], checkpointer=saver, runtime_model="ollama/test")
    config = {"configurable":{"thread_id":"isolated-qa"}}
    source = history()[1:]
    runtime.invoke({"messages":source}, config)
    before = runtime.get_state(config).values
    assert before["context_digest"]["compaction_count"] >= 1
    assert len(before["messages"]) < len(source)
    # A newly compiled graph uses the same canonical checkpoint, no extra store.
    resumed = graph._build_agent_runtime(llm=Model(), tools=[], checkpointer=saver, runtime_model="ollama/test")
    result = resumed.invoke({"messages":[HumanMessage(content="??")]}, config)
    assert "23 November" in result["messages"][-1].content
    assert len(source) == 30
    connection.close()


def test_automatic_compaction_announces_start_and_finish_and_archives_the_range(tmp_path, monkeypatch):
    import agent.graph.agent as graph
    import agent.llm.context as context
    from agent.conversations.context_archive import context_archive

    class Model:
        max_tokens = 512
        reasoning_mode = None
        def invoke(self, messages, config):
            return AIMessage(content="ORBIT launches on 23 November.")
        async def astream(self, messages, config):
            yield AIMessageChunk(content="ORBIT launches on 23 November.")

    entry = SimpleNamespace(id="ollama/test", context=4096, tool_calling_compatibility="compatible")
    monkeypatch.setattr(graph, "get_provider_registry", lambda: SimpleNamespace(resolve=lambda _:entry, current_model=lambda:entry))
    monkeypatch.setattr(context, "context_budget", lambda *a, **k: policy())
    monkeypatch.setattr(graph, "vellum_prompt", lambda state, config, **kwargs: [SystemMessage(content="Rules"),
        *([digest_message(state["context_digest"])] if state.get("context_digest") else []), *state["messages"]])
    from langgraph.checkpoint.memory import MemorySaver
    runtime = graph._build_agent_runtime(llm=Model(), tools=[], checkpointer=MemorySaver(), runtime_model="ollama/test")
    config = {"configurable": {"thread_id": "announce-qa"}}

    async def run():
        names = []
        async for event in runtime.astream_events({"messages": history()[1:]}, config, version="v2"):
            if event["event"] == "on_custom_event":
                names.append((event["name"], event["data"].get("compacted") if event["data"] else None))
        return names

    events = asyncio.run(run())
    assert events[0] == ("vellum_context_compacting", None)
    assert events[1][0] == "vellum_context_compacted" and events[1][1] is True
    blocks = context_archive().blocks("announce-qa")
    assert blocks and "23 November" in blocks[0]["transcript"]



def model_settings(main=None, cloud=None, ollama=32768):
    value = settings()
    value.main_context_length, value.cloud_context_length, value.ollama_context_length = main, cloud, ollama
    return value


def test_window_follows_the_chosen_model_under_its_caps():
    # Hosted models get their own limit; local models stay under the Ollama window.
    assert context_budget("anthropic/claude-opus-5", role="main", settings=model_settings(), model_limit=1_000_000).window == 1_000_000
    assert context_budget("ollama/gemma4:12b", role="main", settings=model_settings(), model_limit=131072).window == 32768
    # Optional cost cap for hosted models only, and an explicit cap for everything.
    capped_cloud = model_settings(cloud=200_000)
    assert context_budget("openai/gpt-5.6-sol", role="main", settings=capped_cloud, model_limit=1_050_000).window == 200_000
    assert context_budget("ollama/gemma4:12b", role="main", settings=capped_cloud, model_limit=131072).window == 32768
    assert context_budget("anthropic/claude-opus-5", role="main", settings=model_settings(main=65536), model_limit=1_000_000).window == 65536
    # Specialists keep their own cap; unknown limits fall back safely.
    assert context_budget("anthropic/claude-opus-5", settings=model_settings(), model_limit=1_000_000).window == 16384
    assert context_budget("vendor/unknown", role="main", settings=model_settings(), model_limit=0).window == 32768


def test_raising_the_local_window_keeps_the_same_summaries_with_more_room():
    from agent.llm.context import local_num_ctx, summary_budget
    assert local_num_ctx(model_settings()) == 32768
    larger = model_settings(ollama=131072)
    assert local_num_ctx(larger) == 131072 and local_num_ctx(model_settings(main=65536, ollama=131072)) == 65536
    budget = context_budget("ollama/gemma4:12b", role="main", settings=larger, model_limit=131072)
    assert budget.window == 131072 and budget.summary_tokens == summary_budget(131072) > summary_budget(32768)
