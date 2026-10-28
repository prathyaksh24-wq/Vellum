"""Linear connection lifecycle and MCP-owned plugin discovery."""
import json
from pathlib import Path
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.runtime import AppActionRuntime
from agent.plugins.linear import LinearError, LinearService
from agent.plugins.linear_controls import linear_contribution
from agent.plugins.registry import PluginRegistry
from agent.plugins.sources import PluginSourceRecord
TOKEN="Bearer linear-oauth-test-only-secret"
ROOT=Path(__file__).resolve().parents[2]

class MemoryKeyring:
    value=None
    def get_password(self,*_):return self.value
    def set_password(self,_service,_entry,value):self.value=value

@pytest.fixture
def connection():
    requests,settings=[],{'code':200,'enabled':True,'now':1000,'actor':'me','workspace':'workspace','error':None,'write_code':200}
    keyring=MemoryKeyring()
    service=LinearService(keyring=keyring,enabled=lambda:settings['enabled'],clock=lambda:settings['now'])
    def identity(token):
        requests.append(token)
        status={401:'unauthorized',403:'permission_required',429:'rate_limited'}.get(settings['code'])
        status=status or {'RATELIMITED':'rate_limited','FORBIDDEN':'permission_required','UNAUTHENTICATED':'unauthorized','OTHER':'provider_error'}.get(settings['error'])
        if status:raise LinearError('Linear authorization failed.',status)
        return {'actor_id':settings['actor'],'account_name':'Viewer','workspace_id':settings['workspace'],'workspace_name':'Workspace'}
    service._identity=identity
    return service,keyring,settings,requests

def connect(service):
    return service.connect_oauth({'access_token':TOKEN.removeprefix('Bearer '),'token_type':'Bearer','expires_in':3600},
        {'client_id':'public-client'},service._identity(TOKEN))

@pytest.mark.parametrize("operation", ["list","inspect","execute"])
def test_tool_name_used_as_action_id_returns_linear_actions_without_a_write(tmp_path,operation):
    from agent.tools.app_actions import app_action, app_action_session, app_action_result_guard
    runtime=AppActionRuntime(plugin_registry=PluginRegistry(ROOT/"plugins",state_path=tmp_path/"state.json"))
    runtime.register_plugin_contribution(linear_contribution())
    with app_action_session(AppActionContext(source="nlp"),"test-linear-action-help",runtime) as session:
        result=json.loads(app_action.invoke({"operation":operation,"action_id":"linear_api"}))
        assert result["status"]=="unavailable"
        assert "linear.mcp.execute" in [item["id"] for item in result["actions"]]
        assert result["discovery_example"]=={"operation":"list","query":"linear"}
        assert not session.emitted
        if operation=="execute":
            assert "not applied" in app_action_result_guard()


def test_oauth_connection_is_persistent_and_legacy_key_is_not_usable(connection):
    service,keyring,settings,requests=connection
    connect(service)
    assert service.status().connected and service.status().auth_type=='oauth'
    assert TOKEN not in service.status().model_dump_json()
    assert LinearService(keyring=keyring,enabled=lambda:True,clock=lambda:settings['now']).status().connected
    service._save({'token':'lin_api_obsolete','status':'ready','checked_epoch':settings['now']})
    assert not service.status().configured
    with pytest.raises(LinearError):service._require()


def test_oauth_disconnect_and_disabled_guard(connection):
    service,_,settings,_=connection
    connect(service);settings['enabled']=False
    with pytest.raises(LinearError):service._require()
    settings['enabled']=True;service.disconnect()
    assert not service.status().configured


@pytest.mark.parametrize("query,expected",[("create a Linear issue","linear_save_issue"),("recent Linear issues","linear_list_issues")])
def test_common_linear_tasks_discover_the_direct_tool(query,expected):
    from agent.graph.agent import _all_runtime_tools
    from agent.tools.tool_search import build_deferred_catalog, to_openai_defs, search_catalog
    runtime,deferred=_all_runtime_tools()
    catalog=build_deferred_catalog(to_openai_defs(runtime),deferred)
    assert expected in {tool.name for tool in runtime} and expected in deferred
    assert expected in {entry.name for entry in search_catalog(catalog,query)}


@pytest.mark.parametrize("status,expected",[("confirmation_required",True),("failed",False),("applied",False),("blocked",False)])
def test_only_an_actual_pending_confirmation_ends_the_action_turn(status,expected):
    from agent.tools.app_actions import app_action_session, app_action_confirmation_pending
    assert not app_action_confirmation_pending()
    with app_action_session(AppActionContext(source="nlp"),"confirmation-boundary",runtime=object()) as session:
        session.write_results["example"]={"status":status}
        assert app_action_confirmation_pending() is expected
    assert not app_action_confirmation_pending()


@pytest.mark.parametrize("error,status",[("RATELIMITED","rate_limited"),("FORBIDDEN","permission_required"),("OTHER","provider_error"),("UNAUTHENTICATED","unauthorized")])
def test_identity_partial_responses_are_not_success_and_do_not_echo_provider_secrets(connection,error,status):
    service,_,settings,_=connection
    connect(service);settings["error"]=error
    with pytest.raises(LinearError) as failure:service.verify()
    assert failure.value.status==status and TOKEN not in str(failure.value)


def test_catalog_replaces_imported_linear_without_duplicate(tmp_path,connection):
    class Source:
        def discover(self):return [PluginSourceRecord(id="linear",name="Linear",version="legacy",description="Imported app",category="Other",developer="OpenAI",source="openai_plugin",root=tmp_path)]
    registry=PluginRegistry(ROOT/"plugins",state_path=tmp_path/"state.json",sources=[Source()])
    result=[item for item in registry.catalog() if item["id"]=="linear"]
    from agent.plugins.linear_mcp import published_tools
    assert len(result)==1 and result[0]["source"]=="portable"
    assert set(result[0]["tools"])=={"linear_"+tool["name"] for tool in published_tools()}
    assert result[0]["category"]=="Productivity" and len(result[0]["mcp_connectors"])==1


def test_http_local_origin_guards_and_removed_key_routes(connection,monkeypatch):
    from agent.plugins import linear_api
    service,_,_,_=connection;monkeypatch.setattr(linear_api,"linear_service",lambda:service)
    app=FastAPI();app.include_router(linear_api.router,prefix="/api")
    with TestClient(app,base_url="http://127.0.0.1:8000",client=("127.0.0.1",1234)) as client:
        assert client.get('/api/plugins/linear/status').status_code==403
        response=client.get('/api/plugins/linear/status',headers={'Origin':'http://127.0.0.1:5173','X-Vellum-Linear':'1'})
        assert response.status_code==200 and response.json()['auth_type']=='oauth'
        assert client.post('/api/plugins/linear/credentials/stage',json={'token':TOKEN}).status_code==404
        assert client.post('/api/plugins/linear/credentials/discard',json={'credential_id':'old'}).status_code==404
