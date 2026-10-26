"""Firecrawl/Apify connection boundaries, deferred schemas and reviewed operations."""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.apify_connection import ApifyMcpOperation, ApifyOAuthRequest
from agent.contracts.firecrawl_connection import FirecrawlMcpOperation, FirecrawlOAuthRequest
from agent.plugins.apify_connection import ApifyService
from agent.plugins.firecrawl_connection import FirecrawlService
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools


class Keyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        assert len(value.encode('utf-16-le')) <= 2560
        self.values[service, account] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


@pytest.fixture(params=['firecrawl', 'apify'])
def connection(request):
    name = request.param
    requests = []

    def http(method, url, **kwargs):
        requests.append((method, url))
        if url.endswith('/register') or url.endswith('/oauth/apps'):
            value = {'client_id': 'fixture-client', 'token_endpoint_auth_method': 'none',
                     'redirect_uris': kwargs['json']['redirect_uris']}
        elif url.endswith('/token'):
            value = {'access_token': 'fixture-oauth-access', 'refresh_token': 'fixture-refresh',
                     'token_type': 'Bearer', 'expires_in': 3600}
        else:
            assert method == 'GET' and url == 'https://api.apify.com/v2/users/me'
            value = {'data': {'id': 'fixture-user-12345', 'username': 'Fixture account'}}
        return SimpleNamespace(status_code=200, json=lambda: value)

    if name == 'firecrawl':
        tools = [
            {'name': 'firecrawl_scrape', 'description': 'Read a page', 'read_only': True,
             'input_schema': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}},
            {'name': 'firecrawl_interact', 'description': 'Interact with a remote browser', 'read_only': True,
             'input_schema': {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']}},
        ]
    else:
        tools = [
            {'name': 'search-actors', 'description': 'Discover Actors', 'read_only': True,
             'input_schema': {'type': 'object', 'properties': {'query': {'type': 'string'}}}},
            {'name': 'call-actor', 'description': 'Launch an Actor', 'read_only': True,
             'input_schema': {'type': 'object', 'properties': {'actor': {'type': 'string'}, 'input': {'type': 'object'}}, 'required': ['actor', 'input']}},
            {'name': 'apify--web-fetch', 'description': 'Run a specific Actor', 'read_only': True,
             'input_schema': {'type': 'object', 'properties': {'url': {'type': 'string'}}}},
        ]

    class Transport:
        async def call_tool(self, connector, name, arguments):
            assert connector.headers['Authorization'].startswith('Bearer ')
            assert name == 'firecrawl_credit_usage' and arguments == {}
            return json.dumps({'success': True, 'data': {'remainingCredits': 100}})

        async def list_tools(self, connector):
            return tools

    cls = FirecrawlService if name == 'firecrawl' else ApifyService
    service = cls(keyring=Keyring(), enabled=lambda: True, request=http, transport=Transport(),
                  clock=lambda: 1000, invalidator=lambda: None)
    service.configured_credential = lambda: 'fixture-configured-key'
    service.request_history = requests
    return service


def operation(service, changed=False):
    if service.provider.plugin_id == 'firecrawl':
        return FirecrawlMcpOperation(tool_name='firecrawl_interact' if changed else 'firecrawl_scrape',
                                    arguments={'url': 'https://example.com'})
    return ApifyMcpOperation(tool_name='call-actor' if changed else 'search-actors',
                            arguments={'actor': 'fixture/actor', 'input': {}} if changed else {'query': 'example'})


def test_configured_key_is_verified_before_save_and_never_exposed(connection):
    assert not connection.status().configured
    status = connection.use_configured()
    assert status.connected and status.auth_type == 'configured_api_key'
    assert connection.managed()
    assert 'fixture-configured-key' not in status.model_dump_json()
    assert status.identity_verified is (connection.provider.plugin_id == 'apify')


def test_oauth_does_not_require_an_operator_key_and_uses_the_exact_provider_resource(connection):
    connection.configured_credential = lambda: ''
    request = FirecrawlOAuthRequest() if connection.provider.plugin_id == 'firecrawl' else ApifyOAuthRequest()
    flow = connection.start(request)
    parsed = urlsplit(flow.authorization_url)
    args = parse_qs(parsed.query)
    assert parsed.scheme == 'https' and args['code_challenge_method'] == ['S256']
    assert args['resource'] == [connection.provider.resource]
    assert args['redirect_uri'] == [connection.provider.callback]
    assert 'code_verifier' not in args and 'client_secret' not in args
    connection._finish(flow.flow_id, 'fixture-code')
    assert connection.status().connected and connection.status().auth_type == 'oauth'


def test_failed_replacement_preserves_the_connected_grant(connection):
    connection.use_configured()
    original = connection.load()
    request = FirecrawlOAuthRequest() if connection.provider.plugin_id == 'firecrawl' else ApifyOAuthRequest()
    flow = connection.start(request)
    connection.cancel(flow.flow_id)
    connection._finish(flow.flow_id, 'fixture-code')
    saved = connection.load()
    assert saved['access_token'] == original['access_token'] and saved['revision'] == original['revision']
    assert connection.flow_status(flow.flow_id).status == 'cancelled'


def test_disconnect_does_not_silently_reactivate_configured_environment_key(connection):
    connection.use_configured()
    connection.disconnect()
    assert connection.configured_credential() and connection.managed()
    assert not connection.status().configured
    with pytest.raises(connection.error_type, match='Sign in'):
        connection.require()


def test_remote_browser_and_actor_runs_require_reviews_even_with_read_annotations(connection):
    connection.use_configured()
    tools = connection.catalog()
    assert tools[0]['read_only'] is True
    assert tools[1]['read_only'] is False
    if connection.provider.plugin_id == 'apify':
        assert tools[2]['read_only'] is False
    adapter = WebMcpAdapter(connection, SimpleNamespace())
    with pytest.raises(connection.error_type, match='review'):
        adapter.read(operation(connection, changed=True))


def test_exact_inputs_and_grant_revision_are_bound_before_provider_execution(connection):
    connection.use_configured()
    adapter = WebMcpAdapter(connection, SimpleNamespace(approval_store=SimpleNamespace(request=lambda _: {'id': 'fixture-approval'})))
    proposed = operation(connection, changed=True)
    binding = adapter.prepare(proposed)
    changed = proposed.model_copy(update={'arguments': {**proposed.arguments, 'extra': 'changed'}})
    with pytest.raises(connection.error_type, match='changed'):
        adapter.execute(changed, binding=binding, confirmed=True)
    with pytest.raises(connection.error_type, match='confirm'):
        adapter.execute(proposed, binding=binding)
    connection.save({**connection.load(), 'revision': 'replacement-grant'})
    with pytest.raises(connection.error_type, match='changed'):
        adapter.execute(proposed, binding=binding, confirmed=True)


def test_deferred_discovery_keeps_the_original_provider_names_and_schemas(connection):
    connection.use_configured()
    cls = FirecrawlMcpOperation if connection.provider.plugin_id == 'firecrawl' else ApifyMcpOperation
    tools = deferred_tools(lambda: connection, cls, lambda name: 'fixture_' + name.replace('-', '_'))
    catalog = next(item for item in tools if item.name.endswith('_mcp_catalog'))
    result = json.loads(catalog.invoke({}))
    assert result['total'] == len(connection.catalog())
    assert all('input_schema' not in item for item in result['tools'])
    assert all(item['name'] in {tool['name'] for tool in connection.catalog()} for item in result['tools'])


def test_actor_run_is_pending_until_terminal_provider_status(connection):
    if connection.provider.plugin_id != 'apify':
        return
    connection.use_configured()
    async def call(*_, **kwargs):
        return json.dumps({'untrusted_provider_data': True, 'data': {'data': {'runId': 'fixture-run', 'status': 'RUNNING'}}})
    runtime = SimpleNamespace(approval_store=SimpleNamespace(request=lambda _: {'id': 'fixture-approval'}, approve=lambda _: None), call_tool=call)
    adapter = WebMcpAdapter(connection, runtime)
    proposed = operation(connection, changed=True)
    result = adapter.execute(proposed, binding=adapter.prepare(proposed), confirmed=True)
    assert result['pending'] is True and 'before reporting completion' in result['_message']


@pytest.mark.parametrize('name', ['firecrawl', 'apify'])
def test_credentials_cannot_be_forwarded_to_an_unapproved_mcp_endpoint(name):
    from agent.mcp.plugin_runtime import PluginMcpRuntimeError, _connector
    with pytest.raises(PluginMcpRuntimeError, match='official'):
        _connector(name, Path('.'), {'name': name, 'url': 'https://example.com/mcp', 'credential_provider': name})


def test_managed_apify_cannot_use_the_unreviewed_legacy_actor_runner(monkeypatch):
    import asyncio
    from agent.mcp import apify_tools
    monkeypatch.setattr(apify_tools, '_managed_connection', lambda: True)
    monkeypatch.setattr(apify_tools, 'streamablehttp_client', lambda *_args, **_kwargs: pytest.fail('Legacy Actor runner must not execute'))
    result = asyncio.run(apify_tools._run_tool_inner({'query': 'example'}))
    assert json.loads(result)['ok'] is False
