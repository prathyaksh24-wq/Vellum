"""Regression at the real model/tool graph boundary; no model server or Google writes."""
import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from agent.graph import agent as graph


@pytest.mark.parametrize('tool_result,expected_attempts', [({'error':'Invalid Drive query'},2),({'service':'calendar','result':{'items':[]}},3)])
def test_repeated_identical_tool_error_stops_before_recursion_or_provider_failure(monkeypatch,tool_result,expected_attempts):
    monkeypatch.setattr(graph,'_make_context_node',lambda **kw:RunnableLambda(lambda state:{}))
    monkeypatch.setattr(graph,'vellum_prompt',lambda state,*a,**kw:state['messages'])
    class Model:
        max_tokens=2048
        calls=0
        def bind_tools(self,*a,**kw):return self
        def invoke(self,*a,**kw):
            self.calls+=1
            return AIMessage(content='',tool_calls=[{'id':str(self.calls),'name':'google_workspace_read','args':{'query':'invalid fixture'}}])
    attempts=[]
    def read(query:str):
        attempts.append(query)
        return json.dumps(tool_result)
    model=Model()
    tool=StructuredTool.from_function(read,name='google_workspace_read',description='Fixture read')
    runtime=graph._build_agent_runtime(llm=model,tools=[tool],deferred_names=set(),checkpointer=InMemorySaver())
    result=runtime.invoke({'messages':[HumanMessage(content='Delete the folder')]},{'recursion_limit':13,'configurable':{'thread_id':'fixture-repeat-error'}})
    assert len(attempts)==expected_attempts
    assert result['messages'][-1].type=='ai'
    assert 'stopped retrying' in result['messages'][-1].content.lower()


def test_calendar_read_cannot_support_a_booking_claim():
    from agent.tools.app_actions import app_action_session, note_google_read, app_action_result_guard
    with app_action_session(None,'fixture-calendar-read',runtime=object()):
        note_google_read('calendar')
        assert app_action_result_guard("I've scheduled your badminton session for 8:00 PM.") == "I checked Google Calendar, but I haven't created or changed an event. There is no confirmed booking from this request."
        assert app_action_result_guard("You have a meeting scheduled at 8:00 PM.") is None


def test_drive_name_shorthand_escapes_literal_name_and_passes_cursor(monkeypatch):
    from types import SimpleNamespace
    from agent.tools.google_workspace import google_workspace_read
    calls=[]
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:SimpleNamespace(read=lambda *a,**kw:calls.append(kw) or {'result':{'files':[]}}))
    google_workspace_read.invoke({'service':'drive','query':"name:Sam's folder",'page_token':'next-folder-page'})
    assert calls[0]['query']=="name = 'Sam\\'s folder' and trashed = false"
    assert calls[0]['page_token']=='next-folder-page'


def test_failed_call_guard_allows_new_pages_corrected_inputs_and_new_user_turns():
    from langchain_core.messages import ToolMessage
    def ai(i,query):return AIMessage(content='',tool_calls=[{'id':str(i),'name':'google_workspace_read','args':{'query':query}}])
    def result(i,body):return ToolMessage(content=json.dumps(body),tool_call_id=str(i))
    failed=[HumanMessage(content='Find folder'),ai(1,'bad query'),result(1,{'error':'bad query'})]
    assert not graph._repeated_tool_failure(failed+[ai(2,'corrected query'),result(2,{'files':[]})])
    assert not graph._repeated_tool_failure(failed+[HumanMessage(content='Retry'),ai(2,'bad query'),result(2,{'error':'bad query'})])
    assert not graph._repeated_tool_failure([ai(1,'first page'),result(1,{'messages':[]}),ai(2,'next page'),result(2,{'messages':[]})])


def test_stream_never_emits_unverified_calendar_booking_claim(monkeypatch):
    from types import SimpleNamespace
    from agent.tools.app_actions import app_action_session,note_google_read
    from test_chat_stream_sources import _run_stream,_parse_sse
    text="I've scheduled your badminton session for 8:00 PM."
    class Agent:
        async def astream_events(self,*a,**kw):
            note_google_read('calendar')
            yield {'event':'on_chat_model_stream','name':'RoutedChatModel','data':{'chunk':SimpleNamespace(content=text)}}
            yield {'event':'on_chat_model_end','name':'RoutedChatModel','data':{'output':AIMessage(content=text)}}
    with app_action_session(None,'fixture-calendar-stream',runtime=object()):
        events=_parse_sse(_run_stream(monkeypatch,Agent()))
    final=json.loads(next(data for name,data in events if name=='final'))
    assert 'no confirmed booking' in final['answer'].lower()
    assert not any(text in data for name,data in events if name in {'token','response.output_text.delta','final'})


def test_graph_loop_limit_is_not_reported_as_network_unreachable(monkeypatch):
    from langgraph.errors import GraphRecursionError
    from test_chat_stream_sources import _run_stream,_parse_sse
    class Agent:
        async def astream_events(self,*a,**kw):
            if False:yield
            raise GraphRecursionError('fixture tool loop')
    events=_parse_sse(_run_stream(monkeypatch,Agent()))
    error=json.loads(next(data for name,data in events if name=='error'))['error']
    if isinstance(error,dict):error=error['message']
    assert 'tool-step limit' in error and 'unreachable' not in error.lower()


def test_stream_preserves_graph_stop_message_without_a_provider_completion(monkeypatch):
    from test_chat_stream_sources import _run_stream,_parse_sse
    text='The tool calls repeated without making progress, so I stopped retrying.'
    class Agent:
        async def astream_events(self,*a,**kw):
            yield {'event':'on_chain_end','name':'tool_failure','data':{'output':{'messages':[AIMessage(content=text)]}}}
    events=_parse_sse(_run_stream(monkeypatch,Agent()))
    final=json.loads(next(data for name,data in events if name=='final'))
    assert final['answer']==text
