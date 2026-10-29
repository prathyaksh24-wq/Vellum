"""Regression sources for scoped skill imports and renewed Linear authorization."""
import asyncio
import json
import pytest
from mcp.client.auth.exceptions import OAuthFlowError
from agent.plugins.linear import LinearService, connection_failure, same_authorization
from agent.plugins.linear_oauth import ExpiringOAuthClientProvider, OAuthStorage, metadata, SERVER

class BoundedKeyring:
    def __init__(self): self.values = {}
    def get_password(self, service, account): return self.values.get((service, account))
    def set_password(self, service, account, value):
        if len(value.encode('utf-16-le')) > 2560: raise ValueError('Windows size limit')
        self.values[(service, account)] = value
    def delete_password(self, service, account): self.values.pop((service, account), None)

def test_linear_reads_legacy_record_and_persists_large_authorization_with_bounded_entries():
    keyring = BoundedKeyring()
    keyring.set_password('vellum.plugins.linear', 'connection-v1', json.dumps({'legacy': True}))
    service = LinearService(keyring=keyring, enabled=lambda: True)
    assert service._load() == {'legacy': True}
    record = {'auth_type': 'oauth', 'token': 'Bearer ' + 'x' * 3000,
        'oauth_tokens': {'access_token': 'x' * 3000, 'refresh_token': 'r' * 1500}}
    service._save(record)
    assert service._load() == record
    assert all(len(value.encode('utf-16-le')) <= 2560 for value in keyring.values.values())

def test_verification_does_not_overwrite_a_token_refreshed_while_reading_identity(monkeypatch):
    service = LinearService(keyring=BoundedKeyring(), enabled=lambda: True, clock=lambda: 1000)
    identity = dict(actor_id='actor', workspace_id='workspace', account_name='A', workspace_name='W')
    service.connect_oauth({'access_token': 'old'}, {'client_id': 'client'}, identity)
    def read_identity(token):
        service.update_connection(token='Bearer refreshed', oauth_tokens={'access_token': 'refreshed'}, oauth_refresh_generation=1)
        return identity
    monkeypatch.setattr(service, '_identity', read_identity)
    assert service.verify().connected is True
    assert service._require()['token'] == 'Bearer refreshed'

def test_refresh_does_not_allow_replacement_grants_to_pass_as_the_same_authorization():
    original = dict(actor_id='a', workspace_id='w', grant_id='old', token='old', oauth_refresh_generation=0)
    refreshed = {**original, 'token': 'new', 'oauth_refresh_generation': 1}
    assert same_authorization(original, refreshed)
    assert not same_authorization(original, {**refreshed, 'grant_id': 'replacement'})
    assert not same_authorization(original, {**original, 'token': 'unrelated'})

def test_background_auth_failure_explains_reconnect_without_exposing_provider_text():
    failure = connection_failure(ExceptionGroup('transport', [OAuthFlowError('No redirect handler provided for authorization code grant')]))
    assert failure.status == 'authorization_required'
    assert 'Sign in with Linear' in str(failure)

def test_sdk_initialization_restores_the_expiration_deadline():
    storage = OAuthStorage()
    storage.tokens = {'access_token': 'expired-fixture', 'token_type': 'Bearer', 'expires_in': 0}
    provider = ExpiringOAuthClientProvider(SERVER, metadata(), storage)
    asyncio.run(provider._initialize())
    assert provider.context.token_expiry_time is not None
    assert provider.context.is_token_valid() is False

def test_linear_popup_return_closes_without_rendering_a_workspace_inside_auth(monkeypatch):
    from types import SimpleNamespace
    from agent.plugins import linear_oauth
    from agent.plugins.linear_api import oauth_return
    flow=SimpleNamespace(id='a'*43,status='connected',message='Connected',popup=True,
        return_url='http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html?view=apps')
    monkeypatch.setattr(linear_oauth,'return_flow',lambda _:flow)
    response=oauth_return(flow.id)
    assert response.status_code==200
    assert 'window.close()' in response.body.decode()
    assert 'document.body.dataset' in response.body.decode()
    assert "script-src 'nonce-" in response.headers['Content-Security-Policy']
    assert response.headers.get('location') is None
