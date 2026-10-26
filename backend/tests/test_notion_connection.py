"""Provider boundaries and exact-input Notion reviews; no external accounts."""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.notion import NotionMcpOperation, NotionOAuthRequest
from agent.plugins.notion import NotionError, NotionService, CALLBACK, REGISTER, SCOPES, TOKEN


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


TOOLS = [
    {'name': 'notion-search', 'description': 'Search the connected Notion workspace', 'read_only': True,
     'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'notion-create-pages', 'description': 'Create pages in the selected parent', 'read_only': False,
     'input_schema': {'type': 'object', 'properties': {'parent': {'type': 'object', 'properties': {'page_id': {'type': 'string'}}, 'required': ['page_id']}, 'pages': {'type': 'array'}},
                      'required': ['parent', 'pages'], 'additionalProperties': False}},
]


@pytest.fixture
def service():
    def request(method, url, **kwargs):
        if url == REGISTER:
            assert method == 'POST' and kwargs['json']['token_endpoint_auth_method'] == 'none'
            value = {'client_id': 'fixture-client', 'redirect_uris': [CALLBACK], 'token_endpoint_auth_method': 'none'}
        elif url == TOKEN:
            value = {'access_token': 'fixture-private-access', 'refresh_token': 'fixture-private-refresh',
                     'expires_in': 3600, 'token_type': 'Bearer '}
        else:
            raise AssertionError('Notion credentials must never be sent to a separate REST endpoint')
        return SimpleNamespace(status_code=200, json=lambda: value)

    class Transport:
        async def call_tool(self, connector, name, arguments):
            assert name == 'notion-get-self' and arguments == {}
            return json.dumps({'user': {'id': 'fixture-user-0123456789', 'name': 'Fixture person', 'type': 'person'}, 'workspace': {'id': 'fixture-workspace-0123456789', 'name': 'Fixture workspace'}})

        async def list_tools(self, connector):
            assert connector.url == 'https://mcp.notion.com/mcp'
            return TOOLS

    return NotionService(keyring=Keyring(), request=request, transport=Transport(),
                          enabled=lambda: True, clock=lambda: 1000, invalidator=lambda: None)


def connect(service):
    flow = service.start(NotionOAuthRequest())
    service._finish(flow.flow_id, 'fixture-code')
    assert service.flow_status(flow.flow_id).status == 'connected'
    return service.load()


def test_dcr_and_pkce_register_only_the_public_loopback_client(service):
    flow = service.start(NotionOAuthRequest())
    url = urlsplit(flow.authorization_url)
    args = parse_qs(url.query)
    assert url.scheme == 'https' and url.netloc == 'mcp.notion.com' and url.path == '/authorize'
    assert args['redirect_uri'] == [CALLBACK] and args['code_challenge_method'] == ['S256']
    assert args['scope'][0].split() == SCOPES.split()
    assert args['resource'] == ['https://mcp.notion.com']
    assert 'code_verifier' not in args and 'client_secret' not in args
    assert not service.status().configured


def test_ready_requires_verified_identity_and_complete_live_catalog(service):
    data = connect(service)
    status = service.status()
    assert status.connected and status.mcp_tool_count == 2
    assert status.account_name == 'Fixture person' and len(status.granted_scopes) == 1
    assert 'fixture-private' not in status.model_dump_json()
    assert service.cached_tools() == TOOLS
    assert all(len(value.encode('utf-16-le')) <= 2560 for value in service.keyring.values.values())
    assert data['access_token'] == 'fixture-private-access'


def test_cancelled_or_superseded_signin_cannot_replace_existing_grant(service):
    original = connect(service)
    flow = service.start(NotionOAuthRequest())
    service.cancel(flow.flow_id)
    service._finish(flow.flow_id, 'fixture-code')
    assert service.load() == original and service.flow_status(flow.flow_id).status == 'cancelled'
    old = service.start(NotionOAuthRequest())
    service.start(NotionOAuthRequest())
    with pytest.raises(NotionError):
        service.callback('unknown-state', 'fixture-code')
    service._finish(old.flow_id, 'fixture-code')
    assert service.load() == original


def test_failed_catalog_preserves_previous_connection_without_provider_error_text(service):
    original = connect(service)
    class Broken:
        async def call_tool(self, *_):
            return json.dumps({'user': {'id': 'fixture-user-0123456789', 'name': 'Fixture person', 'type': 'person'}, 'workspace': {'id': 'fixture-workspace-0123456789', 'name': 'Fixture workspace'}})

        async def list_tools(self, *_):
            raise TypeError('fixture-private-provider-body')
    service.transport = Broken()
    flow = service.start(NotionOAuthRequest())
    service._finish(flow.flow_id, 'fixture-code')
    status = service.flow_status(flow.flow_id)
    assert status.status == 'failed' and 'mcp_client_error' in status.message
    assert 'fixture-private' not in status.message and service.load() == original


def test_refresh_rotation_preserves_review_revision_and_does_not_retry(service):
    original = connect(service)
    service.clock = lambda: 5000
    calls = []
    def refresh(method, url, **kwargs):
        calls.append((url, kwargs['data']))
        return SimpleNamespace(status_code=200, json=lambda: {'access_token': 'rotated-access',
            'refresh_token': 'rotated-refresh', 'token_type': 'Bearer', 'expires_in': 3600})
    service.request = refresh
    data = service.require()
    assert data['revision'] == original['revision'] and data['refresh_token'] == 'rotated-refresh'
    assert len(calls) == 1 and calls[0][1]['grant_type'] == 'refresh_token'
    assert service.require() == data and len(calls) == 1


def test_reads_cannot_execute_writes_and_review_is_bound_to_exact_inputs(service):
    from agent.plugins.notion_mcp import NotionMcpAdapter
    connect(service)
    runtime = SimpleNamespace(approval_store=SimpleNamespace(request=lambda _: {'id': 'fixture-approval'}))
    adapter = NotionMcpAdapter(service, runtime)
    operation = NotionMcpOperation(tool_name='notion-create-pages', arguments={'parent': {'page_id': 'fixture-parent-0123456789'}, 'pages': []})
    with pytest.raises(NotionError, match='changes data'):
        adapter.read(operation)
    with pytest.raises(NotionError, match='confirm'):
        adapter.execute(operation)
    binding = adapter.prepare(operation)
    assert binding['preview']['provider'] == 'Notion' and binding['preview']['workspace'] == 'Fixture workspace'
    changed = operation.model_copy(update={'arguments': {'parent': {'page_id': 'fixture-other-parent-0123456789'}, 'pages': []}})
    with pytest.raises(NotionError, match='changed'):
        adapter.execute(changed, binding=binding, confirmed=True)
    service.save({**service.load(), 'revision': 'a-new-authorization'})
    with pytest.raises(NotionError, match='changed'):
        adapter.execute(operation, binding=binding, confirmed=True)


def test_credentials_are_pinned_to_official_endpoint_before_loading(monkeypatch):
    from agent.mcp.plugin_runtime import PluginMcpRuntimeError, _connector
    from agent.plugins import notion
    monkeypatch.setattr(notion, 'notion_service', lambda: pytest.fail('must not load credentials'))
    with pytest.raises(PluginMcpRuntimeError, match='official'):
        _connector('notion', Path('.'), {'name': 'notion', 'url': 'https://example.com/mcp', 'credential_provider': 'notion'})


def test_provider_failures_never_become_success_receipts():
    from agent.plugins.notion_mcp import verified_result
    for result in ('Unreachable.', '{"error":"denied"}', '{"success":false}', '{"isError":true}'):
        with pytest.raises(NotionError):
            verified_result(result)


def test_disconnect_clears_local_authorization_and_tool_cache(service):
    client_id = connect(service)['client_id']
    assert not service.disconnect().configured
    assert service.load() == {'client_id': client_id} and service.cached_tools() == []


def test_notion_hyphenated_tools_have_safe_model_names_without_changing_provider_names(service):
    from agent.plugins.notion import tool_name
    connect(service)
    assert service.catalog()[0]['name'] == 'notion-search'
    assert tool_name('notion-create-pages') == 'notion_tool_notion_create_pages'


def test_workspace_switch_invalidates_prepared_write_even_for_the_same_person(service):
    from agent.plugins.notion_mcp import NotionMcpAdapter
    connect(service)
    runtime = SimpleNamespace(approval_store=SimpleNamespace(request=lambda _: {'id': 'fixture-approval'}))
    adapter = NotionMcpAdapter(service, runtime)
    operation = NotionMcpOperation(tool_name='notion-create-pages', arguments={'parent': {'page_id': 'fixture-parent-0123456789'}, 'pages': []})
    binding = adapter.prepare(operation)
    service.save({**service.load(), 'workspace_id': 'fixture-different-workspace'})
    with pytest.raises(NotionError, match='changed'):
        adapter.execute(operation, binding=binding, confirmed=True)


def test_async_write_is_pending_until_provider_completion(service):
    from agent.plugins.notion_mcp import NotionMcpAdapter
    connect(service)
    async def call(*_, **kwargs):
        return json.dumps({'untrusted_provider_data': True, 'data': {'async_task': {'id': 'fixture-task'}}})
    runtime = SimpleNamespace(
        approval_store=SimpleNamespace(request=lambda _: {'id': 'fixture-approval'}, approve=lambda _: None),
        call_tool=call,
    )
    adapter = NotionMcpAdapter(service, runtime)
    operation = NotionMcpOperation(tool_name='notion-create-pages', arguments={'parent': {'page_id': 'fixture-parent-0123456789'}, 'pages': []})
    result = adapter.execute(operation, binding=adapter.prepare(operation), confirmed=True)
    assert result['pending'] is True and result['task_id'] == 'fixture-task'
    assert 'before reporting completion' in result['_message']


def test_rejected_refresh_is_not_replayed_by_subsequent_tool_calls(service):
    connect(service)
    service.clock = lambda: 5000
    attempts = []
    def rejected(method, url, **kwargs):
        attempts.append(url)
        return SimpleNamespace(status_code=400, json=lambda: {'error': 'invalid_grant'})
    service.request = rejected
    for _ in range(2):
        with pytest.raises(NotionError, match='Reconnect'):
            service.require()
    assert len(attempts) == 1 and not service.status().connected


def test_record_review_shows_nested_field_values_without_raw_json():
    from agent.plugins.notion_mcp import review_fields
    fields = review_fields({'records': [{'fields': {'Title': 'Ship Vellum', 'Done': True}}]})
    assert fields == [
        {'label': 'Records · 1 · Fields · Title', 'value': 'Ship Vellum'},
        {'label': 'Records · 1 · Fields · Done', 'value': 'Yes'},
    ]


def test_popup_return_uses_inert_data_and_restores_original_app(service, monkeypatch):
    from agent.plugins import notion_api
    monkeypatch.setattr(notion_api, 'notion_service', lambda: service)
    flow = service.start(NotionOAuthRequest())
    assert notion_api.oauth_return(flow.flow_id).headers['refresh'] == '1'
    service.flows[flow.flow_id].update(status='connected', message='<script>untrusted</script>')
    response = notion_api.oauth_return(flow.flow_id)
    page = response.body.decode()
    assert '<script>untrusted</script>' not in page and '&lt;script&gt;' in page
    assert 'window.close()' in page and 'window.opener.focus()' in page
    assert 'data-target-origin="http://127.0.0.1:5173"' in page
    assert "script-src 'nonce-" in response.headers['content-security-policy']
