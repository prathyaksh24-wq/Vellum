from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from agent import api

def test_local_honcho_background_options_do_not_enable_unbounded_thinking():
    import yaml
    compose = yaml.safe_load((Path(__file__).resolve().parents[2] / 'docker-compose.yml').read_text(encoding='utf-8'))
    environment = compose['services']['honcho-deriver']['environment']
    for prefix in ('DERIVER_MODEL_CONFIG', 'SUMMARY_MODEL_CONFIG', 'DIALECTIC_LEVELS__minimal__MODEL_CONFIG'):
        options = json.loads(environment[prefix + '__OVERRIDES__PROVIDER_PARAMS'])
        assert options == {'extra_body': {'reasoning_effort': 'none'}}
        assert environment[prefix + '__OVERRIDES__BASE_URL'] == 'http://host.docker.internal:11434/v1'
    assert environment['DERIVER_MODEL_CONFIG__MAX_OUTPUT_TOKENS'] == '1024'

@pytest.mark.parametrize("message", [
    "What book skills are available for my imported Meditations, and can you use them now?",
    "Show the skills for the book Meditations",
])
def test_book_skills_do_not_preempt_into_global_inventory(monkeypatch, message):
    def forbidden():
        raise AssertionError("Book question reached global skill catalog")
    monkeypatch.setattr(api, "_skill_surface", forbidden)
    assert api._skill_system_answer(message) is None

@pytest.mark.parametrize("question", ["What was my first message in this chat?", "What was the first message I sent in this chat?"])
def test_current_first_message_never_uses_another_chat(monkeypatch, question):
    monkeypatch.setattr(api, "_read_ui_conversations", lambda: [
        {"id":"current", "messages":[{"role":"user", "text":"ORCHID-42 is a note organizer."}]},
        {"id":"other", "messages":[{"role":"user", "text":"Unrelated old topic"}]},
    ])
    assert api._conversation_recall_answer(question, "current") == "Your first message in this chat was: “ORCHID-42 is a note organizer.”"


def test_failed_import_error_is_passed_to_dialog():
    source=Path("design/Velllum/uploads/components/books-view.jsx").read_text(encoding="utf-8")
    assert "error={state.error}" in source


def test_defender_disabled_is_unavailable_not_ambiguous(tmp_path):
    from agent.knowledge.book_ingestion import WindowsDefenderScanner
    executable=tmp_path/"MpCmdRun.exe"; executable.write_bytes(b"")
    asset=tmp_path/"book.epub"; asset.write_bytes(b"book")
    result=WindowsDefenderScanner(executable=executable, runner=lambda *a,**k:SimpleNamespace(returncode=2,stdout="WARN: Product/Feature disabled",stderr="[Failed][0x80004005]")).scan(asset)
    assert result.outcome == "unavailable"
    assert result.reason_code == "MALWARE_SCANNER_DISABLED"

@pytest.mark.parametrize('message', ['What is my latest tweet?', 'Show my newest post', 'what is the latest tweet from my account'])
def test_own_latest_x_post_never_uses_public_search(tmp_path, message):
    from agent.agents.x_agent import XAgent
    calls=[]
    class Service:
        def account(self, payload):
            calls.append('account'); return {'account': {'username':'owner'}}
        def user_posts(self, payload):
            assert payload == {'handle':'owner','max_results':20}
            return {'items':[{'handle':'owner','text':'A &amp; B','url':'https://x.com/owner/status/1'}]}
        def search_posts(self, payload):
            raise AssertionError('private account query reached public search')
    response=XAgent(vault_root=tmp_path,x_service=Service()).answer(message)
    assert calls == ['account']
    assert 'A & B' in response.summary
    assert len(response.sources) == 1

@pytest.mark.parametrize('message', ['What did I watch recently on YouTube?', 'What did I recently watch?', 'Show my watch history'])
def test_private_youtube_history_is_not_public_search(tmp_path, message):
    from agent.agents.youtube import YoutubeAgent
    agent=YoutubeAgent(vault_root=tmp_path)
    assert agent.can_handle(message)
    assert agent._is_takeout_query(message.lower())

def test_youtube_data_access_is_account_intent(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    agent=YoutubeAgent(vault_root=tmp_path)
    assert agent._is_account_query('do you have access to my youtube data?')

def test_natural_calendar_availability_uses_requested_afternoon():
    from datetime import datetime
    from agent.agents.calendar import CalendarAgent
    agent=CalendarAgent(tool_registry=object(),now=lambda tz: datetime(2026,9,30,tzinfo=tz))
    assert agent.can_handle('Am I free tomorrow afternoon?')
    start,end=agent._window('Am I free tomorrow afternoon?',{'time_zone':'Asia/Kolkata'})
    assert (start.day,start.hour,end.day,end.hour) == (1,12,1,18)

def test_explicit_dst_conversion_needs_no_model_or_previous_chat():
    assert '5:45 AM IST on Monday, October 05, 2026' in api._time_conversion_answer('Convert October 4, 2026 20:15 America/New_York to IST', 'new')

def test_next_sports_game_is_singular_and_uses_local_date(monkeypatch):
    from agent.agents.sports import SportsAgent
    monkeypatch.setenv('VELLUM_USER_TIMEZONE','Asia/Kolkata')
    summary=SportsAgent._next_event_snapshot('The next Chiefs game is against the Raiders on Sunday, October 4, 2026, at 3:25 PM CDT. More future games.\nUpcoming fixtures')
    assert 'Monday, October 05, 2026 at 1:55 AM IST' in summary
    assert 'future games' not in summary
    monkeypatch.setattr(api,'_conversation_by_thread_id',lambda _: {'messages':[{'role':'assistant','text':summary}]})
    assert api._time_conversion_answer('what is that time in IST?', 'current') == 'That is 1:55 AM IST on Monday, October 05, 2026.'

def test_why_followup_is_bound_to_previous_answer(monkeypatch):
    monkeypatch.setattr(api,'_previous_conversation_turn',lambda *args:('Explain the note organizer benefits',{'role':'assistant','text':'It makes notes easier to find.'}))
    query=api._continuity_request('why?', 'current')
    assert 'Previous assistant answer: It makes notes easier to find.' in query
    assert 'explain the reasoning behind your previous answer' in query

def test_why_context_envelope_does_not_trigger_last_chat_recall():
    assert api._direct_contextual_answer('why?\n\n[Current conversation follow-up]\nPrevious user request: explain benefits', 'current') is None

def test_confused_followup_retries_substantive_request_instead_of_why(monkeypatch):
    monkeypatch.setattr(api, '_thread_user_messages', lambda *a, **k: ['Explain its benefits using two bullets.', 'why?', '??'])
    assert api._continuity_request('??', 'current') == 'Explain its benefits using two bullets.'
    envelope='??\n\n[Conversation follow-up context]\nPrevious user request: why?\nPrevious assistant response: explanation'
    assert api._direct_contextual_answer(envelope, 'current') is None
    assert api._continuity_request(envelope, 'current') == 'Explain its benefits using two bullets.'

def test_user_model_refresh_is_coalesced_after_idle(monkeypatch):
    from agent.memory import memory_context as memory
    scheduled = []
    class Timer:
        def __init__(self, delay, callback, args):
            self.delay, self.callback, self.args, self.cancelled = delay, callback, args, False
            scheduled.append(self)
        def start(self): pass
        def cancel(self): self.cancelled = True
    monkeypatch.setattr(memory.threading, 'Timer', Timer)
    monkeypatch.setattr(memory, '_REFRESH_TIMERS', {})
    calls=[]
    honcho=SimpleNamespace(chat=lambda **kwargs: calls.append(kwargs) or 'Known preference')
    memory.refresh_user_model('one', honcho)
    memory.refresh_user_model('two', honcho)
    assert not calls and scheduled[0].cancelled and len(memory._REFRESH_TIMERS) == 1
    scheduled[-1].callback(*scheduled[-1].args)
    assert calls[0]['session_id'] == 'two'

def test_discord_summary_uses_fetched_messages_and_keeps_sources(monkeypatch):
    from agent.agents.discord import DiscordAgent
    items=[{'id':'1','author':{'username':'Ana'},'content':'Ship on Friday','timestamp':'2026-09-30'}]
    captured=[]
    tools=SimpleNamespace(invoke=lambda *a, **k: {'items':items})
    summarizer=lambda query, messages: captured.append(messages) or 'Ana proposed shipping on Friday.'
    agent=DiscordAgent(tool_registry=tools, discord_service=object(), summarizer=summarizer)
    monkeypatch.setattr(agent, '_resolve_channel_id', lambda query: ('123456789012345',None))
    result=agent.answer('Summarize recent Discord messages')
    assert captured == [items] and result.summary == 'Ana proposed shipping on Friday.'
    assert len(result.sources) == 1 and result.sources[0].snippet == 'Ship on Friday'

def test_private_discord_summary_cannot_use_cloud():
    from agent.agents.discord import LocalDiscordSummarizer
    summarizer=LocalDiscordSummarizer(model_resolver=lambda: 'openai/gpt-4.1', model_factory=lambda *a: pytest.fail('cloud invoked'))
    with pytest.raises(ValueError, match='LOCAL_MODEL'):
        summarizer('Summarize', [])

@pytest.mark.parametrize('message', ['Cancel that.', 'please cancel the post', "don't post it", 'do not send that'])
def test_natural_pending_action_cancellation_never_confirms(message):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    dispatcher=object.__new__(LiveAgentDispatcher)
    assert dispatcher._is_rejection(message)
    assert not dispatcher._is_confirmation(message)

@pytest.mark.parametrize('message', ['Why do I have to confirm?', "don't post it", 'I do not want you to go ahead', 'Can I post it later?'])
def test_mentions_of_confirmation_are_not_authorization(message):
    from agent.agents.live_dispatcher import LiveAgentDispatcher
    assert not object.__new__(LiveAgentDispatcher)._is_confirmation(message)

def test_current_chat_seed_does_not_fetch_unrelated_chats(monkeypatch):
    monkeypatch.setattr(api,'_read_ui_conversations',lambda: (_ for _ in ()).throw(AssertionError('loaded unrelated chats')))
    assert api._recent_conversation_context('For this chat only the label is ORCHID-42', 'current') == ''

def test_temporary_chat_labels_do_not_become_profile_topics(monkeypatch):
    monkeypatch.setattr(api, '_read_ui_conversations', lambda: [{'id':'qa','messages':[{'role':'user','text':'For this chat only, the demonstration project is ORCHID-42.'}]}])
    monkeypatch.setattr(api, '_memory_orchestrator', SimpleNamespace(store=SimpleNamespace(list_saved=lambda **kwargs:[])))
    assert 'ORCHID' not in api._user_profile_recall_answer('What do you know about me?', 'current')

def test_specialist_model_scope_does_not_mutate_global_selection(monkeypatch):
    from agent.llm.providers import ProviderRegistry, request_model_scope
    registry=object.__new__(ProviderRegistry)
    registry._active=SimpleNamespace(id='global')
    monkeypatch.setattr(registry,'resolve',lambda model:SimpleNamespace(id=model))
    with request_model_scope('chat-one'):
        assert registry.current_model().id == 'chat-one'
        with request_model_scope('chat-two'):
            assert registry.current_model().id == 'chat-two'
        assert registry.current_model().id == 'chat-one'
    assert registry.current_model().id == 'global'

@pytest.mark.asyncio
async def test_specialist_passthrough_retains_user_and_answer_in_canonical_checkpoint(monkeypatch):
    updates=[]
    class Runtime:
        async def prepare(self, model): assert model == 'ollama/gemma4:12b'
        async def aupdate_state(self, config, values, **kwargs): updates.append((config,values,kwargs))
    monkeypatch.setattr(api,'agent',Runtime())
    await api._checkpoint_specialist_exchange('next Chiefs game?', 'October 4 at 8:15 PM EDT', 'current', 'ollama/gemma4:12b')
    assert [m.type for m in updates[0][1]['messages']] == ['human','ai']
    assert updates[0][2]['as_node'] == 'agent'

@pytest.mark.asyncio
async def test_model_node_streams_and_preserves_tool_chunks(monkeypatch):
    from langchain_core.messages import AIMessageChunk
    from agent.graph import agent
    monkeypatch.setattr(agent,'vellum_prompt',lambda state,config,**kwargs:state['messages'])
    class Model:
        async def astream(self,messages,config):
            yield AIMessageChunk(content='Hello ')
            yield AIMessageChunk(content='world')
        def invoke(self,*args):
            raise AssertionError('async graph used blocking invoke')
    result=await agent._make_model_node(Model()).ainvoke({'messages':[]},{})
    assert result['messages'][0].content == 'Hello world'

def test_skill_summary_is_bounded_even_when_all_is_requested(monkeypatch):
    class Catalog:
        def __init__(self,*args): pass
        def reconcile(self,**kwargs): pass
    surface=SimpleNamespace(root=Path('.'),catalog=lambda:{'skills':{'active':[{'name':f'skill-{i}', 'description':'long description '*40} for i in range(134)]}})
    monkeypatch.setattr(api,'_skill_surface',lambda:surface)
    monkeypatch.setattr(api,'SkillCatalog',Catalog)
    answer,_=api._skill_system_answer('Give a short summary of all skills installed')
    assert len(answer)<1500
    assert '134 active skills' in answer


def test_source_annotation_does_not_trigger_previous_chat_answer(monkeypatch):
    monkeypatch.setattr(api, "_read_ui_conversations", lambda: [])
    question = "Use my imported Meditations to give a framework and cite source sections."
    annotated = "[Vellum UI context: the user is currently chatting in the Books Agent view.]\n\n" + question + "\n\n[Conversation source context]\nThe previous assistant answer. Use prior-turn conversation sources."
    assert api._direct_contextual_answer(annotated, "current") is None
    assert not api._has_memory_recall_language(annotated)


def test_books_view_why_help_uses_previous_answer(monkeypatch):
    monkeypatch.setattr(api, "_previous_conversation_turn", lambda *a: ("Use Meditations for criticism", {"role":"assistant", "text":"Pause before reacting to criticism."}))
    answer = api._continuity_request("[Vellum UI context: Books Agent view.]\n\nWhy does that help?", "current")
    assert "Previous assistant answer: Pause before reacting to criticism." in answer
    assert api._direct_contextual_answer(answer, "current") is None


@pytest.mark.parametrize("action,message", [("x.publish_post","Yes, publish it."), ("x.reply","Yes, send the reply."), ("x.repost","Yes, repost it."), ("x.unrepost","Yes, remove the repost."), ("x.delete","Yes, delete it.")])
def test_pending_x_confirmation_keeps_original_payload(monkeypatch, action, message):
    pending = {"agent":"XAgent", "action":action, "payload":{"text":"Approved draft", "tweet_id":"123"}}
    monkeypatch.setattr(api._live_dispatcher.state_store, "get_pending_action", lambda *a: pending)
    assert api._live_dispatcher._is_confirmation(message,pending)
    assert api._continuity_request(message, "current") == message
    assert not api._live_dispatcher._is_confirmation("Yes, delete it.", {"action":"x.publish_post"})


@pytest.mark.parametrize("query", ["Read this tweet https://x.com/owner/status/123456789", "What does that post say?", "Show this tweet https://x.com/owner/status/123456789", "Reply to this tweet with thanks"])
def test_x_read_or_reply_is_not_rewritten_as_publishing_previous_answer(monkeypatch, query):
    monkeypatch.setattr(api, "_previous_conversation_turn", lambda *args: ("earlier", {"role": "assistant", "text": "Posted to X: 123456789"}))
    assert api._referenced_x_post_request(query, "qa") is None


def test_read_x_link_fetches_target_without_preparing_write(tmp_path):
    from agent.agents.x_agent import XAgent
    calls = []
    class Service:
        def read_tweet(self, payload):
            calls.append(payload)
            return {"tweet": {"id": "123456789", "handle": "owner", "text": "Actual post", "url": "https://x.com/owner/status/123456789"}, "provider": "agent-reach"}
    agent = XAgent(vault_root=tmp_path, x_service=Service())
    result = agent.answer("Read this tweet https://x.com/owner/status/123456789")
    assert calls == [{"tweet_id": "https://x.com/owner/status/123456789"}]
    assert result.summary == "@owner: Actual post"
    assert not result.action_request
    assert result.sources[0].path_or_url.endswith("123456789")


def test_x_daily_limit_is_actionable_and_not_reported_as_success(tmp_path):
    from agent.agents.x_agent import XAgent
    class Service:
        def repost(self, payload):
            raise RuntimeError("Authorization: You have reached your daily limit for sending Tweets")
    agent = XAgent(vault_root=tmp_path, x_service=Service())
    result = agent.execute_action_request({"action": "x.repost", "payload": {"tweet_id": "123456789"}})
    assert result.status == "error"
    assert "daily posting limit" in result.summary
    assert "completed" not in result.summary


def test_operational_post_request_is_not_a_durable_project_fact():
    from agent.memory.orchestrator import _extract_candidates, _durable_memories
    text = 'Post "Vellum test: checking my local X agent." from my account.'
    assert _extract_candidates(text, "Posted") == []
    assert _durable_memories([{"text": text, "kind": "project"}]) == []


def test_discovery_response_uses_bounded_local_interest_evidence(tmp_path):
    from agent.agents.youtube import YoutubeAgent
    class Service:
        def personal_context(self, payload):
            return {"local_only": True, "channels": [{"label":"Learning", "evidence_count":5}], "search_themes": []}
    result = YoutubeAgent(vault_root=tmp_path, youtube_service=Service()).answer("Discover something based on my interests")
    assert "Learning" in result.summary and "snapshot" in result.summary
    assert result.status == "answered"
