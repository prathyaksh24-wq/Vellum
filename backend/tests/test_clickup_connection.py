"""ClickUp OAuth differences and shared exact-operation review boundaries."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.clickup_connection import ClickUpMcpOperation, ClickUpOAuthRequest
from agent.plugins.clickup_connection import CALLBACK, REGISTER, RESOURCE, ClickUpService


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
    def request(method, url, **kwargs):
        calls.append((url, kwargs))
        value = ({'client_id':'fixture-clickup-client', 'redirect_uris':[CALLBACK], 'token_endpoint_auth_method':'none'}
            if url == REGISTER else {'access_token':'fixture-access', 'token_type':'Bearer', 'expires_in':3600, 'scope':'read write'})
        return SimpleNamespace(status_code=200, json=lambda:value)
    class Transport:
        async def list_tools(self, connector):
            assert connector.url == 'https://mcp.clickup.com/mcp'
            assert connector.headers['Authorization'] == 'Bearer fixture-access'
            # A timer's mutation must stay reviewed even if incorrectly annotated.
            return [{'name':name, 'description':name, 'read_only':True,
                'input_schema':{'type':'object', 'properties':{}, 'additionalProperties':False}}
                for name in ['clickup_get_task', 'clickup_start_time_tracking']]
    current = ClickUpService(keyring=Keyring(), enabled=lambda:True, request=request, transport=Transport(),
        clock=lambda:1000, invalidator=lambda:None)
    current.calls = calls
    return current


def authorize(connection):
    flow = connection.start(ClickUpOAuthRequest())
    connection._finish(flow.flow_id, 'fixture-code')
    assert connection.flow_status(flow.flow_id).status == 'connected'


def test_clickup_registers_own_public_client_with_only_supported_grant(connection):
    flow = connection.start(ClickUpOAuthRequest())
    registration = connection.calls[0][1]['json']
    assert registration['client_name'] == 'Vellum'
    assert registration['grant_types'] == ['authorization_code']
    assert registration['redirect_uris'] == [CALLBACK]
    query = parse_qs(urlsplit(flow.authorization_url).query)
    assert query['resource'] == [RESOURCE] and RESOURCE == 'https://mcp.clickup.com'
    assert query['code_challenge_method'] == ['S256']


def test_authorization_without_refresh_token_is_accepted_and_redacted(connection):
    authorize(connection)
    assert connection.status().connected and connection.status().auth_type == 'oauth'
    assert not connection.load().get('refresh_token')
    assert 'fixture-access' not in connection.status().model_dump_json()


def test_expired_nonrefreshable_grant_requests_signin_without_token_replay(connection):
    authorize(connection)
    before = len(connection.calls)
    connection.clock = lambda:5000
    assert not connection.status().connected
    assert connection.status().status == 'reauthorization_required'
    with pytest.raises(ValueError, match='expired'):
        connection.require()
    assert len(connection.calls) == before


def test_missing_expiry_does_not_invent_a_refresh_token(connection):
    value = connection._tokens({'access_token':'fixture-access', 'token_type':'Bearer'})
    assert 'expires_at' not in value and 'refresh_token' not in value
    assert value['granted_scopes'] == ['read','write']


def test_clickup_ten_year_lifetime_survives_full_oauth_completion(connection):
    original = connection.request
    def request(method, url, **kwargs):
        if url == REGISTER:
            return original(method, url, **kwargs)
        return SimpleNamespace(status_code=200, json=lambda:{'access_token':'fixture-access',
            'token_type':'Bearer', 'expires_in':315360000})
    connection.request = request
    authorize(connection)
    assert connection.load()['expires_at'] == 1000 + 315360000
    assert connection.status().connected
    assert not connection.load().get('refresh_token')


@pytest.mark.parametrize('response', [
    {'access_token':'fixture', 'token_type':'Basic'},
    {'access_token':'fixture', 'token_type':'Bearer', 'expires_in':-1},
    {'access_token':'fixture', 'token_type':'Bearer', 'expires_in':float('inf')},
    {'access_token':'fixture', 'token_type':'Bearer', 'expires_in':float('nan')},
    {'access_token':'fixture', 'token_type':'Bearer', 'expires_in':True},
    {'access_token':'fixture', 'token_type':'Bearer', 'scope':'admin'},
    {'access_token':'fixture', 'token_type':'Bearer', 'refresh_token':''},
])
def test_invalid_token_response_is_not_saved(connection, response):
    with pytest.raises(ValueError):
        connection._tokens(response)
    assert not connection.load()


def test_rejected_replacement_registration_preserves_existing_grant(connection):
    connection.save({'access_token':'previous-access', 'revision':'previous'})
    connection.request = lambda *a,**k:SimpleNamespace(status_code=403, json=lambda:{'error':'client_not_allowed'})
    with pytest.raises(ValueError):
        connection.start(ClickUpOAuthRequest())
    assert connection.load()['access_token'] == 'previous-access'


def test_opaque_client_id_and_unused_secret_do_not_reject_explicit_public_client(connection):
    connection.request = lambda *a,**k:SimpleNamespace(status_code=200, json=lambda:{
        'client_id':'urn:clickup:fixture.client', 'client_secret':'unused-registration-field',
        'token_endpoint_auth_method':'none', 'redirect_uris':[CALLBACK]})
    connection.start(ClickUpOAuthRequest())
    saved = connection.load()
    assert saved['client_id'] == 'urn:clickup:fixture.client'
    assert 'client_secret' not in saved


def test_incompatible_registration_is_retained_privately_without_repeated_dcr(connection):
    calls = []
    def request(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(status_code=200, json=lambda:{'client_id':'fixture-client',
            'token_endpoint_auth_method':'client_secret_basic', 'redirect_uris':[CALLBACK]})
    connection.request = request
    for _ in range(2):
        with pytest.raises(ValueError, match='clickup_registration_shape'):
            connection.start(ClickUpOAuthRequest())
    assert len(calls) == 1
    assert not connection.status().connected


def test_timer_write_cannot_use_read_or_unconfirmed_execution(connection):
    from agent.plugins.web_mcp_actions import WebMcpAdapter
    authorize(connection)
    adapter = WebMcpAdapter(connection, SimpleNamespace())
    operation = ClickUpMcpOperation(tool_name='clickup_start_time_tracking')
    with pytest.raises(ValueError, match='review'):
        adapter.read(operation)
    with pytest.raises(ValueError, match='confirm'):
        adapter.execute(operation)
