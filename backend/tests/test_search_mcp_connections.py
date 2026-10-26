"""Search connector credentials, exact MCP scope and deferred dispatch boundaries."""
import json
from types import SimpleNamespace

import pytest

from agent.contracts.exa_connection import ExaMcpOperation
from agent.plugins.exa_connection import ExaService
from agent.plugins.serpapi_connection import SerpApiService
from agent.plugins.tavily_connection import TavilyService
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class Keyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        self.values[service, account] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


def service(cls, *, keyring=None, request=None, transport=None):
    return cls(keyring=keyring or Keyring(), enabled=lambda: True, request=request,
               transport=transport, clock=lambda: 1000, invalidator=lambda: None)


class Catalog:
    async def list_tools(self, connector):
        assert connector.headers['Authorization'].startswith('Bearer ')
        assert 'api_key=' not in connector.url and 'tavilyApiKey=' not in connector.url
        return [{'name': 'agent_run' if connector.plugin_id == 'exa' else 'search',
                 'description': 'Published operation', 'read_only': True,
                 'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'runId': {'type': 'string'}}}}]


def test_serpapi_key_is_verified_before_save_and_kept_out_of_actions_and_status():
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        assert kwargs['params']['api_key'] == 'fixture-serpapi-key'
        return SimpleNamespace(status_code=200, json=lambda: {'account_id': 'account-1', 'account_email': 'fixture@example.test'})
    current = service(SerpApiService, request=request, transport=Catalog())
    reference = current.stage('fixture-serpapi-key')
    assert 'fixture-serpapi-key' not in reference
    status = current.connect(reference)
    assert status.connected and status.auth_type == 'api_key' and not status.oauth_available
    assert calls == [('GET', 'https://serpapi.com/account.json')]
    assert 'fixture-serpapi-key' not in status.model_dump_json()
    with pytest.raises(ValueError):
        current.connect(reference)


def test_bad_serpapi_replacement_preserves_working_key_and_redacts_provider_response():
    current = service(SerpApiService, request=lambda *a, **k: SimpleNamespace(status_code=401, json=lambda: {'api_key':'do-not-echo'}), transport=Catalog())
    current.save({'access_token':'previous-key', 'revision':'previous', 'managed':True})
    with pytest.raises(ValueError) as error:
        current.connect(current.stage('rejected-key'))
    assert 'do-not-echo' not in str(error.value)
    assert current.load()['access_token'] == 'previous-key'


@pytest.mark.parametrize('cls', [SerpApiService, ExaService, TavilyService])
def test_disconnect_is_a_managed_tombstone_and_survives_new_service_instance(cls):
    store = Keyring()
    current = service(cls, keyring=store)
    current.save({'access_token':'old-key', 'revision':'old', 'managed':True})
    current.disconnect()
    replacement = service(cls, keyring=store)
    assert replacement.managed() and not replacement.status().configured
    assert replacement.load()['revision'] != 'old'
    with pytest.raises(ValueError):
        replacement.require()


def test_exa_catalog_is_complete_and_plain_keys_cannot_pass_as_oauth():
    current = service(ExaService, transport=Catalog())
    assert 'web_search_advanced_exa' in current.provider.server and 'agent_run' in current.provider.server
    assert current.provider.resource == 'https://mcp.exa.ai/mcp'
    with pytest.raises(ValueError):
        current._tokens({'access_token':'plain-key', 'refresh_token':'refresh', 'token_type':'Bearer', 'expires_in':3600})
    tools = current._catalog({'access_token':'fixture.jwt.signature'})
    assert tools[0]['name'] == 'agent_run' and tools[0]['read_only'] is False


def test_exa_existing_run_poll_is_read_only_but_start_requires_review():
    current = service(ExaService, transport=Catalog())
    current.save({'access_token':'fixture.jwt.signature', 'revision':'grant-1', 'managed':True, 'account_id':'grant-1', 'account_name':'Fixture'})
    adapter = WebMcpAdapter(current)
    assert adapter.tool(ExaMcpOperation(tool_name='agent_run', arguments={'runId':'run-1'}))['read_only']
    assert not adapter.tool(ExaMcpOperation(tool_name='agent_run', arguments={'query':'Research this'}))['read_only']
    assert not adapter.tool(ExaMcpOperation(tool_name='agent_run', arguments={'runId':'run-1','query':'New research'}))['read_only']


def test_catalog_summaries_do_not_disclose_all_schemas():
    current = service(ExaService, transport=Catalog())
    current.save({'access_token':'fixture.jwt.signature', 'revision':'grant-1', 'managed':True})
    result = deferred_tools(lambda: current, ExaMcpOperation, lambda name:'exa_tool_'+name)
    summary = json.loads(result[0].invoke({}))
    assert summary['total'] == 1 and 'input_schema' not in summary['tools'][0]
    schema = json.loads(result[1].invoke({'tool_name':'agent_run'}))
    assert schema['input_schema']['properties']['runId']['type'] == 'string'


def test_tavily_uses_own_oauth_scope_and_fixed_callback():
    current = service(TavilyService)
    assert current.provider.scopes == 'openid offline_access'
    assert current.provider.callback == 'http://127.0.0.1:8000/api/plugins/tavily/oauth/callback'
    assert current.provider.resource == 'https://mcp.tavily.com/mcp'
    assert current.connector({'access_token':'fixture'}).url == 'https://mcp.tavily.com/mcp/'


def test_invalid_oauth_resource_is_not_reported_as_user_declining():
    current = service(TavilyService)
    current.flows['flow-1'] = {'state':'fixture-state', 'status':'pending', 'created':1000,
                               'consumed':False, 'verifier':'fixture', 'message':'Pending'}
    identifier = current.callback('fixture-state', '', 'invalid_target')
    result = current.flow_status(identifier)
    assert result.status == 'failed' and 'resource' in result.message
    assert 'declined' not in result.message and 'verifier' not in current.flows[identifier]


def test_existing_serpapi_client_observes_saved_key_and_disconnect(monkeypatch, tmp_path):
    from agent.tools.serpapi import SerpApiClient
    from agent.plugins import search_connections
    current = service(SerpApiService)
    current.save({'access_token':'saved-fixture-key', 'revision':'grant', 'managed':True})
    monkeypatch.setattr(search_connections, 'service_for', lambda name:current)
    client = SerpApiClient(log_path=tmp_path/'search.jsonl')
    assert search_connections.credential('serpapi') == 'saved-fixture-key'
    current.disconnect()
    with pytest.raises(ValueError):
        client.search({'q':'No request may leave this client'})
