"""Vercel registration, resource binding and reviewed deployment lifecycle."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.vercel_connection import VercelMcpOperation, VercelOAuthRequest
from agent.plugins.vercel_connection import CALLBACK, REGISTER, RESOURCE, VercelService


class Keyring:
    def __init__(self):
        self.values = {}
    def get_password(self, service, account):
        return self.values.get((service, account))
    def set_password(self, service, account, value):
        self.values[service, account] = value
    def delete_password(self, service, account):
        self.values.pop((service, account), None)


@pytest.fixture
def connection():
    calls = []
    def request(method,url,**kwargs):
        calls.append((url,kwargs))
        value = ({'client_id':'fixture-vercel-client', 'redirect_uris':[CALLBACK], 'token_endpoint_auth_method':'none'}
            if url==REGISTER else {'access_token':'fixture-access','refresh_token':'fixture-refresh','token_type':'Bearer','expires_in':3600})
        return SimpleNamespace(status_code=200,json=lambda:value)
    class Transport:
        async def list_tools(self,connector):
            assert connector.url == 'https://mcp.vercel.com'
            assert connector.headers['Authorization'] == 'Bearer fixture-access'
            return [{'name':name,'description':name,'read_only':name!='create_deployment',
                'input_schema':{'type':'object','properties':{}}} for name in ['list_projects','create_deployment']]
    current=VercelService(keyring=Keyring(),enabled=lambda:True,request=request,transport=Transport(),
        clock=lambda:1000,invalidator=lambda:None)
    current.calls=calls
    return current


def test_vercel_registers_itself_and_uses_exact_advertised_resource(connection):
    flow=connection.start(VercelOAuthRequest())
    registration=connection.calls[0][1]['json']
    assert registration['client_name']=='Vellum' and registration['application_type']=='native'
    assert registration['redirect_uris']==[CALLBACK] and registration['token_endpoint_auth_method']=='none'
    query=parse_qs(urlsplit(flow.authorization_url).query)
    assert query['resource']==[RESOURCE] and RESOURCE=='https://mcp.vercel.com/'
    assert query['code_challenge_method']==['S256'] and 'client_secret' not in query


def test_rejected_registration_keeps_previous_grant_and_does_not_fall_back_to_another_client(connection):
    connection.save({'access_token':'previous-access','revision':'previous'})
    connection.request=lambda *a,**k:SimpleNamespace(status_code=403,json=lambda:{'error':'client_not_allowed'})
    with pytest.raises(ValueError):connection.start(VercelOAuthRequest())
    assert connection.load()['access_token']=='previous-access'
    assert connection.tools==[] and connection.flows=={}


def test_confidential_or_wrong_callback_registration_is_not_accepted(connection):
    connection.request=lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:{'client_id':'fixture-client','client_secret':'not-public','redirect_uris':[CALLBACK]})
    with pytest.raises(ValueError):connection.start(VercelOAuthRequest())
    assert not connection.status().configured


def test_saved_connection_contains_refresh_authorization_but_public_status_does_not(connection):
    flow=connection.start(VercelOAuthRequest());connection._finish(flow.flow_id,'fixture-code')
    assert connection.status().connected and connection.status().auth_type=='oauth'
    assert connection.load()['refresh_token']=='fixture-refresh'
    assert 'fixture-refresh' not in connection.status().model_dump_json()


@pytest.mark.parametrize('state,pending',[('BUILDING',True),('QUEUED',True),('READY',False)])
def test_building_deployment_is_not_reported_ready(connection,state,pending):
    from agent.plugins.web_mcp_actions import WebMcpAdapter
    flow=connection.start(VercelOAuthRequest());connection._finish(flow.flow_id,'fixture-code')
    class Approvals:
        def request(self,operation):return {'id':'fixture-approval'}
        def approve(self,identifier):assert identifier=='fixture-approval'
    class Runtime:
        approval_store=Approvals()
        async def call_tool(self,*args,**kwargs):return json.dumps({'id':'fixture-deployment','readyState':state})
    adapter=WebMcpAdapter(connection,Runtime());operation=VercelMcpOperation(tool_name='create_deployment',arguments={})
    binding=adapter.prepare(operation)
    assert adapter.execute(operation,binding=binding,confirmed=True)['pending'] is pending
