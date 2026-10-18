from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import json

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agent import account_api, accounts
from agent.accounts import AccountError, AccountService


class Keyring:
    def __init__(self):
        self.value = None
        self.fail_write = False

    def get_password(self, *args):
        return self.value

    def set_password(self, service, key, value):
        if self.fail_write:
            raise RuntimeError("credential store locked")
        self.value = value


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
        account_google_client_id="google-client", account_google_client_secret="google-secret",
        account_github_client_id="github-client"))
    keyring = Keyring()
    now = [100.0]
    requests = []
    replies = {}

    def respond(request):
        requests.append(request)
        reply = replies.get(request.url.path, {})
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)

    service = AccountService(keyring=keyring, transport=httpx.MockTransport(respond), clock=lambda: now[0], opener=lambda _: True)
    replies.update({
        "/token": {"access_token": "google-private-token"},
        "/v1/userinfo": {"sub": "google-user-1", "email": "user@example.com", "email_verified": True, "name": "Alex"},
        "/login/device/code": {"device_code": "private-device-code", "user_code": "ABCD-EFGH", "interval": 5, "expires_in": 900},
        "/login/oauth/access_token": {"access_token": "github-private-token"},
        "/user": {"id": 123, "login": "alex", "name": "Alex GitHub", "email": "unverified@example.com"},
        "/user/emails": [{"email": "user@example.com", "verified": True, "primary": True}],
    })
    return service, keyring, now, requests, replies


def google_login(service):
    flow = service.start("google")
    state = parse_qs(urlparse(flow.authorization_url).query)["state"][0]
    assert service.google_callback(state, "code", "")
    return flow, state


def test_google_pkce_verified_identity_and_single_use_callback(setup):
    service, keyring, _, requests, _ = setup
    flow = service.start("google")
    query = parse_qs(urlparse(flow.authorization_url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == ["select_account"]
    assert query["redirect_uri"] == [accounts.GOOGLE_CALLBACK]
    assert query["state"][0] != flow.flow_id
    assert "google-secret" not in flow.model_dump_json()
    assert not service.google_callback("wrong-state", "code", "")
    assert service.status().accounts == []
    assert service.google_callback(query["state"][0], "code", "")
    assert not service.google_callback(query["state"][0], "code", "")
    assert service.poll(flow.flow_id).status == "complete"
    assert service.status().accounts[0].email == "user@example.com"
    assert "code_verifier=" in requests[0].content.decode()
    assert "google-private-token" not in keyring.value
    assert "google-secret" not in keyring.value
    assert "verifier" not in service.flows[flow.flow_id]
    # Restoring identities uses the system store and does not need a provider call.
    restored = AccountService(keyring=keyring)
    assert restored.status().active_account_id == service.status().active_account_id


@pytest.mark.parametrize("outcome", ["denied", "expired", "unverified", "storage_failure"])
def test_google_does_not_claim_success_when_sign_in_fails(setup, outcome):
    service, keyring, now, _, replies = setup
    flow = service.start("google")
    state = service.flows[flow.flow_id]["state"]
    if outcome == "expired":
        now[0] += 601
    if outcome == "unverified":
        replies["/v1/userinfo"]["email_verified"] = False
    if outcome == "storage_failure":
        keyring.fail_write = True
    assert not service.google_callback(state, "code", "access_denied" if outcome == "denied" else "")
    assert service.status().accounts == []
    assert service.poll(flow.flow_id).status in {"failed", "expired"}
    assert "state" not in service.flows[flow.flow_id]


def test_duplicate_account_and_email_collision_do_not_merge_providers(setup):
    service, _, now, _, _ = setup
    google_login(service)
    google_login(service)
    assert len(service.status().accounts) == 1
    flow = service.start("github")
    now[0] += 5
    assert service.poll(flow.flow_id).status == "complete"
    status = service.status()
    assert len(status.accounts) == 2
    assert {a.provider for a in status.accounts} == {"google", "github"}
    assert len({a.email for a in status.accounts}) == 1
    first = status.accounts[0]
    assert service.select(first.id).active_account_id == first.id
    assert service.sign_out(first.id).active_account_id is None
    assert len(service.status().accounts) == 1
    service.select(service.status().accounts[0].id)
    with pytest.raises(AccountError, match="no longer saved"):
        service.select("missing")


def test_github_polling_respects_slow_down_and_keeps_tokens_private(setup):
    service, keyring, now, requests, replies = setup
    replies["/login/oauth/access_token"] = {"error": "slow_down"}
    flow = service.start("github")
    assert flow.user_code == "ABCD-EFGH"
    assert "private-device-code" not in flow.model_dump_json()
    assert service.poll(flow.flow_id).status == "pending"
    assert len(requests) == 1
    now[0] += 5
    assert service.poll(flow.flow_id).interval == 10
    now[0] += 5
    service.poll(flow.flow_id)
    assert len(requests) == 2
    now[0] += 5
    replies["/login/oauth/access_token"] = {"error": "authorization_pending"}
    assert service.poll(flow.flow_id).status == "pending"
    now[0] += 10
    replies["/login/oauth/access_token"] = {"access_token": "github-private-token"}
    assert service.poll(flow.flow_id).status == "complete"
    assert service.status().accounts[0].email == "user@example.com"
    assert "private-token" not in keyring.value
    assert "private-device-code" not in keyring.value
    assert requests[-1].headers["authorization"] == "Bearer github-private-token"


@pytest.mark.parametrize("error", ["access_denied", "expired_token", "incorrect_client_credentials"])
def test_github_failures_leave_accounts_unchanged(setup, error):
    service, _, now, _, replies = setup
    flow = service.start("github")
    replies["/login/oauth/access_token"] = {"error": error}
    now[0] += 5
    result = service.poll(flow.flow_id)
    assert result.status == "failed"
    assert "device_code" not in service.flows[flow.flow_id]
    assert not service.status().accounts


def test_cancellation_and_sign_out_block_late_callback(setup):
    service, _, _, _, _ = setup
    google_login(service)
    active = service.status().active_account_id
    flow = service.start("google")
    state = service.flows[flow.flow_id]["state"]
    service.sign_out(active)
    assert not service.google_callback(state, "code", "")
    assert service.poll(flow.flow_id).status == "cancelled"
    assert not service.status().accounts
    github = service.start("github")
    assert service.cancel(github.flow_id).status == "cancelled"
    assert "device_code" not in service.flows[github.flow_id]


def test_provider_readiness_and_corrupt_store_fail_closed(setup, monkeypatch):
    service, keyring, _, _, _ = setup
    monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
        account_google_client_id="", account_google_client_secret="", account_github_client_id=""))
    assert not any(p.available for p in service.status().providers)
    with pytest.raises(AccountError, match="not been configured"):
        service.start("google")
    keyring.value = "corrupt"
    assert service.status().storage_available is False
    assert keyring.value == "corrupt"


def test_api_guards_and_typed_contracts(setup, monkeypatch):
    service, _, _, _, _ = setup
    monkeypatch.setattr(account_api, "service", lambda: service)
    app = FastAPI()
    router = APIRouter(prefix="/api")
    router.include_router(account_api.router)
    app.include_router(router)
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    headers = {"Origin": "http://127.0.0.1:5173", "X-Vellum-Accounts": "1"}
    assert client.get("/api/accounts/status").status_code == 403
    assert client.get("/api/accounts/status", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    result = client.get("/api/accounts/status", headers=headers)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["contract_version"] == 1
    assert client.post("/api/accounts/start", headers=headers, json={"provider": "sso"}).status_code == 422
    started = client.post("/api/accounts/start", headers=headers, json={"provider": "google"})
    assert started.status_code == 200
    flow_id = started.json()["flow_id"]
    assert client.post("/api/accounts/cancel", headers=headers, json={"flow_id": flow_id}).json()["status"] == "cancelled"
    callback = client.get("/api/accounts/callback/google", params={"state": "wrong", "error": "<script>bad</script>"})
    assert callback.status_code == 400
    assert "<script>" not in callback.text
    assert callback.headers["referrer-policy"] == "no-referrer"
    remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 50000))
    assert remote.get("/api/accounts/status", headers=headers).status_code == 403


@pytest.mark.parametrize("provider", ["google", "github"])
def test_successful_callback_returns_to_originating_vellum_page(setup, monkeypatch, provider):
    service, _, _, _, _ = setup
    if provider == "github":
        monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
            account_google_client_id="google-client", account_google_client_secret="google-secret",
            account_github_client_id="github-client", account_github_client_secret="github-secret"))
    monkeypatch.setattr(account_api, "service", lambda: service)
    app = FastAPI()
    app.include_router(account_api.router, prefix="/api")
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    headers = {"Origin": "http://127.0.0.1:5173", "X-Vellum-Accounts": "1"}
    target = "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html"
    started = client.post("/api/accounts/start", headers=headers, json={"provider": provider, "return_url": target, "open_browser": False})
    assert started.status_code == 200
    assert started.json()["browser_opened"] is False
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    callback = client.get(f"/api/accounts/callback/{provider}", params={"state": state, "code": "code"}, follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == target
    assert callback.headers["referrer-policy"] == "no-referrer"
    assert callback.headers["cache-control"] == "no-store"
    assert "code" not in callback.headers["location"]
    replay = client.get(f"/api/accounts/callback/{provider}", params={"state": state, "code": "code"}, follow_redirects=False)
    assert replay.status_code == 400
    for url in ("https://evil.example/", "http://localhost:5173.evil.example/", "http://localhost:5173/@evil", "http://localhost:5173/?next=https://evil.example"):
        assert client.post("/api/accounts/start", headers=headers, json={"provider": "google", "return_url": url}).status_code == 422
    assert client.post("/api/accounts/logout").status_code == 403
    assert client.post("/api/accounts/continue-local").status_code == 403
    logged_out = client.post("/api/accounts/logout", headers=headers)
    assert logged_out.status_code == 200
    assert logged_out.json()["logged_out"] is True
    assert logged_out.json()["active_account_id"] is None
    assert client.post("/api/accounts/continue-local", headers=headers).json()["logged_out"] is False


@pytest.mark.parametrize("error", ["access_denied", "bad_code"])
def test_github_redirect_denial_does_not_redirect_or_create_an_account(setup, monkeypatch, error):
    service, _, _, _, replies = setup
    monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
        account_google_client_id="google-client", account_google_client_secret="google-secret",
        account_github_client_id="github-client", account_github_client_secret="github-secret"))
    flow = service.start("github", open_browser=False)
    state = parse_qs(urlparse(flow.authorization_url).query)["state"][0]
    if error == "bad_code":
        replies["/login/oauth/access_token"] = {"error": "bad_verification_code"}
    assert not service.complete_callback("github", state, "code", "access_denied" if error == "access_denied" else "")[0]
    assert service.poll(flow.flow_id).status == "failed"
    assert service.status().accounts == []
    assert "verifier" not in service.flows[flow.flow_id]


def test_logout_cancels_pending_sign_in_and_persists_signed_out_state(setup):
    service, keyring, _, _, _ = setup
    google_login(service)
    saved = service.status().accounts
    pending = service.start("google")
    state = parse_qs(urlparse(pending.authorization_url).query)["state"][0]
    result = service.logout()
    assert result.active_account_id is None
    assert result.logged_out is True
    assert result.accounts == saved
    assert not service.google_callback(state, "code", "")
    assert service.poll(pending.flow_id).status == "cancelled"
    restored = AccountService(keyring=keyring)
    assert restored.status().logged_out is True
    assert restored.continue_local().logged_out is False
    assert restored.status().active_account_id is None


def test_github_redirect_flow_uses_pkce_and_discards_credentials(setup, monkeypatch):
    service, keyring, _, requests, _ = setup
    monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
        account_google_client_id="google-client", account_google_client_secret="google-secret",
        account_github_client_id="github-client", account_github_client_secret="github-secret"))
    flow = service.start("github", open_browser=False)
    query = parse_qs(urlparse(flow.authorization_url).query)
    assert flow.method == "redirect"
    assert urlparse(flow.authorization_url).path == "/login/oauth/authorize"
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [accounts.GITHUB_CALLBACK]
    assert query["allow_signup"] == ["true"]
    assert not service.complete_callback("google", query["state"][0], "code", "")[0]
    assert service.complete_callback("github", query["state"][0], "code", "")[0]
    token_body = parse_qs(requests[0].content.decode())
    assert token_body["client_secret"] == ["github-secret"]
    assert token_body["code_verifier"]
    assert "github-secret" not in flow.model_dump_json()
    assert "github-private-token" not in keyring.value
    assert service.status().accounts[0].provider == "github"


@pytest.fixture
def email_setup(setup, monkeypatch):
    monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
        account_google_client_id="google-client", account_google_client_secret="google-secret", account_github_client_id="github-client",
        account_supabase_url="https://fixture-project.supabase.co", account_supabase_publishable_key="sb_publishable_fixture"))
    service, keyring, now, requests, replies = setup
    replies.update({
        "/auth/v1/signup": {"id": "hosted-user-1", "email": "alex@example.com"},
        "/auth/v1/token": {"access_token": "email-private-token", "refresh_token": "email-private-refresh"},
        "/auth/v1/user": {"id": "hosted-user-1", "email": "alex@example.com", "email_confirmed_at": "2026-10-17T00:00:00Z"},
    })
    return service, keyring, now, requests, replies


def test_email_signup_requires_confirmation_and_keeps_passwords_private(email_setup):
    service, keyring, _, requests, _ = email_setup
    result = service.email_sign_up("Alex@Example.com", "fixture-password-only")
    assert result.status == "confirmation_required"
    assert service.status().accounts == []
    assert service.status().email_auth_available is True
    assert "fixture-password-only" not in result.model_dump_json()
    assert "fixture-password-only" not in json.dumps(service.flows)
    body = json.loads(requests[0].content)
    assert body["email"] == "alex@example.com"
    assert body["code_challenge_method"] == "s256"
    state = service.flows[result.flow.flow_id]["state"]
    assert service.complete_callback("email", state, "fixture-code", "")[0]
    assert service.status().accounts[0].provider == "email"
    assert not service.complete_callback("email", state, "fixture-code", "")[0]
    assert "private-token" not in keyring.value
    assert "private-refresh" not in keyring.value
    assert "fixture-password-only" not in keyring.value
    assert "verifier" not in service.flows[result.flow.flow_id]


def test_hosted_email_identity_is_the_same_on_two_installations(email_setup):
    service, keyring, _, requests, _ = email_setup
    first = service.email_sign_in("alex@example.com", "fixture-password-only")
    other_keyring = Keyring()
    other = AccountService(keyring=other_keyring, transport=service.transport)
    second = other.email_sign_in("alex@example.com", "fixture-password-only")
    assert first.accounts == second.accounts
    assert first.active_account_id == second.active_account_id
    assert first.accounts[0].provider == "email"
    assert keyring.value is not None and other_keyring.value is not None
    assert requests[0].url.params["grant_type"] == "password"
    assert "fixture-password-only" not in keyring.value
    assert "private-token" not in other_keyring.value


@pytest.mark.parametrize("outcome", ["wrong_password", "unconfirmed", "rate_limited"])
def test_email_sign_in_failure_never_creates_a_local_identity(email_setup, outcome):
    service, _, _, _, replies = email_setup
    if outcome == "wrong_password":
        replies["/auth/v1/token"] = httpx.Response(400, json={"error": "invalid_grant", "msg": "fixture-password-only"})
    elif outcome == "rate_limited":
        replies["/auth/v1/token"] = httpx.Response(429, json={})
    else:
        replies["/auth/v1/user"]["email_confirmed_at"] = None
    with pytest.raises(AccountError) as exc:
        service.email_sign_in("alex@example.com", "fixture-password-only")
    assert "fixture-password-only" not in str(exc.value)
    assert not service.status().accounts


def test_email_validation_and_logout_cancel_confirmation(email_setup):
    service, _, _, requests, _ = email_setup
    with pytest.raises(AccountError):
        service.email_sign_up("not-email", "fixture-password-only")
    with pytest.raises(AccountError):
        service.email_sign_up("alex@example.com", "short")
    assert not requests
    pending = service.email_sign_up("alex@example.com", "fixture-password-only")
    state = service.flows[pending.flow.flow_id]["state"]
    service.logout()
    assert not service.complete_callback("email", state, "fixture-code", "")[0]
    assert service.status().logged_out is True


def test_email_api_redacts_passwords_from_validation_and_provider_errors(email_setup, monkeypatch):
    service, _, _, _, _ = email_setup
    monkeypatch.setattr(account_api, "service", lambda: service)
    app = FastAPI()
    app.include_router(account_api.router, prefix="/api")
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    headers = {"Origin": "http://127.0.0.1:5173", "X-Vellum-Accounts": "1"}
    path = "/api/accounts/email/sign-in"
    assert client.post(path, json={"email": "alex@example.com", "password": "fixture-password-only"}).status_code == 403
    invalid = client.post(path, headers=headers, json={"password": "fixture-password-only"})
    assert invalid.status_code == 422
    assert "fixture-password-only" not in invalid.text
    signed_in = client.post(path, headers=headers, json={"email": "alex@example.com", "password": "fixture-password-only"})
    assert signed_in.status_code == 200
    assert "private-token" not in signed_in.text
    assert "fixture-password-only" not in signed_in.text


def test_email_config_rejects_secret_keys_and_insecure_destinations(email_setup, monkeypatch):
    service, _, _, _, _ = email_setup
    for url, key in (("http://fixture-project.supabase.co", "sb_publishable_fixture"),
                     ("https://evil.example", "sb_publishable_fixture"),
                     ("https://fixture-project.supabase.co", "sb_secret_do-not-use")):
        monkeypatch.setattr(accounts, "get_settings", lambda: SimpleNamespace(
            account_google_client_id="", account_google_client_secret="", account_github_client_id="",
            account_supabase_url=url, account_supabase_publishable_key=key))
        assert service.status().email_auth_available is False
        with pytest.raises(AccountError):
            service.email_sign_in("alex@example.com", "fixture-password-only")
