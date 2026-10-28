"""Swiggy local OAuth, shared selection and service-specific tool routing."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.swiggy_connection import SwiggyOAuthRequest, SwiggySelection, SwiggyMcpOperation
from agent.plugins.swiggy_connection import SwiggyService, SwiggyError, CALLBACK, SERVERS


class Keyring:
    def __init__(self): self.values = {}
    def get_password(self, service, account): return self.values.get((service, account))
    def set_password(self, service, account, value): self.values[(service, account)] = value
    def delete_password(self, service, account): self.values.pop((service, account), None)


@pytest.fixture
def connection():
    calls = []
    def request(method, url, **kwargs):
        calls.append((url, kwargs))
        assert 'data' not in kwargs
        if url.endswith('/register'):
            assert kwargs['json']['redirect_uris'] == [CALLBACK]
            return SimpleNamespace(status_code=200, json=lambda: {'client_id': 'vellum-fixture', 'token_endpoint_auth_method': 'none', 'redirect_uris': [CALLBACK]})
        assert url == 'https://mcp.swiggy.com/auth/token'
        return SimpleNamespace(status_code=200, json=lambda: {'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh', 'token_type': 'Bearer', 'expires_in': 432000})
    class Transport:
        async def list_tools(self, connector):
            assert connector.url == SERVERS[connector.name]
            return [{'name': name, 'description': name, 'input_schema': {'type': 'object', 'properties': {}}, 'read_only': True}
                for name in ['get_addresses', 'checkout']]
    current = SwiggyService(keyring=Keyring(), enabled=lambda: True, request=request, transport=Transport(), clock=lambda: 1000, invalidator=lambda: None)
    current.calls = calls
    return current


def authorize(connection):
    flow = connection.start(SwiggyOAuthRequest())
    connection._finish(flow.flow_id, 'fixture-code')
    assert connection.flow_status(flow.flow_id).status == 'connected'
    return flow


def test_local_oauth_uses_pkce_and_json_with_one_registration(connection):
    flow = authorize(connection)
    query = parse_qs(urlsplit(flow.authorization_url).query)
    assert query['redirect_uri'] == ['http://localhost:8000/api/plugins/swiggy/oauth/callback']
    assert query['code_challenge_method'] == ['S256']
    assert query['scope'] == ['mcp:tools mcp:resources mcp:prompts']
    assert connection.status().mcp_tool_count == 4
    assert sum(url.endswith('/register') for url, _ in connection.calls) == 1
    assert 'fixture-access' not in connection.status().model_dump_json()


def test_same_named_tools_are_qualified_and_mutations_are_reviewed(connection):
    authorize(connection)
    tools = connection.catalog()
    assert {item['name'] for item in tools} == {'food__get_addresses', 'food__checkout', 'instamart__get_addresses', 'instamart__checkout'}
    assert all(not item['read_only'] for item in tools if item['original_name'] == 'checkout')
    assert [item['name'] for item in connection.tools_for('instamart')] == ['get_addresses', 'checkout']


def test_service_selection_preserves_grant_and_invalidates_old_reviews(connection):
    authorize(connection)
    before = connection.load()
    connection.configure(SwiggySelection(services=['food']))
    assert connection.load()['access_token'] == before['access_token']
    assert connection.load()['revision'] != before['revision']
    assert all(item['service'] == 'food' for item in connection.catalog())
    with pytest.raises(SwiggyError, match='Enable'):
        connection.connector_for(connection.require(), 'instamart')
    connection.configure(SwiggySelection(services=[]))
    assert not connection.status().connected and connection.status().status == 'disabled'
    with pytest.raises(SwiggyError, match='Select'):
        connection.start(SwiggyOAuthRequest())


def test_refresh_rotation_and_terminal_invalid_grant(connection):
    authorize(connection)
    connection.clock = lambda: 434000
    def rejected(method, url, **kwargs):
        assert kwargs['json']['grant_type'] == 'refresh_token'
        return SimpleNamespace(status_code=400, json=lambda: {'error': 'invalid_grant'})
    connection.request = rejected
    with pytest.raises(SwiggyError, match='refresh'):
        connection.require()
    assert connection.load()['refresh_rejected'] is True


def test_instamart_read_uses_its_exact_connector_and_original_name(connection):
    from agent.plugins.swiggy_mcp import SwiggyMcpAdapter
    authorize(connection)
    calls = []
    class Runtime:
        async def call_tool(self, *args, **kwargs):
            calls.append(args)
            return json.dumps({'success': True, 'data': {}})
    adapter = SwiggyMcpAdapter(connection, Runtime())
    adapter.read(SwiggyMcpOperation(tool_name='instamart__get_addresses'))
    assert calls == [('swiggy', 'instamart', 'get_addresses', {})]


def test_changed_cart_cannot_reuse_checkout_confirmation(connection, monkeypatch):
    from agent.plugins.swiggy_mcp import SwiggyMcpAdapter
    from agent.plugins.web_mcp_actions import WebMcpAdapter
    adapter = SwiggyMcpAdapter(connection, SimpleNamespace())
    monkeypatch.setattr(WebMcpAdapter, 'prepare', lambda *args: {'preview': {'fields': []}})
    snapshot = {'service': 'instamart', 'amount': '10', 'items': [{'id': 'fixture', 'quantity': 1}], 'paymentMethod': 'Cash', 'delivery': 'Selected address'}
    monkeypatch.setattr(adapter, 'cart', lambda operation: dict(snapshot))
    operation = SwiggyMcpOperation(tool_name='instamart__checkout', arguments={'addressId': 'addr_fixture'})
    binding = adapter.prepare(operation)
    snapshot['amount'] = '12'
    with pytest.raises(SwiggyError, match='changed'):
        adapter.execute(operation, binding=binding, confirmed=True)
