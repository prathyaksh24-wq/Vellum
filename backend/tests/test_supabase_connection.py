"""Supabase confidential-client OAuth and exact-input tool policy; no live projects."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.supabase_connection import SupabaseOAuthRequest
from agent.contracts.supabase_connection import SupabaseMcpOperation
from agent.plugins.supabase_connection import CALLBACK, RESOURCE, SupabaseService


class Keyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, account):
        return self.data.get((service, account))

    def set_password(self, service, account, value):
        self.data[service, account] = value

    def delete_password(self, service, account):
        self.data.pop((service, account), None)


@pytest.fixture
def connection():
    calls = []
    def request(method, url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith('/register'):
            result = {'client_id':'fixture-client', 'client_secret':'fixture-client-secret',
                'redirect_uris':[CALLBACK], 'token_endpoint_auth_method':'client_secret_basic'}
        else:
            result = {'access_token':'fixture-access', 'refresh_token':'fixture-refresh',
                'token_type':'Bearer', 'expires_in':3600}
        return SimpleNamespace(status_code=200, json=lambda:result)

    class Transport:
        async def list_tools(self, connector):
            assert connector.headers['Authorization'] == 'Bearer fixture-access'
            return [{'name':name, 'description':name, 'read_only':name != 'create_project',
                'input_schema':{'type':'object','properties':{}}} for name in ['list_tables','execute_sql','apply_migration','confirm_cost','create_project']]

    current = SupabaseService(keyring=Keyring(), enabled=lambda:True, request=request,
        transport=Transport(), clock=lambda:1000, invalidator=lambda:None)
    current.calls = calls
    return current


def test_registration_and_flow_keep_client_secret_out_of_public_contracts(connection):
    flow = connection.start(SupabaseOAuthRequest())
    assert connection.load()['client_secret'] == 'fixture-client-secret'
    assert 'fixture-client-secret' not in flow.model_dump_json()
    assert 'fixture-client-secret' not in connection.status().model_dump_json()
    params = parse_qs(urlsplit(flow.authorization_url).query)
    assert params['resource'] == [RESOURCE] and params['redirect_uri'] == [CALLBACK]
    assert params['code_challenge_method'] == ['S256'] and 'client_secret' not in params


def test_token_exchange_and_saved_grant_retain_confidential_registration(connection):
    flow = connection.start(SupabaseOAuthRequest())
    connection._finish(flow.flow_id, 'fixture-code')
    status = connection.status()
    assert status.connected and status.auth_type == 'oauth' and not status.identity_verified
    assert connection.load()['client_secret'] == 'fixture-client-secret'
    token_call = next(kwargs for url,kwargs in connection.calls if url.endswith('/token'))
    assert 'auth' in token_call and 'client_secret' not in token_call['data']
    assert token_call['data']['resource'] == RESOURCE


def test_disconnect_retains_registration_but_removes_user_authorization(connection):
    flow = connection.start(SupabaseOAuthRequest())
    connection._finish(flow.flow_id, 'fixture-code')
    connection.disconnect()
    saved = connection.load()
    assert saved['client_id'] == 'fixture-client' and saved['client_secret'] == 'fixture-client-secret'
    assert 'access_token' not in saved and 'refresh_token' not in saved
    assert not connection.status().configured


def test_sql_migrations_and_cost_authorization_cannot_take_the_read_path(connection):
    tools = connection._catalog({'access_token':'fixture-access'})
    assert next(tool for tool in tools if tool['name']=='list_tables')['read_only']
    assert all(not tool['read_only'] for tool in tools if tool['name'] in {'execute_sql','apply_migration','confirm_cost'})
    assert 'storage' in connection.provider.server and 'skip_elicitations' not in connection.provider.server


def test_bad_registration_does_not_overwrite_existing_authorization(connection):
    connection.save({'access_token':'previous', 'revision':'previous'})
    connection.request=lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:{'client_id':'wrong', 'client_secret':'x', 'redirect_uris':['https://other.example/callback']})
    with pytest.raises(ValueError):
        connection.start(SupabaseOAuthRequest())
    assert connection.load()['access_token'] == 'previous'


def test_failed_oauth_keeps_saved_client_secret_out_of_error_message(connection):
    flow = connection.start(SupabaseOAuthRequest())
    connection.request=lambda *a,**k:SimpleNamespace(status_code=401,json=lambda:{'client_secret':'fixture-client-secret'})
    connection._finish(flow.flow_id, 'fixture-code')
    result = connection.flow_status(flow.flow_id)
    assert result.status == 'failed' and 'fixture-client-secret' not in result.message


@pytest.mark.parametrize('state,pending', [('COMING_UP',True), ('ACTIVE_HEALTHY',False)])
def test_project_provisioning_is_not_reported_ready_before_supabase_confirms_health(connection, state, pending):
    from agent.plugins.web_mcp_actions import WebMcpAdapter
    flow = connection.start(SupabaseOAuthRequest())
    connection._finish(flow.flow_id, 'fixture-code')
    class Approvals:
        def request(self, operation):
            return {'id':'fixture-approval'}
        def approve(self, identifier):
            assert identifier == 'fixture-approval'
    class Runtime:
        approval_store = Approvals()
        async def call_tool(self, *args, **kwargs):
            return json.dumps({'status':state, 'id':'fixture-project'})
    adapter = WebMcpAdapter(connection, Runtime())
    operation = SupabaseMcpOperation(tool_name='create_project',arguments={})
    binding = adapter.prepare(operation)
    result = adapter.execute(operation,binding=binding,confirmed=True)
    assert result['pending'] is pending
