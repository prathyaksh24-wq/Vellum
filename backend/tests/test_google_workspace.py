from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.contracts.google_workspace import GoogleSelection
from agent.plugins.google_calendar_runtime import google_calendar_plugin, google_calendar_scopes
from agent.plugins.google_workspace import GoogleError, GoogleWorkspaceService, SERVICES
from agent.plugins.registry import PluginRegistry


class Keyring:
    def __init__(self):
        self.values = {}
    def get_password(self, service, account):
        return self.values.get((service, account))
    def set_password(self, service, account, value):
        self.values[(service, account)] = value
    def delete_password(self, service, account):
        self.values.pop((service, account), None)


@pytest.fixture
def service(tmp_path):
    root = tmp_path / "plugins"
    for identifier in ["google-workspace", *[spec["plugin_id"] for spec in SERVICES.values()]]:
        folder = root / identifier
        folder.mkdir(parents=True)
        (folder / "plugin.yaml").write_text(f"id: {identifier}\nname: {identifier}\ntype: connector\ncategory: Connectors\ndefault_enabled: false\n")
    registry = PluginRegistry(root, state_path=tmp_path / "state.json")
    registry.set_enabled("google-workspace", True)
    store = google_calendar_plugin().module.auth.GoogleCalendarAuthStore(tmp_path / "auth", keyring_backend=Keyring(), clock=lambda: 1000)
    def forbid(*args, **kwargs):
        raise AssertionError("Unexpected external request")
    return GoogleWorkspaceService(store=store, registry=registry, credentials=lambda: ("client", "client-secret"), request=forbid, clock=lambda: 1000)


def grant(service, scopes):
    service.store.save_tokens({"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_at": 2000, "scope": " ".join(scopes)})


def test_agent_mail_read_returns_bounded_readable_messages_in_one_round(service):
    import base64
    grant(service,SERVICES['gmail']['scopes'])
    service.registry.set_enabled('gmail',True)
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        if url.endswith('/messages'):
            assert kwargs['params']['maxResults']==20
            return httpx.Response(200,json={'messages':[{'id':f'mail-{n}'} for n in range(7)],'nextPageToken':'next-fixture'})
        return httpx.Response(200,json={'id':'mail-1','snippet':'Fixture preview','payload':{'headers':[{'name':'Subject','value':'Fixture subject'}],'mimeType':'text/plain','body':{'data':base64.urlsafe_b64encode(('Fixture body '*1000).encode()).decode()}}})
    service.request=request
    result=service.read_mail(query='after:100',limit=20)
    message=result['result']['messages'][0]
    assert message['headers']['Subject']=='Fixture subject' and message['text'].startswith('Fixture body')
    assert message['truncated'] and len(message['text'])<=1500
    assert result['result']['nextPageToken']=='next-fixture' and result['result']['partial']
    assert len(result['result']['messages'])==7 and result['result']['limit']==20
    assert all(method=='GET' for method,_,_ in calls) and len(calls)==8


def test_selection_requests_only_selected_services_with_pkce(service):
    result = service.configure(GoogleSelection(services=["gmail", "drive"]))
    query = parse_qs(urlsplit(result["flow"]["authorization_url"]).query)
    assert query["client_id"] == ["client"]
    assert query["code_challenge_method"] == ["S256"]
    assert "gmail.readonly" in query["scope"][0]
    assert "drive.readonly" in query["scope"][0]
    assert "calendar.events" not in query["scope"][0]
    assert "contacts.readonly" not in query["scope"][0]
    assert "client-secret" not in str(result)
    assert not service.registry.is_enabled("gmail")


def test_desktop_install_opens_generated_google_url_and_reports_launch(service):
    opened = []
    service.opener = lambda url: opened.append(url) or True
    flow = service.configure(GoogleSelection(services=["gmail"], open_browser=True))["flow"]
    assert opened == [flow["authorization_url"]]
    assert urlsplit(opened[0]).netloc == "accounts.google.com"
    assert flow["browser_opened"] is True


def test_browser_install_leaves_navigation_to_frontend_and_desktop_failure_can_retry(service):
    def blocked(url):
        raise OSError("Browser unavailable")
    service.opener = blocked
    flow = service.configure(GoogleSelection(services=["gmail"]))["flow"]
    assert flow["browser_opened"] is False
    flow = service.configure(GoogleSelection(services=["gmail"], open_browser=True))["flow"]
    assert flow["browser_opened"] is False
    assert service.flow_status(flow["flow_id"]).status == "pending"


def test_partial_google_consent_enables_only_authorized_services_and_redacts_secrets(service):
    result = service.configure(GoogleSelection(services=["gmail", "drive"]))
    state = parse_qs(urlsplit(result["flow"]["authorization_url"]).query)["state"][0]
    def request(method, url, **kwargs):
        if url.endswith("/token"):
            assert kwargs["data"]["code_verifier"]
            return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600, "scope": "openid email " + SERVICES["gmail"]["scopes"][0]})
        assert method == "GET" and url == "https://openidconnect.googleapis.com/v1/userinfo"
        return httpx.Response(200, json={"sub": "account-new", "email": "connected@example.test", "email_verified": True})
    service.request = request
    target, finished = service.receive_callback(code="code", state=state)
    assert target.startswith("http://127.0.0.1:5173/")
    assert finished["status"] == "connected" and "Drive" in finished["message"]
    assert service.registry.is_enabled("gmail")
    assert not service.registry.is_enabled("google-drive")
    assert service.status().email == "connected@example.test"
    assert service.store.load_tokens()["refresh_token"] == "new-refresh"
    assert "new-refresh" not in service.store.metadata_path.read_text()
    assert "new-access" not in service.status().model_dump_json()
    assert service.flow_status(result["flow"]["flow_id"]).status == "connected"
    with pytest.raises(RuntimeError):
        service.receive_callback(code="replay", state=state)


def test_denied_consent_preserves_previous_connection_and_selection(service):
    grant(service, google_calendar_scopes())
    service.registry.set_enabled("google-calendar", True)
    result = service.configure(GoogleSelection(services=["gmail"]))
    state = parse_qs(urlsplit(result["flow"]["authorization_url"]).query)["state"][0]
    _, finished = service.receive_callback(code="", state=state, error="access_denied")
    assert finished["status"] == "failed"
    assert service.store.load_tokens()["access_token"] == "access-secret"
    assert service.registry.is_enabled("google-calendar")
    assert not service.registry.is_enabled("gmail")


def test_disable_and_reenable_use_same_grant_without_oauth(service):
    grant(service, SERVICES["gmail"]["scopes"])
    service.configure(GoogleSelection(services=["gmail"]))
    assert service.status().services[1].status == "connected"
    service.configure(GoogleSelection(services=[]))
    with pytest.raises(GoogleError, match="Enable"):
        service.read("gmail")
    result = service.configure(GoogleSelection(services=["gmail"]))
    assert "flow" not in result
    assert service.store.load_tokens()["access_token"] == "access-secret"


def test_disabled_provider_blocks_enabled_service(service):
    grant(service, SERVICES["gmail"]["scopes"])
    service.registry.set_enabled("gmail", True)
    service.registry.set_enabled("google-workspace", False)
    with pytest.raises(GoogleError, match="Enable"):
        service.read("gmail")


def test_read_uses_fixed_get_endpoint_and_refreshes_in_os_store(service):
    grant(service, SERVICES["gmail"]["scopes"])
    service.registry.set_enabled("gmail", True)
    tokens = service.store.load_tokens()
    service.store.save_tokens({**tokens, "expires_at": 999})
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/token"):
            return httpx.Response(200, json={"access_token": "refreshed", "expires_in": 3600})
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    service.request = request
    result = service.read("gmail", query="is:unread", limit=500)
    assert result["result"]["messages"][0]["id"] == "m1"
    assert calls[1][0:2] == ("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
    assert calls[1][2]["params"]["maxResults"] == 50
    assert service.store.load_tokens()["refresh_token"] == "refresh-secret"
    assert service.store.load_tokens()["access_token"] == "refreshed"


def test_missing_permission_is_blocked_before_data_request(service):
    grant(service, google_calendar_scopes())
    service.registry.set_enabled("gmail", True)
    with pytest.raises(GoogleError, match="permission"):
        service.read("gmail")


def test_disabled_provider_api_reports_configuration_instead_of_repeating_signin(service):
    grant(service, SERVICES["gmail"]["scopes"])
    service.registry.set_enabled("gmail", True)
    service.request = lambda *args, **kwargs: httpx.Response(403, json={"error": {"message": "private-provider-detail", "details": [{"reason": "SERVICE_DISABLED"}]}})
    with pytest.raises(GoogleError, match="Gmail API is disabled") as error:
        service.read("gmail", limit=1)
    assert "Signing in again is not required" in str(error.value)
    assert "private-provider-detail" not in str(error.value)


def test_disconnect_clears_shared_credentials_and_switches_all_services_off(service):
    grant(service, SERVICES["gmail"]["scopes"])
    service.registry.set_enabled("gmail", True)
    result = service.disconnect()
    assert result["changed"]
    assert not service.store.load_tokens(required=False)
    assert not any(row.enabled for row in service.status().services)


def test_invalid_state_and_nonlocal_return_are_rejected(service):
    service.configure(GoogleSelection(services=["gmail"]))
    with pytest.raises(RuntimeError):
        service.receive_callback(code="code", state="google.wrong")
    with pytest.raises(ValueError):
        GoogleSelection(services=["gmail"], return_url="https://example.test/")
    with pytest.raises(ValueError):
        GoogleSelection(services=["gmail", "gmail"])


def test_explicit_account_change_starts_oauth_even_when_scopes_exist(service):
    grant(service, SERVICES["gmail"]["scopes"])
    result = service.configure(GoogleSelection(services=["gmail"], force_signin=True))
    assert result["flow"]["status"] == "pending"
    assert parse_qs(urlsplit(result["flow"]["authorization_url"]).query)["prompt"] == ["consent select_account"]


def test_calendar_only_disconnect_keeps_other_google_credentials(service, monkeypatch):
    from agent.plugins import google_calendar_api as calendar
    grant(service, SERVICES["gmail"]["scopes"])
    service.store._atomic_write(service.store.metadata_path, {"google_account_id": "account", "scope": SERVICES["gmail"]["scopes"][0]})
    service.registry.set_enabled_many({"google-calendar": True, "gmail": True})
    monkeypatch.setattr(calendar, "google_calendar_store", lambda: service.store)
    monkeypatch.setattr(calendar, "get_plugin_registry", lambda: service.registry)
    calendar.disconnect_calendar_connection()
    assert not service.registry.is_enabled("google-calendar")
    assert service.registry.is_enabled("gmail")
    assert service.store.load_tokens()["access_token"] == "access-secret"


def test_status_transport_rejects_nonlocal_origins_and_requires_custom_header(service, monkeypatch):
    from agent.plugins import google_workspace_api as api
    monkeypatch.setattr(api, "google_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    assert client.get("/api/plugins/google/status").status_code == 403
    assert client.get("/api/plugins/google/status", headers={"Origin": "https://evil.test", "X-Vellum-Google": "1"}).status_code == 403
    response = client.get("/api/plugins/google/status", headers={"Origin": "http://127.0.0.1:5173", "X-Vellum-Google": "1"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"


def test_connection_action_requires_ui_consent_and_disconnect_confirmation(service):
    from agent.plugins.google_workspace_controls import google_contribution
    actions = {item.definition.id: item for item in google_contribution(service=service).actions}
    configure = actions["google.connection.configure"]
    assert configure.allowed_agents == frozenset({"VellumUI"})
    assert configure.definition.confirmation_rule == "oauth_consent"
    with pytest.raises(ValueError):
        configure.adapter({"arguments": {"services": ["gmail"]}})
    result = configure.adapter({"arguments": {"services": ["gmail"]}, "confirm": True})
    assert result["flow"]["status"] == "pending"
    with pytest.raises(ValueError):
        actions["google.connection.disconnect"].adapter({"arguments": {}})


def test_mail_pagination_reads_every_matching_page_without_three_message_cap(service,monkeypatch):
    from agent.tools.google_workspace import google_workspace_read
    import json
    grant(service,SERVICES['gmail']['scopes'])
    service.registry.set_enabled('gmail',True)
    monkeypatch.setattr('agent.plugins.google_workspace.google_service',lambda:service)
    pages=[]
    def request(method,url,**kwargs):
        if url.endswith('/messages'):
            token=kwargs['params'].get('pageToken')
            pages.append((kwargs['params']['q'],token))
            return httpx.Response(200,json={'messages':[{'id':str(n)} for n in (range(20) if not token else range(20,27))],**({'nextPageToken':'second'} if not token else {})})
        return httpx.Response(200,json={'id':url.rsplit('/',1)[-1],'snippet':'Fixture readable message'})
    service.request=request
    arguments={'service':'gmail','period':'last_24_hours'}
    ids=[]
    while arguments:
        page=json.loads(google_workspace_read.invoke(arguments))['result']
        ids.extend(message['id'] for message in page['messages'])
        arguments=page['continuation']
        service.clock=lambda:1010
    assert len(ids)==27 and len(set(ids))==27
    assert pages==[('after:-85400 before:1000 ',None),('after:-85400 before:1000 ','second')]
    assert page['partial'] is False


def test_calendar_read_passes_exact_window_title_and_cursor(service):
    grant(service,SERVICES['calendar']['scopes'])
    service.registry.set_enabled('google-calendar',True)
    calls=[]
    def request(method,url,**kwargs):
        calls.append(kwargs['params'])
        return httpx.Response(200,json={'items':[]})
    service.request=request
    service.read('calendar',query='badminton',time_min='2026-10-24T20:00:00+05:30',time_max='2026-10-24T20:01:00+05:30',page_token='next')
    assert calls[0]['timeMin']=='2026-10-24T20:00:00+05:30'
    assert calls[0]['timeMax']=='2026-10-24T20:01:00+05:30'
    assert calls[0]['q']=='badminton' and calls[0]['pageToken']=='next'
    with pytest.raises(GoogleError,match='timezone'):
        service.read('calendar',time_min='2026-10-24T20:00:00')
    with pytest.raises(GoogleError,match='later'):
        service.read('calendar',time_min='2026-10-24T20:00:00+05:30',time_max='2026-10-24T19:00:00+05:30')
    assert len(calls)==1
