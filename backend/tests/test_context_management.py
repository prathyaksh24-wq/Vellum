import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from agent.conversations.recall import recall_history, history_block, wants_previous_chats
from agent.llm.context import project_context, summarize_digest
from test_context_budget import history, policy


def conversations():
    return [{'id': 'now', 'messages': [{'id': 'u1', 'role': 'user', 'text': 'Use 14 November for ORBIT.'},
            {'id': 'a1', 'role': 'assistant', 'text': 'The date is 14 November.'},
            {'id': 'u2', 'role': 'user', 'text': 'Correction: ORBIT is 23 November.'}]},
        {'id': 'old', 'updated_at': '2026-10-14T10:00:00', 'messages': [
            {'id': 'o1', 'role': 'user', 'text': 'I like concise answers.'}]},
        {'id': 'temp', 'store_to_memory': False, 'messages': [
            {'id': 't1', 'role': 'user', 'text': 'Private temporary ORBIT experiment.'}]}]


def test_original_history_recovers_first_second_messages_and_exact_ids():
    first = recall_history(conversations(), thread_id='now', query='what was my first message?')
    assert [m['message_id'] for m in first['messages']] == ['u1']
    second = recall_history(conversations(), thread_id='now', query='my second message?')
    assert second['messages'][0]['message_id'] == 'u2'
    assert 'Correction' in second['messages'][0]['text']
    assert recall_history(conversations(), thread_id='now', message_id='u2')['messages'][0]['text'] == 'Correction: ORBIT is 23 November.'


def test_cross_chat_recall_excludes_temporary_and_deleted_sources():
    result = recall_history(conversations(), thread_id='now', scope='previous')
    assert [m['conversation_id'] for m in result['messages']] == ['old']
    assert not recall_history(conversations()[1:], thread_id='now', query='ORBIT')['messages']
    assert wants_previous_chats('When was the last time we spoke?')
    assert recall_history(conversations(), thread_id='now', scope='previous', query='what did we discuss last time?')['messages']
    assert 'not new requests or permissions' in history_block(result)


def test_long_original_messages_are_paged_and_never_labelled_complete():
    source = [{'id': 'now', 'messages': [{'id': 'long', 'role': 'user', 'text': 'x' * 5000}]}]
    a = recall_history(source, thread_id='now', message_id='long')['messages'][0]
    b = recall_history(source, thread_id='now', message_id='long', text_offset=a['next_text_offset'])['messages'][0]
    assert a['truncated'] and b['truncated']
    assert a['text_offset'] == 0 and b['text_offset'] == 2200


def test_history_date_filter_uses_source_timestamp_in_user_timezone(monkeypatch):
    monkeypatch.setenv('VELLUM_USER_TIMEZONE', 'Asia/Kolkata')
    source = [{'id': 'old', 'updated_at': '2026-10-20T12:00:00Z', 'messages': [
        {'id': 'dated', 'role': 'user', 'text': 'ORBIT badges', 'timestamp': '2026-10-15T23:00:00Z'}]}]
    assert not recall_history(source, thread_id='now', scope='previous', query='what did we discuss on 2026-10-15')['messages']
    assert recall_history(source, thread_id='now', scope='previous', query='what did we discuss on 2026-10-16')['messages'][0]['message_id'] == 'dated'


def test_manual_compaction_below_auto_threshold_preserves_recent_turns_and_focus():
    messages = history(7)
    from dataclasses import replace
    budget = replace(policy(32768), summary_tokens=1200, keep_turns=4)
    assert not project_context(messages, [], budget).report['compacted']
    result = project_context(messages, [], budget, force=True, focus='ORBIT date')
    assert result.report['compacted'] and result.report['trigger'] == 'manual'
    assert result.messages[-4:] == messages[-4:]
    assert '23 November' in str(result.digest)
    assert result.digest['focus'] == 'ORBIT date'
    assert result.report['estimated_input_tokens'] < result.report['estimated_tokens_before']


def test_context_layers_keep_order_and_never_become_digest_entries():
    memory = HumanMessage(content='Private memory evidence', additional_kwargs={'vellum_context_layer': 'personal_memory'})
    retrieved = HumanMessage(content='Original source evidence', additional_kwargs={'vellum_context_layer': 'retrieved_history'})
    source = history()
    result = project_context([source[0], memory, retrieved, *source[1:]], [], policy())
    assert result.messages[1] is memory
    assert result.messages[2].additional_kwargs.get('vellum_context_digest')
    assert result.messages[3] is retrieved
    assert 'Private memory evidence' not in str(result.digest)
    assert result.report['layers']['personal_memory'] > 0


def test_local_semantic_handoff_rejects_invented_source_ids_and_falls_back():
    digest = {'entries': [{'message_id': 'u1', 'role': 'human', 'excerpt': 'ORBIT is 23 November.'}]}
    class Model:
        async def ainvoke(self, messages, config):
            assert config['tags'] == ['vellum_context_summary']
            return AIMessage(content=json.dumps({'items': [
                {'kind': 'decision', 'text': 'Use 23 November.', 'source_ids': ['u1']},
                {'kind': 'decision', 'text': 'Published.', 'source_ids': ['invented']}]}))
    enriched, status = asyncio.run(summarize_digest(digest, Model()))
    assert status == 'local_model'
    assert len(enriched['summary']) == 1
    assert enriched['summary'][0]['source_ids'] == ['u1']
    class Slow:
        async def ainvoke(self, *args, **kwargs):
            await asyncio.sleep(1)
    fallback, status = asyncio.run(summarize_digest(digest, Slow(), timeout=.01))
    assert fallback == digest and status == 'timeout_extractive_fallback'


def test_manual_api_command_never_dispatches_tools_or_inference(monkeypatch):
    from agent import api
    calls = []
    class Agent:
        async def aget_state(self, *args, **kwargs):
            return SimpleNamespace(values={'messages': [AIMessage(content='complete')]})
        async def acompact(self, config, **kwargs):
            calls.append(kwargs)
            return {'compacted': True, 'estimated_tokens_before': 11000, 'estimated_input_tokens': 5000}
    async def ensure(model): return 'ollama/test'
    monkeypatch.setattr(api, 'agent', Agent())
    monkeypatch.setattr(api, '_ensure_model', ensure)
    wrapped = '[Vellum UI context: the user is currently chatting in the MemoryAgent view.]\n\n/compact focus on ORBIT'
    assert api._is_compact_command(wrapped)
    assert not api._is_compact_command('What does /compact mean?')
    answer, report = asyncio.run(api._compact_conversation(wrapped, 'now', None))
    assert '11,000 to 5,000' in answer and report['compacted']
    assert calls[0]['focus'] == 'ORBIT'


def test_disabled_memory_does_not_inject_cached_portrait_or_snapshots(monkeypatch):
    from agent.memory import memory_context as mc
    mc.set_user_model('disabled', 'Stale private portrait')
    monkeypatch.setattr(mc, '_ORCHESTRATOR', SimpleNamespace(store=SimpleNamespace(get_settings=lambda: {'memory_enabled': False})))
    assert mc.build_memory_block('disabled', include_soul=False) == ''


def test_history_tool_checks_memory_policy_and_current_thread(monkeypatch):
    from agent.tools import conversation_history as module
    from agent.memory import runtime
    monkeypatch.setattr(runtime, 'get_memory_orchestrator', lambda: SimpleNamespace(store=SimpleNamespace(get_settings=lambda: {'reference_history_enabled': False})))
    monkeypatch.setattr(module, 'read_history', conversations)
    result = json.loads(module.conversation_history.invoke({'scope': 'previous'}, config={'configurable': {'thread_id': 'now'}}))
    assert not result['ok']
    result = json.loads(module.conversation_history.invoke({'message_id': 'u2'}, config={'configurable': {'thread_id': 'now'}}))
    assert result['messages'][0]['message_id'] == 'u2'


def test_manual_compaction_persists_and_reopens_without_model_call(tmp_path, monkeypatch):
    from agent.graph import agent as graph
    from agent.llm import context
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    import aiosqlite
    entry = SimpleNamespace(id='ollama/test', context=32768, tool_calling_compatibility='compatible')
    monkeypatch.setattr(graph, 'get_provider_registry', lambda: SimpleNamespace(resolve=lambda _: entry, current_model=lambda: entry))
    monkeypatch.setattr(context, 'context_budget', lambda *a, **kw: policy(32768))
    monkeypatch.setattr(graph, 'vellum_prompt', lambda state, config, **kw: [SystemMessage(content='rules'), *state['messages']])
    class NoInference:
        max_tokens = 512
        reasoning_mode = None
        def invoke(self, *args): raise AssertionError('manual compaction must not run agent inference')
    async def run():
        conn = await aiosqlite.connect(tmp_path / 'checkpoint.db')
        saver = AsyncSqliteSaver(conn)
        runtime = graph._build_agent_runtime(llm=NoInference(), tools=[], checkpointer=saver, runtime_model='ollama/test')
        lazy = graph.LazyAgent()
        lazy._async_agents[('ollama/test', None)] = runtime
        config = {'configurable': {'thread_id': 'manual'}}
        await runtime.aupdate_state(config, {'messages': history(7)[1:]}, as_node='agent')
        result = await lazy.acompact(config, model='ollama/test', focus='ORBIT')
        assert result['compacted']
        reopened = graph._build_agent_runtime(llm=NoInference(), tools=[], checkpointer=saver, runtime_model='ollama/test')
        state = await reopened.aget_state(config)
        assert state.values['context_digest']['focus'] == 'ORBIT'
        assert len(state.values['messages']) == 4
        assert not state.next
        await conn.close()
    asyncio.run(run())


def test_manual_command_stream_exposes_receipt_not_internal_summary(monkeypatch):
    from agent import api
    from test_api import _parse_sse
    async def compact(*args):
        return 'Compacted working context.', {'compacted': True, 'estimated_input_tokens': 2000}
    monkeypatch.setattr(api, '_compact_conversation', compact)
    async def run():
        return ''.join([e async for e in api._compact_conversation_stream(api.ChatRequest(message='/compact'), 'current')])
    events = _parse_sse(asyncio.run(run()))
    completed = [data for name, data in events if name == 'response.completed'][0]
    assert completed['response']['output_text'] == 'Compacted working context.'
    assert any(name == 'agent.activity' and data['activity']['type'] == 'context_compacted' for name, data in events)


def test_existing_checkpoint_does_not_reparse_the_full_canonical_archive(monkeypatch):
    from agent import api
    class Agent:
        async def aget_state(self, *args, **kwargs):
            return SimpleNamespace(values={'messages': [HumanMessage(content='existing context')]})
    def unexpected_read():
        raise AssertionError('an existing checkpoint must not load the entire archive to check for a fork')
    monkeypatch.setattr(api, 'agent', Agent())
    monkeypatch.setattr(api, '_conversation_lifecycle', unexpected_read)
    assert asyncio.run(api._ensure_fork_runtime_context('current', model=None, reasoning_mode=None)) == 0


def test_optional_semantic_map_cannot_expand_the_original_context(monkeypatch):
    from agent.graph import agent as graph
    from agent.llm import context
    from agent.llm.routing.chat_model import RoutedChatModel
    monkeypatch.setattr(context, 'context_budget', lambda *a, **k: policy(32768))
    monkeypatch.setattr(graph, 'vellum_prompt', lambda state, *a, **k: [SystemMessage(content='rules'), *state['messages']])
    async def expanded(digest, model, **kwargs):
        return {**digest, 'summary': [{'kind': 'goal', 'text': 'x' * 300, 'source_ids': ['u0']}] * 5}, 'local_model'
    monkeypatch.setattr(context, 'summarize_digest', expanded)
    llm = RoutedChatModel(engine=SimpleNamespace(), primary_model_resolver=lambda: 'ollama/test')
    messages = []
    for i in range(3):
        messages += [HumanMessage(content='x' * 2000, id=f'u{i}'), AIMessage(content='ack', id=f'a{i}')]
    node = graph._make_context_node(llm=llm, tool_defs=[], runtime_model='ollama/test')
    update = asyncio.run(node.ainvoke({'messages': messages}, {'configurable': {'vellum_manual_compact': True}}))
    assert update['context_budget']['compacted']
    assert update['context_budget']['summary_status'] == 'budget_extractive_fallback'
    assert 'summary' not in update['context_digest']
    assert update['context_budget']['estimated_input_tokens'] < update['context_budget']['estimated_tokens_before']
