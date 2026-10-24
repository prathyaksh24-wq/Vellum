import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator

from agent.contracts.google_workspace import GoogleApiOperation, GoogleSelection
from agent.plugins import google_api_catalog as catalog
from agent.plugins.google_api import GoogleApiAdapter
from agent.plugins.google_workspace import SERVICES, WRITE_SCOPES
from test_google_workspace import service, grant


@pytest.fixture
def connected(service, monkeypatch):
    grant(service, [scope for key in SERVICES for scope in SERVICES[key]["scopes"] + WRITE_SCOPES[key]])
    service.store._atomic_write(service.store.metadata_path, {**service.store.load_metadata(), "google_account_id":"fixture-account", "google_email":"fixture@example.test"})
    service.registry.set_enabled_many({spec["plugin_id"]:True for spec in SERVICES.values()})
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json={"id":"fixture-result"})
    service.request = request
    monkeypatch.setattr("agent.plugins.google_api.google_service", lambda:service)
    monkeypatch.setattr("agent.plugins.google_workspace.google_service", lambda:service)
    return service, GoogleApiAdapter(service), calls


@pytest.mark.parametrize("name,count", [("gmail",79),("drive",64),("calendar",38),("contacts",24)])
def test_every_bundled_published_operation_has_a_valid_discoverable_schema(name,count):
    assert len(catalog.methods(name)) == count
    for identifier in catalog.methods(name):
        description = catalog.describe(name,identifier)
        Draft202012Validator.check_schema(description["parameters"])
        if description["body"] is not None:
            Draft202012Validator.check_schema(description["body"])
    first = catalog.catalog(name,limit=1)
    assert first["total"]==count and first["next_offset"]==1


CASES = [
    ("gmail","gmail.users.messages.list",{},None),
    ("gmail","gmail.users.drafts.create",{},{"message":{"raw":base64.urlsafe_b64encode(b'To: friend@example.test\r\nSubject: Fixture\r\n\r\nHello').decode()}}),
    ("gmail","gmail.users.labels.update",{"id":"label-1"},{"name":"Updated"}),
    ("gmail","gmail.users.messages.modify",{"id":"mail-1"},{"removeLabelIds":["UNREAD"]}),
    ("gmail","gmail.users.messages.trash",{"id":"mail-1"},None),
    ("gmail","gmail.users.messages.delete",{"id":"mail-1"},None),
    ("drive","drive.files.list",{"pageSize":1},None),
    ("drive","drive.files.create",{},{"name":"Fixture.txt"}),
    ("drive","drive.files.update",{"fileId":"file-1"},{"name":"Renamed.txt"}),
    ("drive","drive.files.delete",{"fileId":"file-1"},None),
    ("calendar","calendar.calendarList.list",{},None),
    ("calendar","calendar.events.insert",{"calendarId":"primary"},{"summary":"Fixture","start":{"date":"2026-10-25"},"end":{"date":"2026-10-26"}}),
    ("calendar","calendar.events.patch",{"calendarId":"primary","eventId":"event-1"},{"summary":"Edited fixture"}),
    ("calendar","calendar.events.delete",{"calendarId":"primary","eventId":"event-1"},None),
    ("contacts","people.people.connections.list",{"resourceName":"people/me","personFields":"names","pageSize":1},None),
    ("contacts","people.people.createContact",{},{"names":[{"givenName":"Fixture"}]}),
    ("contacts","people.people.updateContact",{"resourceName":"people/contact-1","updatePersonFields":"names"},{"names":[{"givenName":"Edited"}]}),
    ("contacts","people.people.deleteContact",{"resourceName":"people/contact-1"},None),
]


@pytest.mark.parametrize("name,identifier,parameters,body",CASES)
def test_read_create_edit_update_and_delete_follow_the_correct_confirmed_path(connected,name,identifier,parameters,body):
    service,adapter,calls=connected
    operation=GoogleApiOperation(service=name,method_id=identifier,parameters=parameters,body=body)
    request=catalog.plan(operation)
    if request["method"]=="GET":
        assert adapter.read(operation)["result"]["id"]=="fixture-result"
    else:
        with pytest.raises(ValueError,match="confirm"):
            adapter.execute(operation)
        with pytest.raises(ValueError,match="changes data"):
            adapter.read(operation)
        binding=adapter.prepare(operation)
        assert not calls and binding["preview"]["account"]=="fixture@example.test"
        assert adapter.execute(operation,binding=binding,confirmed=True)["changed"]
    assert len(calls)==1 and calls[0][0]==request["method"]
    assert calls[0][1].startswith(catalog.ROOTS[name])


def test_new_scopes_require_consent_and_existing_reads_remain_available(service):
    grant(service,SERVICES["gmail"]["scopes"])
    service.registry.set_enabled("gmail",True)
    flow=service.configure(GoogleSelection(services=["gmail"],access="manage"))["flow"]
    assert "mail.google.com" in flow["authorization_url"]
    assert service.status().services[1].authorized and not service.status().services[1].can_write
    with pytest.raises(ValueError,match="additional Google permission"):
        GoogleApiAdapter(service).prepare(GoogleApiOperation(service="gmail",method_id="gmail.users.messages.trash",parameters={"id":"m1"}))


def test_changed_account_payload_or_credential_cannot_reuse_a_review(connected):
    service,adapter,calls=connected
    operation=GoogleApiOperation(service="drive",method_id="drive.files.update",parameters={"fileId":"file-1"},body={"name":"First"})
    binding=adapter.prepare(operation)
    altered=operation.model_copy(update={"body":{"name":"Different"}})
    with pytest.raises(ValueError,match="changed"):
        adapter.execute(altered,binding=binding,confirmed=True)
    metadata=service.store.load_metadata()
    service.store._atomic_write(service.store.metadata_path,{**metadata,"google_account_id":"other"})
    with pytest.raises(ValueError,match="changed"):
        adapter.execute(operation,binding=binding,confirmed=True)
    assert not calls


@pytest.mark.parametrize("change",[{"parameters":{"fileId":"../x"}},{"parameters":{"fileId":"x","access_token":"secret"}},{"body":{"inventedField":"x"}},{"method_id":"https://evil.test"}])
def test_unpublished_endpoints_credentials_fields_and_traversal_are_blocked(change):
    operation=GoogleApiOperation(service="drive",method_id="drive.files.update",parameters={"fileId":"x"},body={"name":"Okay"}).model_copy(update=change)
    with pytest.raises(ValueError):catalog.plan(operation)


def test_contact_reserved_expansion_and_google_media_upload_are_application_owned(connected):
    _,adapter,calls=connected
    operation=GoogleApiOperation(service="drive",method_id="drive.files.update",parameters={"fileId":"file-1"},body={"name":"Fixture.txt"},media_base64=base64.b64encode(b'Fixture file contents').decode(),media_type="text/plain")
    review=adapter.prepare(operation)
    assert "Fixture file contents" not in json.dumps(review)
    adapter.execute(operation,binding=review,confirmed=True)
    assert calls[0][1]=="https://www.googleapis.com/upload/drive/v3/files/file-1"
    assert calls[0][2]["params"]["uploadType"]=="multipart"
    assert b'Fixture file contents' in calls[0][2]["content"]


def test_email_review_decodes_recipient_subject_body_instead_of_raw_base64(connected):
    _,adapter,_=connected
    data=CASES[1]
    review=adapter.prepare(GoogleApiOperation(service=data[0],method_id=data[1],parameters=data[2],body=data[3]))["preview"]
    assert {field["label"]:field["value"] for field in review["fields"]}["To"]=="friend@example.test"
    assert "Hello" in json.dumps(review) and data[3]["message"]["raw"] not in json.dumps(review)


def test_tool_write_uses_real_app_action_preview_then_one_bound_confirmation(connected,tmp_path,monkeypatch):
    from agent.app_actions.models import AppActionContext,AppActionRequest
    from agent.app_actions.runtime import AppActionRuntime
    from agent.plugins.google_workspace_controls import google_contribution
    from agent.plugins.registry import PluginRegistry
    from agent.tools.app_actions import app_action_session
    from agent.tools.google_workspace import google_api_tools
    service,_,calls=connected
    manifest=tmp_path/"plugins/google-workspace/plugin.yaml"
    manifest.write_text(manifest.read_text()+"capabilities:\n  - google.connection.configure\n  - google.connection.disconnect\n  - google.api.execute\n")
    service.registry=PluginRegistry(tmp_path/"plugins",state_path=tmp_path/"state.json")
    runtime=AppActionRuntime(plugin_registry=service.registry)
    runtime.register_plugin_contribution(google_contribution(service=service))
    context=AppActionContext(source="nlp")
    tool=next(tool for tool in google_api_tools() if tool.name=="google_drive")
    with app_action_session(context,"fixture-thread",runtime) as session:
        result=json.loads(tool.invoke({"operation":"execute","method_id":"drive.files.update","parameters":{"fileId":"file-1"},"body":{"name":"Reviewed fixture"}}))
        assert result["status"]=="confirmation_required" and result["result"]["google_review"]["fields"]
        assert not calls
        request=AppActionRequest.model_validate(session.emitted[-1]["request"])
    done=runtime.confirm(result["confirmation"]["token"],request,context)
    assert done.status=="applied" and len(calls)==1
    again=runtime.confirm(result["confirmation"]["token"],request,context)
    assert again.status!="applied" and len(calls)==1


def test_gmail_plain_email_inputs_prepare_a_valid_review_without_model_base64(connected,monkeypatch):
    from agent.tools import app_actions
    from agent.tools.google_workspace import google_api_tools
    _,adapter,calls=connected
    captured=[]
    def dispatch(payload):
        operation=GoogleApiOperation.model_validate(payload['arguments'])
        captured.append(operation)
        return json.dumps(adapter.prepare(operation)['preview'])
    monkeypatch.setattr(app_actions,'app_action',SimpleNamespace(invoke=dispatch))
    tool=next(item for item in google_api_tools() if item.name=='gmail')
    result=json.loads(tool.invoke({'operation':'execute','method_id':'gmail.users.drafts.create','email':{'to':['friend@example.test'],'subject':'Fixture hello','text':'Hello from the test.'}}))
    fields={field['label']:field['value'] for field in result['fields']}
    assert fields['To']=='friend@example.test' and fields['Subject']=='Fixture hello'
    assert 'Hello from the test.' in fields['Message'] and not calls


def test_google_api_read_http_route_rejects_writes_and_unknown_operations(connected,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent.plugins.google_workspace_api import router
    _,_,calls=connected
    app=FastAPI();app.include_router(router,prefix='/api')
    client=TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',1234))
    headers={'Origin':'http://127.0.0.1:5173','X-Vellum-Google':'1'}
    response=client.get('/api/plugins/google/catalog?service=gmail&limit=1',headers=headers)
    assert response.status_code==200 and response.json()['operation_count']==79
    for identifier in ['drive.files.delete','unpublished']:
        response=client.post('/api/plugins/google/api-read',headers=headers,json={'service':'drive','method_id':identifier,'parameters':{'fileId':'fixture'}})
        assert response.status_code==400
    assert not calls


def test_every_published_method_is_a_unique_deferred_native_tool():
    from agent.tools.google_workspace import published_google_tools
    tools=published_google_tools()
    assert len(tools)==205 and len({item.name for item in tools})==205
    assert all(len(item.name)<=64 for item in tools)
    for tool in tools:
        Draft202012Validator.check_schema(tool.args_schema)
        assert len(json.dumps(tool.args_schema)) < 12_000


def test_published_tools_are_compact_but_execution_keeps_full_nested_validation(connected):
    from agent.tools.google_workspace import published_google_tools
    tool=next(item for item in published_google_tools() if item.name=='google_drive_files_update')
    assert len(json.dumps(tool.args_schema))<20_000
    operation=GoogleApiOperation(service='drive',method_id='drive.files.update',parameters={'fileId':'file-1'},body={'contentHints':{'inventedField':'x'}})
    with pytest.raises(ValueError,match='published schema'):
        connected[1].prepare(operation)


def test_native_gmail_draft_accepts_plain_fields_and_reports_missing_fields_without_content(connected,monkeypatch):
    from agent.tools import app_actions
    from agent.tools.google_workspace import published_google_tools
    _,adapter,calls=connected
    monkeypatch.setattr(app_actions,'app_action',SimpleNamespace(invoke=lambda payload:json.dumps(adapter.prepare(GoogleApiOperation.model_validate(payload['arguments']))['preview'])))
    published_google_tools.cache_clear()
    try:
        tool=next(item for item in published_google_tools() if item.name=='gmail_users_drafts_create')
        result=json.loads(tool.invoke({'to':['friend@example.test'],'subject':'Fixture hello','text':'Private fixture text'}))
        fields={field['label']:field['value'] for field in result['fields']}
        assert fields['To']=='friend@example.test' and 'Private fixture text' in fields['Message']
        bad=json.loads(tool.invoke({'subject':'Private fixture subject','text':'Private fixture text'}))
        assert {'field':'email.to','problem':'missing'} in bad['issues']
        assert 'Private fixture' not in json.dumps(bad) and not calls
    finally:
        published_google_tools.cache_clear()


def test_resource_read_reports_the_missing_id_instead_of_retrying_a_search(monkeypatch):
    from agent.tools.google_workspace import google_workspace_read
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:pytest.fail('Invalid input must not access Google'))
    result=json.loads(google_workspace_read.invoke({'service':'drive','action':'file','query':'file-1'}))
    assert 'requires resource_id' in result['error'] and 'action=search' in result['error']


def test_contact_leaf_fields_are_visible_and_full_schema_accepts_exact_tool_name():
    from agent.tools.google_workspace import published_google_tools,google_api_describe
    tool=next(item for item in published_google_tools() if item.name=='google_contacts_people_create_contact')
    phone=tool.args_schema['properties']['body']['properties']['phoneNumbers']['items']
    assert 'value' in phone['properties']
    described=json.loads(google_api_describe.invoke({'service':'contacts','method_id':tool.name}))
    assert described['method_id']=='people.people.createContact'


def test_invalid_contact_phone_reports_field_names_without_the_private_value():
    operation=GoogleApiOperation(service='contacts',method_id='people.people.createContact',body={'phoneNumbers':[{'number':'PRIVATE_FIXTURE'}]})
    with pytest.raises(ValueError) as caught:catalog.plan(operation)
    assert 'phoneNumbers.0' in str(caught.value) and 'value' in str(caught.value)
    assert 'PRIVATE_FIXTURE' not in str(caught.value)


def test_invalid_folder_type_cannot_prepare_an_unintended_regular_file(connected):
    operation=GoogleApiOperation(service='drive',method_id='drive.files.create',body={'name':'Fixture folder','mimeType':'application/vnd.google_apps.folder'})
    with pytest.raises(ValueError,match='application/vnd.google-apps.folder'):
        connected[1].prepare(operation)
    assert not connected[2]


def test_metadata_update_requires_a_change_before_preparing_review(connected):
    with pytest.raises(ValueError,match='needs body'):
        connected[1].prepare(GoogleApiOperation(service='drive',method_id='drive.files.update',parameters={'fileId':'file-1'}))
    assert not connected[2]


def test_mail_projection_drops_html_scripts_encoded_data_and_attachments():
    from agent.plugins.google_workspace import readable_mail
    encoded=base64.urlsafe_b64encode(b'<style>hidden</style><p>Hello fixture</p><script>evil()</script>').decode()
    message=readable_mail({'id':'fixture','payload':{'mimeType':'multipart/mixed','parts':[{'mimeType':'text/html','body':{'data':encoded}},{'filename':'private.txt','mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(b'attachment fixture').decode()}}]}})
    assert 'Hello fixture' in message['text']
    assert all(value not in json.dumps(message) for value in ['evil()','hidden','attachment fixture',encoded])


def test_native_manifests_own_the_exact_generated_method_names():
    from pathlib import Path
    import yaml
    root=Path(__file__).resolve().parents[2]
    for service,folder in {'gmail':'gmail','drive':'google_drive','calendar':'google_calendar','contacts':'google_contacts'}.items():
        manifest=yaml.safe_load((root/'plugins/connectors'/folder/'plugin.yaml').read_text(encoding='utf-8'))
        assert set(manifest['provides_tools'])=={catalog.tool_name(service,method) for method in catalog.methods(service)}


def test_everyday_gmail_tools_keep_small_interfaces_without_losing_full_api_access():
    from agent.tools.google_workspace import published_google_tools,google_api_describe
    tools={tool.name:tool for tool in published_google_tools()}
    draft=tools['gmail_users_drafts_create']
    assert set(draft.args_schema['properties'])=={'to','subject','text','cc','bcc','thread_id'}
    assert len(json.dumps(draft.args_schema))<2000
    assert set(tools['gmail_users_messages_trash'].args_schema['properties'])=={'id'}
    assert set(tools['gmail_users_messages_modify'].args_schema['properties'])=={'id','body'}
    full=json.loads(google_api_describe.invoke({'service':'gmail','method_id':'gmail.users.drafts.create'}))
    assert full['body'] is not None and 'userId' in full['parameters']['properties']


def test_mistaken_google_action_returns_the_exact_discovered_tool_without_writing(connected,tmp_path):
    from agent.app_actions.runtime import AppActionRuntime
    from agent.plugins.google_workspace_controls import google_contribution
    from agent.plugins.registry import PluginRegistry
    from agent.config import REPO_ROOT
    from agent.tools.app_actions import app_action,app_action_session
    service,adapter,calls=connected
    runtime=AppActionRuntime(plugin_registry=PluginRegistry(REPO_ROOT/'plugins',state_path=tmp_path/'registry.json'))
    runtime.register_plugin_contribution(google_contribution(service=service))
    with app_action_session(None,'fixture-delete-recovery',runtime):
        result=json.loads(app_action.invoke({'operation':'execute','action_id':'google.drive.files.delete','arguments':{'fileId':'fixture-folder'}}))
    assert result['status']=='unavailable'
    assert result['suggested_tool']['name']=='google_drive_files_delete'
    assert 'fileId' in result['suggested_tool']['argument_schema']['properties']
    assert not calls


@pytest.mark.parametrize('method_id,arguments',[
    ('drive.files.delete',{'fileId':'fixture-folder'}),
    ('calendar.events.insert',{'calendarId':'primary','body':{'summary':'Fixture badminton','start':{'dateTime':'2026-10-24T20:00:00+05:30','timeZone':'Asia/Kolkata'},'end':{'dateTime':'2026-10-24T21:00:00+05:30','timeZone':'Asia/Kolkata'}}})])
def test_native_google_write_stops_graph_at_review_then_executes_once(connected,tmp_path,monkeypatch,method_id,arguments):
    from agent.app_actions.models import AppActionContext,AppActionRequest
    from agent.app_actions.runtime import AppActionRuntime
    from agent.plugins.google_workspace_controls import google_contribution
    from agent.plugins.registry import PluginRegistry
    from agent.tools.app_actions import app_action_session
    from agent.tools.google_workspace import published_google_tools
    from agent.graph import agent as graph
    from langchain_core.messages import AIMessage,HumanMessage
    from langchain_core.runnables import RunnableLambda
    from langgraph.checkpoint.memory import InMemorySaver
    service,_,calls=connected
    manifest=tmp_path/'plugins/google-workspace/plugin.yaml'
    manifest.write_text(manifest.read_text()+'capabilities:\n  - google.connection.configure\n  - google.connection.disconnect\n  - google.api.execute\n')
    service.registry=PluginRegistry(tmp_path/'plugins',state_path=tmp_path/'state.json')
    runtime=AppActionRuntime(plugin_registry=service.registry)
    runtime.register_plugin_contribution(google_contribution(service=service))
    tool=next(t for t in published_google_tools() if t.metadata['google_method']==method_id)
    monkeypatch.setattr(graph,'_make_context_node',lambda **kw:RunnableLambda(lambda state:{}))
    monkeypatch.setattr(graph,'vellum_prompt',lambda state,*a,**kw:state['messages'])
    class Model:
        max_tokens=2048
        calls=0
        def bind_tools(self,*a,**kw):return self
        def invoke(self,*a,**kw):
            self.calls+=1
            assert self.calls==1,'A prepared review must end tool execution immediately'
            return AIMessage(content='',tool_calls=[{'id':'native-google-write','name':tool.name,'args':arguments}])
    model=Model()
    compiled=graph._build_agent_runtime(llm=model,tools=[tool],deferred_names=set(),checkpointer=InMemorySaver())
    with app_action_session(None,'fixture-google-review',runtime) as session:
        output=compiled.invoke({'messages':[HumanMessage(content='Apply this requested Google change')]},{'configurable':{'thread_id':'fixture-google-review'}})
        receipt=session.emitted[-1]['receipt']
        assert receipt['status']=='confirmation_required' and output['messages'][-1].type=='tool'
        assert not calls
        if method_id.startswith('calendar.'):
            assert '2026-10-24T20:00:00+05:30' in json.dumps(receipt['result']['google_review'])
        request=AppActionRequest.model_validate(session.emitted[-1]['request'])
    done=runtime.confirm(receipt['confirmation']['token'],request,AppActionContext(source='ui'))
    assert done.status=='applied' and len(calls)==1
    assert calls[0][0]==('DELETE' if method_id.startswith('drive.') else 'POST')
    assert runtime.confirm(receipt['confirmation']['token'],request,AppActionContext(source='ui')).status!='applied'
    assert len(calls)==1
