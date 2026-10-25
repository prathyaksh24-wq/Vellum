import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.slack import SlackAppRegistration, SlackMcpOperation, SlackOAuthRequest
from agent.plugins.slack import CALLBACK, SCOPES, SERVER, TOKEN, SlackError, SlackService
from agent.plugins.slack_mcp import SlackMcpAdapter, verified_result


READ = {"name": "slack_read_channel", "description": "Read Slack history", "read_only": True,
    "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}}, "required": ["channel"], "additionalProperties": False}}
WRITE = {"name": "slack_send_message", "description": "Send a Slack message", "read_only": False,
    "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel", "text"], "additionalProperties": False}}


class Keyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        if len(value.encode('utf-16-le')) > 2560:
            raise ValueError('Windows credential blob too large')
        self.values[service, account] = value

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


@pytest.fixture
def service():
    def request(method, url, **kwargs):
        assert method == "POST" and kwargs["follow_redirects"] is False
        if url == TOKEN:
            value = {"ok": True, "access_token": "fixture-user-token", "refresh_token": "fixture-refresh", "token_type": "user", "expires_in": 43200, "scope": SCOPES}
        else:
            assert url == "https://slack.com/api/auth.test"
            value = {"ok": True, "user_id": "U12345678", "user": "Fixture", "team_id": "T12345678", "team": "Workspace"}
        return SimpleNamespace(status_code=200, json=lambda: value)

    class Transport:
        async def list_tools(self, connector):
            assert connector.url == SERVER
            return [READ, WRITE]

    value = SlackService(keyring=Keyring(), enabled=lambda: True, clock=lambda: 100, request=request, transport=Transport(), invalidator=lambda: None)
    value.configure(SlackAppRegistration(app_id="A12345678", client_id="12345678.12345678"))
    return value


def connect(service):
    started = service.start(SlackOAuthRequest())
    service._finish(started.flow_id, "fixture-code")
    assert service.flow_status(started.flow_id).status == "connected"
    return started


def test_setup_manifest_matches_the_real_callback_and_complete_scope_set():
    source = Path(__file__).resolve().parents[2] / 'plugins/connectors/slack/slack-app-manifest.json'
    manifest = json.loads(source.read_text())
    assert manifest['oauth_config']['redirect_urls'] == [CALLBACK]
    assert manifest['oauth_config']['pkce_enabled'] is True
    assert manifest['settings']['is_mcp_enabled'] is True
    assert set(manifest['oauth_config']['scopes']['user']) == set(SCOPES.split())
    assert 'bot' not in manifest['oauth_config']['scopes']


def test_oauth_is_user_scoped_pkce_with_no_client_secret_or_token_in_start(service):
    flow = service.start(SlackOAuthRequest())
    url = urlsplit(flow.authorization_url)
    params = parse_qs(url.query)
    assert url.scheme + '://' + url.netloc + url.path == 'https://slack.com/oauth/v2_user/authorize'
    assert params['redirect_uri'] == [CALLBACK]
    assert params['code_challenge_method'] == ['S256']
    assert set(params['scope'][0].split()) == set(SCOPES.split())
    assert 'client_secret' not in params and 'user_scope' not in params
    assert service.flows[flow.flow_id]['verifier'] not in flow.model_dump_json()


def test_real_account_and_full_catalog_must_verify_before_connected(service):
    assert service.status().configured is False
    connect(service)
    status = service.status()
    assert status.connected and status.workspace_name == 'Workspace' and status.account_name == 'Fixture'
    assert status.mcp_tool_count == 2 and len(status.granted_scopes) == 30
    assert 'fixture-user-token' not in status.model_dump_json()
    assert 'fixture-refresh' not in status.model_dump_json()


def test_rejected_catalog_and_stale_or_cancelled_signin_preserve_previous_grant(service):
    connect(service)
    original = service.load()
    flow = service.start(SlackOAuthRequest())
    service.cancel(flow.flow_id)
    service._finish(flow.flow_id, 'fixture-code')
    assert service.load() == original
    assert service.flow_status(flow.flow_id).status == 'cancelled'
    with pytest.raises(SlackError):
        service.callback(service.flows[flow.flow_id]['state'], 'fixture-code')

    class Rejected:
        async def list_tools(self, *_):
            raise RuntimeError('provider secret must not escape')

    service.transport = Rejected()
    failed = service.start(SlackOAuthRequest())
    service._finish(failed.flow_id, 'fixture-code')
    assert service.load() == original
    assert service.flow_status(failed.flow_id).status == 'failed'
    assert 'provider secret' not in service.flow_status(failed.flow_id).message


def test_refresh_rotates_credentials_without_changing_account_bound_revision(service):
    connect(service)
    original = service.load()
    calls = []
    def request(method, url, **kwargs):
        calls.append((url, kwargs['data']))
        return SimpleNamespace(status_code=200, json=lambda: {'ok': True, 'access_token': 'new-fixture-token', 'refresh_token': 'new-fixture-refresh', 'token_type': 'user', 'expires_in': 43200})
    service.save({**original, 'expires_at': 101})
    service.request = request
    current = service.require()
    assert current['access_token'] == 'new-fixture-token' and current['revision'] == original['revision']
    assert calls == [(TOKEN, {'grant_type': 'refresh_token', 'client_id': original['app']['client_id'], 'refresh_token': original['refresh_token']})]
    service.require()
    assert len(calls) == 1


def test_unknown_callback_and_decline_do_not_overwrite_saved_authorization(service):
    connect(service)
    original = service.load()
    flow = service.start(SlackOAuthRequest())
    with pytest.raises(SlackError):
        service.callback('unknown-state', 'fixture-code')
    service.callback(service.flows[flow.flow_id]['state'], '', 'access_denied')
    assert service.load() == original and service.flow_status(flow.flow_id).status == 'failed'
    assert 'verifier' not in service.flows[flow.flow_id]


def test_read_path_cannot_send_a_message_and_arguments_must_match_published_schema(service):
    connect(service)
    adapter = SlackMcpAdapter(service, SimpleNamespace())
    with pytest.raises(SlackError, match='changes data'):
        adapter.read(SlackMcpOperation(tool_name=WRITE['name'], arguments={'channel': 'C123', 'text': 'Hello'}))
    with pytest.raises(SlackError, match='published schema'):
        adapter.tool(SlackMcpOperation(tool_name=READ['name'], arguments={'wrong': True}))


def test_reviews_bind_message_account_workspace_revision_and_schema(service, tmp_path):
    from agent.mcp.plugin_approvals import PluginMcpApprovalStore
    connect(service)
    adapter = SlackMcpAdapter(service, SimpleNamespace(approval_store=PluginMcpApprovalStore(tmp_path / 'approvals.db')))
    operation = SlackMcpOperation(tool_name=WRITE['name'], arguments={'channel': 'C123', 'text': 'Hello team'})
    binding = adapter.prepare(operation)
    assert binding['preview']['description'] == 'Hello team' and binding['preview']['workspace'] == 'Workspace'
    changed = operation.model_copy(update={'arguments': {'channel': 'C123', 'text': 'Changed'}})
    with pytest.raises(SlackError, match='changed'):
        adapter.execute(changed, binding=binding, confirmed=True)
    service.save({**service.load(), 'workspace_id': 'TOTHER'})
    with pytest.raises(SlackError, match='changed'):
        adapter.execute(operation, binding=binding, confirmed=True)


@pytest.mark.parametrize('result', ['{"ok":false}', '{"untrusted_provider_data":true,"data":{"error":"failed"}}', 'Unreachable.'])
def test_slack_errors_cannot_be_success_receipts(result):
    with pytest.raises(SlackError):
        verified_result(result)


def test_slack_credentials_are_pinned_to_the_official_endpoint(service, monkeypatch):
    from agent.mcp.plugin_runtime import PluginMcpRuntimeError, _connector
    from agent.plugins import slack
    monkeypatch.setattr(slack, 'slack_service', lambda: service)
    with pytest.raises(PluginMcpRuntimeError):
        _connector('slack', Path('.'), {'name': 'slack', 'url': 'https://example.com/mcp', 'credential_provider': 'slack'})


def test_disconnect_removes_grant_but_preserves_public_app_registration(service):
    connect(service)
    app = service.load()['app']
    assert not service.disconnect().configured
    assert service.load() == {'app': app} and service.cached_tools() == []


def test_popup_return_preserves_close_focus_origin_and_inert_data(service, monkeypatch):
    from html.parser import HTMLParser
    from agent.plugins import slack_api

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.body, self.tags = {}, []

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)
            if tag == 'body':
                self.body = dict(attrs)

    monkeypatch.setattr(slack_api, 'slack_service', lambda: service)
    flow = service.start(SlackOAuthRequest())
    pending = slack_api.oauth_return(flow.flow_id)
    assert pending.headers['refresh'] == '1' and '<script' not in pending.body.decode()
    hostile = '</script><img src=x onerror=alert(1)>'
    service.flows[hostile] = service.flows.pop(flow.flow_id)
    service.flows[hostile].update(status='connected', message='<script>alert(2)</script>')
    response = slack_api.oauth_return(hostile)
    page = Page()
    page.feed(response.body.decode())
    assert page.body['data-flow-id'] == hostile and page.body['data-target-origin'] == 'http://127.0.0.1:5173'
    assert page.tags.count('script') == 1 and 'img' not in page.tags
    assert 'window.opener.postMessage' in response.body.decode() and 'window.close()' in response.body.decode()
    assert "script-src 'nonce-" in response.headers['content-security-policy']
    assert slack_api.oauth_return('unknown').status_code == 400


def test_non_popup_return_and_launch_keep_the_registered_destinations(service, monkeypatch):
    from agent.plugins import slack_api
    monkeypatch.setattr(slack_api, 'slack_service', lambda: service)
    flow = service.start(SlackOAuthRequest(popup=False))
    assert slack_api.oauth_open(flow.flow_id).headers['location'] == flow.authorization_url
    service.flows[flow.flow_id].update(status='connected')
    result = slack_api.oauth_return(flow.flow_id)
    assert result.status_code == 303 and urlsplit(result.headers['location']).port == 5173


def test_mcp_diagnostic_unwraps_http_failures_without_provider_secrets():
    import httpx
    from agent.plugins.slack import catalog_failure
    request = httpx.Request('POST', SERVER, headers={'Authorization': 'Bearer fixture-private-token'})
    response = httpx.Response(403, json={'error': 'app_not_mcp_enabled', 'private': 'fixture-private-token'}, request=request)
    error = httpx.HTTPStatusError('provider text with fixture-private-token', request=request, response=response)
    code, message = catalog_failure(ExceptionGroup('transport failure', [error]))
    assert code == 'app_not_mcp_enabled' and 'Agents' in message
    assert 'fixture-private-token' not in code + message
    unknown = httpx.Response(401, json={'error': 'fixture-private-token'}, request=request)
    code, message = catalog_failure(httpx.HTTPStatusError('fixture-private-token', request=request, response=unknown))
    assert code == 'mcp_http_401' and 'fixture-private-token' not in message


def test_catalog_diagnostic_distinguishes_timeout_client_and_schema_errors(service):
    from agent.plugins.slack import catalog_failure
    assert catalog_failure(ExceptionGroup('wrapper', [TimeoutError('private')]))[0] == 'mcp_timeout'
    assert catalog_failure(TypeError('private'))[0] == 'mcp_client_error'

    class InvalidCatalog:
        async def list_tools(self, *_):
            return [{'name': 'invalid/name', 'description': 'private', 'read_only': True, 'input_schema': {}}]

    service.transport = InvalidCatalog()
    with pytest.raises(SlackError, match='mcp_catalog_validation'):
        service._catalog({'access_token': 'fixture-private-token'})


def test_large_authorization_roundtrips_through_windows_sized_os_entries(service):
    from agent.plugins.slack import KEYRING_SERVICE, KEYRING_ACCOUNT
    value = {**service.load(), 'access_token': 'fixture-access-' * 500, 'refresh_token': 'fixture-refresh-' * 500,
        'account_name': '\\"\u2028\u0c95' * 200}
    service.save(value)
    assert service.load() == value
    assert all(len(part.encode('utf-16-le')) <= 2560 for part in service.keyring.values.values())
    pointer = json.loads(service.keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT))
    assert pointer['parts'] > 1 and 'access_token' not in pointer
    old_services = {key[0] for key in service.keyring.values if '.part.' in key[0]}
    service.save({'app': value['app']})
    assert service.load() == {'app': value['app']}
    assert not old_services.intersection(key[0] for key in service.keyring.values)


def test_failed_partial_os_write_keeps_previous_record_and_cleans_staging(service, monkeypatch):
    before, entries = service.load(), dict(service.keyring.values)
    original = service.keyring.set_password
    writes = 0
    def fail(service_name, account, value):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError('fixture storage failure')
        original(service_name, account, value)
    monkeypatch.setattr(service.keyring, 'set_password', fail)
    with pytest.raises(SlackError, match='credential store'):
        service.save({**before, 'access_token': 'fixture-' * 1000})
    assert service.load() == before and service.keyring.values == entries


def test_incomplete_record_fails_closed_and_legacy_registration_still_loads(service):
    from agent.plugins.slack import KEYRING_SERVICE, KEYRING_ACCOUNT
    app = service.load()
    service.keyring.values = {(KEYRING_SERVICE, KEYRING_ACCOUNT): json.dumps(app)}
    assert service.load() == app
    service.save(app)
    pointer = json.loads(service.keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT))
    service.keyring.delete_password(service._part_service(pointer['generation'], 0), KEYRING_ACCOUNT)
    with pytest.raises(SlackError, match='credential store'):
        service.load()


@pytest.mark.parametrize('commit_before_error', [False, True])
def test_root_write_error_preserves_the_record_that_actually_committed(service, monkeypatch, commit_before_error):
    from agent.plugins.slack import KEYRING_SERVICE
    before = service.load()
    original = service.keyring.set_password
    def fail(service_name, account, value):
        if service_name == KEYRING_SERVICE:
            if commit_before_error:
                original(service_name, account, value)
            raise OSError('fixture root write failure')
        original(service_name, account, value)
    monkeypatch.setattr(service.keyring, 'set_password', fail)
    after = {**before, 'access_token': 'fixture-access'}
    if commit_before_error:
        service.save(after)
        assert service.load() == after
    else:
        with pytest.raises(SlackError):
            service.save(after)
        assert service.load() == before
