"""HubSpot confidential OAuth, secret staging and review boundaries."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.hubspot_connection import HubSpotAppCredentials, HubSpotOAuthRequest, HubSpotMcpOperation
from agent.plugins.hubspot_connection import CALLBACK, HubSpotService


class Keyring:
    def __init__(self):self.values = {}
    def get_password(self,service,account):return self.values.get((service,account))
    def set_password(self,service,account,value):self.values[(service,account)] = value
    def delete_password(self,service,account):self.values.pop((service,account),None)


@pytest.fixture
def connection():
    calls = []
    def request(method,url,**kwargs):
        assert url == 'https://mcp.hubspot.com/oauth/v3/token'
        assert kwargs['data']['client_id'] == 'fixture-client'
        assert kwargs['data']['client_secret'] == 'fixture-secret'
        calls.append(kwargs['data'])
        return SimpleNamespace(status_code=200,json=lambda:{'access_token':'fixture-access',
            'token_type':'bearer','refresh_token':'fixture-refresh','expires_in':1800})
    class Transport:
        async def list_tools(self,connector):
            assert connector.url == 'https://mcp.hubspot.com'
            return [{'name':name,'description':name,'input_schema':{'type':'object','properties':{}},'read_only':True}
                for name in ('get_user_details','manage_crm_records')]
    current = HubSpotService(keyring=Keyring(),enabled=lambda:True,clock=lambda:1000,
        request=request,transport=Transport(),invalidator=lambda:None)
    current.calls = calls
    return current


def configure(connection):
    credentials = HubSpotAppCredentials(client_id='fixture-client',client_secret='fixture-secret')
    reference = connection.stage(credentials)
    assert reference != 'fixture-secret'
    return connection.configure(reference)


def authorize(connection):
    configure(connection)
    flow = connection.start(HubSpotOAuthRequest())
    connection._finish(flow.flow_id,'fixture-code')
    assert connection.flow_status(flow.flow_id).status == 'connected'


def test_setup_is_required_and_never_uses_dcr(connection):
    assert not connection.status().oauth_available
    with pytest.raises(ValueError,match='local setup form'):
        connection.start(HubSpotOAuthRequest())
    assert connection.calls == []


def test_staged_credentials_expire_or_can_be_discarded(connection):
    credentials = HubSpotAppCredentials(client_id='fixture-client',client_secret='fixture-secret')
    reference = connection.stage(credentials)
    connection.discard(reference)
    with pytest.raises(ValueError,match='expired'):connection.configure(reference)
    reference = connection.stage(credentials)
    connection.clock = lambda:1700
    with pytest.raises(ValueError,match='expired'):connection.configure(reference)
    assert not connection.status().app_registered


def test_pkce_confidential_exchange_and_automatic_provider_scopes(connection):
    assert CALLBACK == 'http://localhost:8000/api/plugins/hubspot/oauth/callback'
    assert configure(connection).oauth_available
    flow = connection.start(HubSpotOAuthRequest())
    query = parse_qs(urlsplit(flow.authorization_url).query)
    assert query['redirect_uri'] == [CALLBACK]
    assert query['code_challenge_method'] == ['S256']
    assert 'scope' not in query and 'client_secret' not in query
    connection._finish(flow.flow_id,'fixture-code')
    assert connection.status().connected
    assert 'fixture-secret' not in connection.status().model_dump_json()
    assert 'fixture-access' not in connection.status().model_dump_json()


def test_refresh_and_disconnect_use_same_app_without_losing_registration(connection):
    authorize(connection)
    connection.clock = lambda:2800
    connection.require()
    assert connection.calls[-1]['grant_type'] == 'refresh_token'
    connection.disconnect()
    assert connection.load()['client_secret'] == 'fixture-secret'
    assert 'access_token' not in connection.load()
    assert not connection.status().connected and connection.status().oauth_available


def test_connected_account_blocks_replacing_app_credentials(connection):
    authorize(connection)
    reference = connection.stage(HubSpotAppCredentials(client_id='different-client',client_secret='different-secret'))
    with pytest.raises(ValueError,match='Disconnect'):connection.configure(reference)
    assert connection.load()['access_token'] == 'fixture-access'


def test_management_tool_cannot_bypass_review_even_if_misannotated(connection):
    from agent.plugins.web_mcp_actions import WebMcpAdapter
    authorize(connection)
    adapter = WebMcpAdapter(connection,SimpleNamespace())
    operation = HubSpotMcpOperation(tool_name='manage_crm_records')
    with pytest.raises(ValueError,match='review'):adapter.read(operation)
    with pytest.raises(ValueError,match='confirm'):adapter.execute(operation)


def test_credential_validation_response_redacts_input(connection,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent.plugins import hubspot_api
    monkeypatch.setattr(hubspot_api,'hubspot_service',lambda:connection)
    app = FastAPI();app.include_router(hubspot_api.router,prefix='/api')
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',50000)) as client:
        response = client.post('/api/plugins/hubspot/credentials/stage',headers={
            'Origin':'http://127.0.0.1:5173','X-Vellum-Accounts':'1'},
            json={'client_id':'invalid id','client_secret':'fixture-secret-must-not-echo'})
        assert response.status_code == 422
        assert 'fixture-secret-must-not-echo' not in response.text
