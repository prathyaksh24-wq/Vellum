import asyncio
from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agent.contracts.github_connection import GitHubConnectionRequest, GitHubMcpOperation
from agent.plugins.github_connection import CALLBACK, GitHubConnectionError, GitHubConnectionService
from agent.plugins.github_mcp import GitHubMcpAdapter, cli_operation


class Keyring:
    value = None

    def get_password(self, *_):
        return self.value

    def set_password(self, _service, _account, value):
        self.value = value


READ = {"name": "issue_read", "description": "Read an issue", "read_only": True,
    "input_schema": {"type": "object", "properties": {"method": {"const": "get"}, "owner": {"type": "string"}, "repo": {"type": "string"}, "issue_number": {"type": "integer"}}, "required": ["method", "owner", "repo", "issue_number"]}}
WRITE = {"name": "issue_write", "description": "Change an issue", "read_only": False,
    "input_schema": {"type": "object", "properties": {"method": {"const": "create"}, "owner": {"type": "string"}, "repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}}}, "required": ["method", "owner", "repo", "title"]}}


@pytest.fixture
def service():
    value = GitHubConnectionService(keyring=Keyring(), enabled=lambda: True, clock=lambda: 100,
        settings=lambda: SimpleNamespace(account_github_client_id="fixture-client", account_github_client_secret="fixture-secret"), invalidator=lambda: None)
    value.save({"access_token": "fixture-token", "account_id": "one", "login": "fixture", "access": "manage", "revision": "generation-one", "status": "ready"})
    value.tools, value.tools_revision = [deepcopy(READ), deepcopy(WRITE)], "generation-one"
    return value


def test_oauth_reuses_registered_callback_with_pkce_and_no_secret_in_public_start(service):
    flow = service.start(GitHubConnectionRequest())
    authorization = urlsplit(flow.authorization_url)
    params = parse_qs(authorization.query)
    assert (authorization.scheme, authorization.netloc, authorization.path) == ("https", "github.com", "/login/oauth/authorize")
    assert params["redirect_uri"] == [CALLBACK]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"][0].startswith("github-plugin.")
    assert "fixture-secret" not in flow.model_dump_json()
    assert "fixture-token" not in service.status().model_dump_json()


def test_cancelled_declined_and_replayed_callbacks_preserve_existing_connection(service):
    original = service.load()
    flow = service.start(GitHubConnectionRequest())
    state = parse_qs(urlsplit(flow.authorization_url).query)["state"][0]
    service.callback(state, "", "access_denied")
    assert service.flow_status(flow.flow_id).status == "failed"
    with pytest.raises(GitHubConnectionError):
        service.callback(state, "unused-code")
    assert service.load() == original
    pending = service.start(GitHubConnectionRequest())
    service.cancel(pending.flow_id)
    assert service.flow_status(pending.flow_id).status == "cancelled"
    assert service.load() == original


def test_provider_success_saves_only_after_account_and_mcp_verification(service, monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url))
        return SimpleNamespace(status_code=200, json=lambda: {"access_token": "new-fixture", "scope": "repo"} if method == "POST" else {"id": 9, "login": "signed-in", "name": "Signed In"})
    service.request = request
    monkeypatch.setattr(service, "_catalog", lambda data: [deepcopy(READ), deepcopy(WRITE)])
    flow = service.start(GitHubConnectionRequest())
    service._finish(flow.flow_id, "fixture-code")
    assert service.flow_status(flow.flow_id).status == "connected"
    assert service.load()["login"] == "signed-in"
    assert service.load()["revision"] != "generation-one"
    assert service.status().connected and service.status().mcp_tool_count == 2
    returned = urlsplit(service.return_url(flow.flow_id))
    assert returned.hostname == "127.0.0.1" and parse_qs(returned.query)["github_oauth"] == [flow.flow_id]
    assert calls == [("POST", "https://github.com/login/oauth/access_token"), ("GET", "https://api.github.com/user")]


def test_cli_translation_preserves_labels_and_defers_unrepresentable_fields():
    args = {"method": "create", "owner": "org", "repo": "repo", "title": "Title", "body": "Description", "labels": ["done"]}
    action, translated = cli_operation(GitHubMcpOperation(tool_name="issue_write", arguments=args))
    assert action == "create_issue" and translated["body"] == args["body"] and translated["labels"] == args["labels"]
    assert cli_operation(GitHubMcpOperation(tool_name="issue_write", arguments={**args, "new_provider_field": True})) is None
    assert cli_operation(GitHubMcpOperation(tool_name="issue_read", arguments={"method": "get_comments"})) is None


def test_write_requires_exact_review_and_reconnection_invalidates_it(service, tmp_path):
    from agent.mcp.plugin_approvals import PluginMcpApprovalStore
    runtime = SimpleNamespace(approval_store=PluginMcpApprovalStore(tmp_path / "approvals.db"))
    adapter = GitHubMcpAdapter(service, runtime)
    operation = GitHubMcpOperation(tool_name="issue_write", arguments={"method": "create", "owner": "org", "repo": "repo", "title": "Title", "body": "Description", "labels": ["done"]})
    with pytest.raises(GitHubConnectionError, match="confirm"):
        adapter.execute(operation)
    binding = adapter.prepare(operation)
    assert binding["preview"]["description"] == "Description"
    assert any(field["label"] == "Labels" and "done" in field["value"] for field in binding["preview"]["fields"])
    service.save({**service.load(), "revision": "rotated"})
    service.tools_revision = "rotated"
    with pytest.raises(GitHubConnectionError, match="changed"):
        adapter.execute(operation, binding=binding, confirmed=True)


def test_read_path_cannot_execute_provider_writes(service):
    adapter = GitHubMcpAdapter(service, SimpleNamespace())
    with pytest.raises(GitHubConnectionError, match="changes data"):
        adapter.read(GitHubMcpOperation(tool_name="issue_write", arguments={"method": "create", "owner": "org", "repo": "repo", "title": "Title"}))


def test_ambiguous_cli_write_never_reaches_mcp(service, tmp_path, monkeypatch):
    from agent.mcp.plugin_approvals import PluginMcpApprovalStore
    from agent.plugins import github_mcp
    calls = []
    async def uncertain(*args, **kwargs):
        calls.append("cli")
        return "GitHub CLI failed: the write outcome is unknown. MCP was not called to avoid a duplicate."
    async def forbidden(*args, **kwargs):
        raise AssertionError("An uncertain write was replayed through MCP")
    monkeypatch.setattr(github_mcp.github_cli, "run", uncertain)
    runtime = SimpleNamespace(approval_store=PluginMcpApprovalStore(tmp_path / "approvals.db"), call_tool=forbidden)
    adapter = GitHubMcpAdapter(service, runtime)
    operation = GitHubMcpOperation(tool_name="issue_write", arguments={"method": "create", "owner": "org", "repo": "repo", "title": "Title"})
    binding = adapter.prepare(operation)
    with pytest.raises(GitHubConnectionError, match="outcome is unknown"):
        adapter.execute(operation, binding=binding, confirmed=True)
    assert calls == ["cli"]


def test_backend_error_payload_cannot_become_a_success_receipt():
    from agent.plugins.github_mcp import _verified_result
    for result in ('{"error":"failed"}', '{"untrusted_provider_data":true,"data":{"success":false}}', "Unreachable."):
        with pytest.raises(GitHubConnectionError):
            _verified_result(result)


def test_verified_popup_closes_without_redirecting_the_full_app_into_it(service, monkeypatch):
    from agent.plugins import github_api
    monkeypatch.setattr(github_api, "github_service", lambda: service)
    started = service.start(GitHubConnectionRequest(popup=True))
    service.flows[started.flow_id].update(status="connected", message="Connected to GitHub.")
    response = github_api.oauth_return(started.flow_id)
    assert response.status_code == 200 and "location" not in response.headers
    markup = response.body.decode()
    assert "window.close()" in markup and "window.opener.postMessage" in markup
    assert "window.opener.focus()" in markup
    assert "location.replace" not in markup and '<iframe' not in markup
    assert "script-src 'nonce-" in response.headers["content-security-policy"]


def test_explicit_non_popup_flow_returns_to_the_validated_app(service, monkeypatch):
    from agent.plugins import github_api
    monkeypatch.setattr(github_api, "github_service", lambda: service)
    started = service.start(GitHubConnectionRequest(popup=False))
    service.flows[started.flow_id].update(status="connected", message="Connected to GitHub.")
    response = github_api.oauth_return(started.flow_id)
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.scheme == "http" and target.hostname == "127.0.0.1" and target.port == 5173


@pytest.mark.parametrize('flow_id', [
    '</script><script>alert("oauth")</script>',
    '\"><img src=x onerror=alert(1)>',
    '&quot; onload=alert(1) data-flow-id="',
    '\u2028\u2029',
])
def test_popup_values_are_inert_html_data_not_javascript(service, monkeypatch, flow_id):
    from html.parser import HTMLParser
    from agent.plugins import github_api

    class Page(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags, self.body, self.scripts = [], {}, []
            self.in_script = False

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)
            if tag == 'body':
                self.body = dict(attrs)
            if tag == 'script':
                self.in_script = True
                self.scripts.append('')

        def handle_endtag(self, tag):
            if tag == 'script':
                self.in_script = False

        def handle_data(self, value):
            if self.in_script:
                self.scripts[-1] += value

    monkeypatch.setattr(github_api, 'github_service', lambda: service)
    started = service.start(GitHubConnectionRequest(popup=True))
    # Generated IDs are URL-safe. Seed hostile stored data to exercise the HTML
    # boundary independently of today's token generator and flow lookup guard.
    service.flows[flow_id] = service.flows.pop(started.flow_id)
    service.flows[flow_id].update(status='connected', message='<img src=x onerror=alert(2)>')
    response = github_api.oauth_return(flow_id)
    page = Page()
    page.feed(response.body.decode())
    assert response.status_code == 200
    assert page.body['data-flow-id'] == flow_id
    assert page.body['data-target-origin'] == 'http://127.0.0.1:5173'
    assert len(page.scripts) == 1 and 'img' not in page.tags
    assert set(page.body) == {'data-flow-id', 'data-target-origin'}
    assert flow_id not in page.scripts[0]
    assert 'window.opener.postMessage' in page.scripts[0]
    assert 'window.opener.focus()' in page.scripts[0] and 'window.close()' in page.scripts[0]


def test_desktop_launch_route_uses_the_existing_flow_and_rejects_unknown_ids(service, monkeypatch):
    from agent.plugins import github_api
    monkeypatch.setattr(github_api, "github_service", lambda: service)
    started = service.start(GitHubConnectionRequest())
    response = github_api.oauth_open(started.flow_id)
    assert response.status_code == 303
    assert response.headers["location"] == started.authorization_url
    assert github_api.oauth_open("unknown-flow").status_code == 400


def test_pending_popup_keeps_polling_and_unknown_return_is_static(service, monkeypatch):
    from agent.plugins import github_api
    monkeypatch.setattr(github_api, 'github_service', lambda: service)
    started = service.start(GitHubConnectionRequest(popup=True))
    response = github_api.oauth_return(started.flow_id)
    assert response.status_code == 200 and response.headers['refresh'] == '1'
    assert '<script' not in response.body.decode()
    assert 'target="_blank" rel="noopener noreferrer"' in response.body.decode()
    unknown = github_api.oauth_return('</script><script>alert(1)</script>')
    assert unknown.status_code == 400 and '<script' not in unknown.body.decode()
