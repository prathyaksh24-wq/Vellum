"""Google capabilities must be reachable from the main agent, without a specialist."""
import pytest

from agent.tools import tool_search
from agent.tools.google_workspace import google_workspace_read


@pytest.mark.parametrize("query", ["check my mail", "read my email", "Gmail inbox"])
def test_mail_intent_discovers_the_google_tool(query):
    catalog = tool_search.build_catalog(tool_search.to_openai_defs([google_workspace_read]))
    matches = tool_search.search_catalog(catalog, query)
    assert any(item.name == "google_workspace_read" for item in matches)


def test_main_agent_has_mail_reads_before_search_and_all_four_service_tools(monkeypatch):
    from agent.graph import agent
    monkeypatch.setattr(agent, "portable_agent_tools", lambda:[])
    monkeypatch.setattr("agent.plugins.linear_mcp.agent_tools", lambda:[])
    tools, deferred = agent._all_runtime_tools()
    names = {tool.name for tool in tools}
    representatives={"gmail_users_drafts_create","google_drive_files_update","google_calendar_events_list","google_contacts_people_update_contact"}
    assert representatives.issubset(names)
    assert "google_workspace_read" not in deferred
    assert representatives.issubset(deferred)


def test_runtime_google_context_reports_current_permission_without_private_content(monkeypatch):
    from types import SimpleNamespace
    from agent.plugins.google_workspace import google_connection_context
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:SimpleNamespace(status=lambda:SimpleNamespace(connected=True,services=[SimpleNamespace(id='gmail',enabled=True,authorized=True,can_write=True)])))
    text=google_connection_context()
    assert 'gmail: read authorized' in text and 'Earlier assistant statements' in text
    assert 'google_workspace_read' in text and "today's mail" in text


def test_today_mail_uses_local_midnight_and_one_readable_page(monkeypatch):
    import json
    from datetime import datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    captured=[]
    clock=datetime(2026,10,24,14,0,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()
    current=SimpleNamespace(clock=lambda:clock,read_mail=lambda **kwargs:captured.append(kwargs) or {'result':{'messages':[]}})
    monkeypatch.setenv('VELLUM_USER_TIMEZONE','Asia/Kolkata')
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:current)
    result=json.loads(google_workspace_read.invoke({'service':'gmail','period':'today','page_token':'fixture-next'}))
    query=captured[0]['query']
    assert f"after:{int(datetime(2026,10,24,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp())}" in query
    assert f"before:{int(datetime(2026,10,25,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp())}" in query
    assert captured[0]['page_token']=='fixture-next' and result['result']['messages']==[]


def test_unrelated_linear_methods_remain_deferred_for_google_turns(monkeypatch):
    from agent.graph import agent
    from langchain_core.tools import StructuredTool
    tools=[StructuredTool.from_function(lambda:'fixture',name=name,description=name) for name in ['linear_save_issue','linear_list_issues','google_workspace_read']]
    monkeypatch.setattr(agent,'core_tools',lambda:tools)
    monkeypatch.setattr(agent,'portable_agent_tools',lambda:[])
    _,deferred=agent._all_runtime_tools()
    assert {'linear_save_issue','linear_list_issues'}.issubset(deferred)
    assert 'google_workspace_read' not in deferred


def test_last_24_hours_is_rolling_not_local_midnight(monkeypatch):
    import json
    from types import SimpleNamespace
    captured=[]
    current=SimpleNamespace(clock=lambda:1792837800,read_mail=lambda **kw:captured.append(kw) or {'result':{'messages':[]}})
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:current)
    google_workspace_read.invoke({'service':'gmail','period':'last_24_hours','limit':40})
    assert captured[0]['query']==f'after:{1792837800-86400} before:1792837800 '
    assert captured[0]['limit']==40


def test_calendar_today_lookup_is_bounded_to_local_day(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from types import SimpleNamespace
    calls=[]
    clock=datetime(2026,10,24,16,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()
    monkeypatch.setenv('VELLUM_USER_TIMEZONE','Asia/Kolkata')
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:SimpleNamespace(clock=lambda:clock,read=lambda *a,**kw:calls.append(kw) or {'result':{'items':[]}}))
    google_workspace_read.invoke({'service':'calendar','period':'today','query':'badminton'})
    assert calls[0]['time_min']=='2026-10-24T00:00:00+05:30'
    assert calls[0]['time_max']=='2026-10-25T00:00:00+05:30'
    assert calls[0]['query']=='badminton'
