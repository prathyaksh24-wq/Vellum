from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from agent.agents.base import SpecialistResponse
from agent.master.runtime import DelegationRequest
from agent.profiles import AgentCatalog, AgentProfile, builtin_profiles
from agent.profiles.execution import ProfileExecution, get_profile_execution, profile_execution, profile_model_id
from agent.profiles.runner import run_profile
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolRegistry
from test_delegation_runtime import build_runtime


def execution(agent="MusicAgent", model="ollama/gemma4:12b"):
    return ProfileExecution(agent, model, "light", f"Instructions for {agent}", "own skill", {"saved_memories":[{"text":"own memory"}]}, "task context", "chat-a")


@pytest.mark.parametrize("agent", list(builtin_profiles()))
def test_every_builtin_has_complete_distinct_profile(agent):
    profile = builtin_profiles()[agent]
    assert profile.executor == "hybrid"
    assert profile.instructions.inline and profile.skills.allow and profile.tools.allow
    assert profile.memory.write_scope == f"agent:{agent}"
    assert profile.memory.read_scopes == ["user_profile", "shared", f"agent:{agent}"]
    assert agent not in profile.memory.receive_from


def test_model_and_evidence_are_task_local_and_removed_after_exit():
    with profile_execution(execution()) as scoped:
        assert profile_model_id(lambda:"wrong") == "ollama/gemma4:12b"
        messages = scoped.messages([HumanMessage(content="play")])
        assert "MusicAgent" in messages[0].content
        assert "own memory" in messages[1].content
        assert "task context" in messages[1].content
        assert len(scoped.messages(messages)) == len(messages)
    assert get_profile_execution() is None


def test_parallel_profiles_cannot_see_each_others_context():
    def run(agent):
        with profile_execution(execution(agent)):
            return get_profile_execution().profile_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run,["XAgent","BooksAgent"])) == ["XAgent","BooksAgent"]
    assert get_profile_execution() is None


def test_music_automatic_context_excludes_portraits_and_provider_activity(tmp_path,monkeypatch):
    runtime,_=build_runtime(tmp_path)
    monkeypatch.setattr(type(runtime.memory_orchestrator), "build_memory_packet", lambda self,**kwargs: {
        "global_summary":"private listening portrait", "recent_context":"provider history",
        "saved_memories":[
            {"scope":"user_profile","kind":"preference","text":"provider-derived taste"},
            {"scope":"agent:MusicAgent","kind":"fact","text":"provider activity"},
            {"scope":"agent:MusicAgent","kind":"preference","text":"I like quiet music"},
        ]})
    with runtime._execution_scope(profile=builtin_profiles()["MusicAgent"],goal="play music",context="",thread_id="t",user_id="u",memory_from=()):
        packet=get_profile_execution().memory
        assert len(packet["saved_memories"]) == 1
        assert "I like quiet music" in str(packet) and "provider" not in str(packet)
        assert "global_summary" not in packet and "recent_context" not in packet


def test_private_scopes_cannot_be_widened_directly():
    with pytest.raises(ValidationError, match="authorized packets"):
        AgentProfile(id="XAgent",memory={"read_scopes":["agent:BooksAgent"]})


def test_handoff_keeps_provenance_and_excludes_unrelated_memory(tmp_path):
    runtime,_ = build_runtime(tmp_path)
    owner = runtime.memory_orchestrator
    profiles = builtin_profiles()
    owner.store.save_memory(scope="agent:BooksAgent",kind="fact",text="Marcus Aurelius book explains Stoic control",source_thread_id="previous",confidence=.9)
    owner.store.save_memory(scope="agent:XAgent",kind="fact",text="Unrelated private X fact",source_thread_id="previous",confidence=.9)
    packet = owner.build_agent_handoff(source=profiles["BooksAgent"],recipient=profiles["XAgent"],query="Stoic control",thread_id="chat-a",user_id="user")
    assert packet["source_agent"] == "BooksAgent" and packet["recipient_agent"] == "XAgent"
    assert packet["authority"] == "evidence_only" and len(packet["items"]) == 1
    assert packet["items"][0]["reference"].startswith("memory:")
    assert "Unrelated" not in str(packet)


@pytest.mark.parametrize("source,recipient", [("CalendarAgent","XAgent"),("DiscordAgent","BooksAgent")])
def test_private_summary_only_agents_cannot_export_packets(tmp_path,source,recipient):
    runtime,_=build_runtime(tmp_path)
    profiles=builtin_profiles()
    runtime.memory_orchestrator.store.save_memory(scope=f"agent:{source}",kind="fact",text="Private messages evidence",source_thread_id="t",confidence=1)
    packet=runtime.memory_orchestrator.build_agent_handoff(source=profiles[source],recipient=profiles[recipient],query="messages",thread_id="t",user_id="u")
    assert packet["items"] == []


@pytest.mark.parametrize("change", ["source_denies","recipient_denies","external"])
def test_both_profile_permissions_and_destination_are_required(tmp_path,change):
    runtime,_=build_runtime(tmp_path)
    source=builtin_profiles()["BooksAgent"]; target=builtin_profiles()["XAgent"]
    if change == "source_denies": source.memory.share_with=[]
    if change == "recipient_denies": target.memory.receive_from=[]
    if change == "external": target.source_egress="external"
    with pytest.raises(PermissionError):
        runtime.memory_orchestrator.build_agent_handoff(source=source,recipient=target,query="Stoic",thread_id="t",user_id="u")


def test_packets_do_not_share_secrets_expired_runs_or_other_users(tmp_path):
    runtime,_=build_runtime(tmp_path); owner=runtime.memory_orchestrator; profiles=builtin_profiles()
    owner.store.save_memory(scope="agent:BooksAgent",kind="fact",text="Stoic token=secret-fixture",source_thread_id="t",confidence=1)
    recent={"reference":"run:one","purpose":"Stoic","summary":"Stoic idea","confidence":.8,"user_id":"other","captured_at":datetime.now(UTC).isoformat()}
    def packet(): return owner.build_agent_handoff(source=profiles["BooksAgent"],recipient=profiles["XAgent"],query="Stoic",thread_id="t",user_id="u",recent=recent)
    assert packet()["items"] == []
    recent["user_id"]="u"; recent["captured_at"]=(datetime.now(UTC)-timedelta(hours=1)).isoformat()
    assert packet()["items"] == []
    recent["captured_at"]=datetime.now(UTC).isoformat()
    assert packet()["items"][0]["reference"] == "run:one"
    owner.store.update_settings({"memory_enabled":False})
    assert packet()["items"] == []


class ScriptedModel:
    def __init__(self, outputs): self.outputs=iter(outputs); self.messages=[]; self.tools=[]
    def bind_tools(self, tools): self.tools=tools; return self
    def invoke(self, messages, **kwargs): self.messages.append(list(messages)); return next(self.outputs)


def tool_call(name,args):
    return AIMessage(content="",tool_calls=[{"name":name,"args":args,"id":"call-1","type":"tool_call"}])


def loop(profile,model,registry=None,**kwargs):
    return run_profile(profile=profile,executor=None,registry=registry,model=model,goal="a question",context="",thread_id="t",memory_reader=lambda source_agent,query:{"items":[]},skill_reader=lambda name:"skill",**kwargs)


def test_native_loop_reads_allowed_tool_and_observes_result():
    registry=ToolRegistry(); calls=[]
    registry.register(CapabilityRecord("sports.query","sports",CapabilityAccess.READ,frozenset({"SportsAgent"}),"Read scores",lambda p:calls.append(p) or {"score":"12-10"}))
    profile=AgentProfile(id="SportsAgent",executor="llm",tools={"allow":["sports.query"]})
    model=ScriptedModel([tool_call("specialist_read",{"name":"sports.query","payload":{"query":"NBA"}}),AIMessage(content="12-10")])
    result=loop(profile,model,registry)
    assert result.summary == "12-10" and calls == [{"query":"NBA"}]
    assert result.activity_events[0]["tool"] == "sports.query"


@pytest.mark.parametrize("payload",[{"action":"save"},{"action":"list","confirm":True}])
def test_loop_cannot_turn_read_adapter_into_write(payload):
    registry=ToolRegistry(); calls=[]
    registry.register(CapabilityRecord("spotify_library","spotify",CapabilityAccess.WRITE,frozenset({"MusicAgent"}),"Library",lambda p:calls.append(p),read_actions=frozenset({"list"})))
    model=ScriptedModel([tool_call("specialist_read",{"name":"spotify_library","payload":payload}),AIMessage(content="Read unavailable")])
    loop(builtin_profiles()["MusicAgent"],model,registry)
    assert calls == [] and "ToolPermissionError" in model.messages[-1][-1].content


def test_chat_only_loop_validates_structured_steps():
    model=ScriptedModel([AIMessage(content='{"kind":"tool","tool":"specialist_memory","arguments":{"source_agent":"BooksAgent","query":"Stoic"}}'),AIMessage(content='{"kind":"answer","answer":"Relevant memory found"}')])
    result=loop(builtin_profiles()["XAgent"],model,native_tools=False)
    assert result.summary == "Relevant memory found"
    assert model.tools == []


def test_books_profile_discussion_preserves_contract_without_inventing_book_evidence():
    from agent.contracts.books import BooksAgentEnvelope
    model=ScriptedModel([AIMessage(content="The profile reference word is amber.")])
    response=loop(builtin_profiles()["BooksAgent"],model)
    envelope=BooksAgentEnvelope.model_validate(response.structured_payload["books_agent"])
    assert envelope.answer == response.summary
    assert envelope.status == "partial" and not envelope.claims and not envelope.evidence
    assert "no Book evidence verified" in response.summary


def test_exact_action_returns_original_receipt_without_model_rewrite():
    receipt=SpecialistResponse(agent="MusicAgent",status="answered",summary="Verified exact result")
    model=ScriptedModel([tool_call("specialist_action",{})])
    result=loop(builtin_profiles()["MusicAgent"],model,action_handler=lambda:receipt)
    assert result is receipt and len(model.messages)==1


def test_runtime_injects_profile_before_inner_model_calls(tmp_path):
    runtime,_=build_runtime(tmp_path)
    class Executor:
        name="SportsAgent"
        def can_handle(self,q): return True
        def answer(self,q):
            current=get_profile_execution()
            assert current.profile_id==self.name and "user_profile" in current.memory["scopes"]
            assert current.thread_id=="profile-thread"
            return SpecialistResponse(agent=self.name,status="answered",summary="ok")
    runtime.agent_catalog.register_executor("SportsAgent",Executor())
    assert runtime.delegate(DelegationRequest("SportsAgent","NBA","profile-thread")).response.status=="answered"
    assert get_profile_execution() is None


def test_local_profile_cannot_send_memory_to_cloud_primary():
    from agent.llm.routing.engine import RoutingEngine
    from agent.profiles import profile_policy
    from agent.privacy.disclosure import DisclosureBlocked
    engine=RoutingEngine(store=SimpleNamespace(list_fallbacks=lambda:[]),pool=None,secret_resolver=None,adapters={})
    with profile_policy(profile_id="XAgent",source_egress="local",allowed_tools=frozenset()), profile_execution(execution("XAgent")):
        with pytest.raises(DisclosureBlocked): engine.build_plan("openai/example")
        assert engine.build_plan("ollama/gemma4:12b").targets[0].provider == "ollama"


def test_handoff_reference_cannot_override_existing_confirmation(tmp_path):
    from agent.master.state import MasterThreadStateStore
    runtime,_=build_runtime(tmp_path)
    runtime.pending_action_store=MasterThreadStateStore(sessions_db=tmp_path/"state.db")
    pending={"agent":"MusicAgent","action":"music.change_collection","payload":{"target":"original"}}
    runtime.pending_action_store.set_pending_action("t",pending)
    assert runtime._resolve_pending_action(agent_id="SportsAgent",parent_thread_id="t",user_id="u") is None
    assert runtime.pending_action_store.get_pending_action("t")["payload"]=={"target":"original"}


def test_unauthorized_handoff_is_blocked_before_execution(tmp_path):
    runtime,_=build_runtime(tmp_path)
    class Executor:
        name="SportsAgent"
        def can_handle(self,q): return True
        def answer(self,q): raise AssertionError("No execution after invalid packet")
    runtime.agent_catalog.register_executor("SportsAgent",Executor())
    runtime.agent_catalog._builtins["XAgent"]=builtin_profiles()["XAgent"]
    result=runtime.delegate(DelegationRequest("SportsAgent","NBA","t",memory_from=("XAgent",)))
    assert result.response.status == "error"


@pytest.mark.parametrize("explicit", [True,False])
def test_contextual_packet_answers_are_not_written_to_global_response_cache(tmp_path,monkeypatch,explicit):
    runtime,_=build_runtime(tmp_path)
    runtime.agent_catalog._builtins=builtin_profiles()
    writes=[]
    monkeypatch.setattr(type(runtime.memory_orchestrator), "store_specialist_response", lambda self,**kwargs:writes.append(kwargs))
    class Executor:
        name="SportsAgent"
        def can_handle(self,q): return True
        def answer(self,q):
            return SpecialistResponse(agent=self.name,status="answered",summary="contextual evidence",
                activity_events=[] if explicit else [{"tool":"specialist_memory"}])
    runtime.agent_catalog.register_executor("SportsAgent",Executor())
    result=runtime.delegate(DelegationRequest("SportsAgent","history","t",memory_from=("BooksAgent",) if explicit else ()))
    assert result.response.status == "answered" and writes == []
