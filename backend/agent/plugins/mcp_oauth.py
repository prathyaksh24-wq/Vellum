"""Shared OAuth lifecycle for official hosted MCP connections.

The existing PluginMcpRuntime owns transport, policy, approvals and auditing.
This helper owns only the local connection lifecycle and bounded credential record.
Provider-specific client registration/authentication uses narrow overridable hooks.
"""
import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import secrets
from threading import RLock, Thread
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import httpx
from jsonschema import Draft202012Validator
from agent.plugins.credentials import KeyringRecordStore
logger = logging.getLogger(__name__)


class OAuthRefreshRejected(ValueError):
    """Terminal provider response; never retry a rejected rotating token."""

@dataclass(frozen=True)
class OfficialOAuthProvider:
    plugin_id: str
    name: str
    server: str
    authorize: str
    token: str
    register: str
    resource: str
    callback: str
    scopes: str

def invalidate_tools():
    from agent.graph.agent import agent
    agent.invalidate()

def catalog_failure(error, provider_name):
    """Keep diagnostic categories, never provider bodies, URLs or credentials."""
    known = {}
    pending, seen = ([error], set())
    while pending and len(seen) < 24:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, httpx.HTTPStatusError):
            response = item.response
            code = None
            try:
                payload = response.json()
                value = payload.get('error') if isinstance(payload, dict) else None
                code = value if isinstance(value, str) and value in known else None
            except (ValueError, TypeError):
                pass
            status = response.status_code
            return (code or f'mcp_http_{status}', known.get(code) or f"{provider_name}'s MCP endpoint returned HTTP {status}. Account sign-in succeeded, but MCP access was not verified.")
        if isinstance(item, (TimeoutError, httpx.TimeoutException)):
            return ('mcp_timeout', f"{provider_name}'s MCP catalog did not respond in time. Retry the connection before changing app permissions.")
        if isinstance(item, httpx.RequestError):
            return ('mcp_network_error', f"Vellum could not reach {provider_name}'s MCP endpoint. Check network access before changing the {provider_name} app.")
        from mcp.shared.exceptions import McpError
        from pydantic import ValidationError
        if isinstance(item, McpError):
            code = item.error.code
            return (f'mcp_protocol_{code}', f"{provider_name}'s MCP server rejected the protocol request (code {code}).")
        if isinstance(item, ValidationError):
            return ('mcp_response_schema', f"Vellum could not parse {provider_name}'s MCP response. This needs a connector correction, not another permissions change.")
        if isinstance(item, (TypeError, AttributeError, ImportError)):
            return ('mcp_client_error', 'Vellum encountered a local MCP client compatibility error. This needs a connector correction.')
        pending.extend(getattr(item, 'exceptions', ()) or ())
        if item.__cause__ is not None:
            pending.append(item.__cause__)
        elif item.__context__ is not None:
            pending.append(item.__context__)
    return ('mcp_transport_error', f'Vellum could not complete the {provider_name} MCP connection. The local diagnostic records the failure category; no workspace access was marked ready.')

class OfficialMcpOAuthService(KeyringRecordStore):

    def __init__(self, *, keyring=None, enabled=None, clock=time.time, request=None, transport=None, invalidator=invalidate_tools):
        if keyring is None:
            import keyring as keyring
        super().__init__(keyring, service='vellum.plugins.' + self.provider.plugin_id, error_type=self.error_type, account='connection-v1')
        self.clock = clock
        self.enabled = enabled or self._enabled
        self.request, self.transport, self.invalidator = (request or httpx.request, transport, invalidator)
        self.lock, self.flows = (RLock(), {})
        self.tools, self.tools_revision = ([], '')

    def _enabled(self):
        from agent.plugins.registry import get_plugin_registry
        return get_plugin_registry().is_enabled(self.provider.plugin_id)

    def status(self):
        enabled = self.enabled()
        try:
            data = self.load()
        except self.error_type as exc:
            return self.status_model(enabled=enabled, status='keyring_unavailable', message=str(exc))
        configured = bool(data.get('access_token'))
        fresh = 0 <= self.clock() - data.get('checked_epoch', 0) < 86400
        connected = enabled and configured and (data.get('status') == 'ready') and fresh
        return self.status_model(
            enabled=enabled, configured=configured, connected=connected,
            **self.public_identity(data), account_name=data.get('account_name'),
            verified_at=data.get('verified_at'), mcp_tool_count=data.get('mcp_tool_count', 0),
            granted_scopes=data.get('granted_scopes', []),
            status='disabled' if not enabled else 'ready' if connected else 'not_checked' if configured else 'not_connected',
            message=f'{self.provider.name} account and official MCP access verified.' if connected else
                f'Enable {self.provider.name} to use its connection.' if not enabled else
                f'Reconnect {self.provider.name} to renew its expired or revoked authorization.' if data.get('refresh_rejected') else
                f'Verify the saved {self.provider.name} connection before using it.' if configured else
                f'Sign in with {self.provider.name} and choose the resources Vellum can access.',
        )

    def _json(self, url, *, method='POST', **kwargs):
        try:
            response = self.request(method, url, timeout=30, follow_redirects=False, **kwargs)
            if response.status_code >= 300:
                if url == self.provider.token and (kwargs.get('data') or kwargs.get('json') or {}).get('grant_type') == 'refresh_token':
                    try:
                        error = response.json().get('error')
                    except (ValueError, AttributeError):
                        error = None
                    if error in {'invalid_grant', 'invalid_client'}:
                        raise OAuthRefreshRejected()
                hint = {401: f'{self.provider.name} authorization expired or was revoked. Reconnect in Plugins.', 403: f'{self.provider.name} denied access. Check your selected resources and organization approval.', 429: f'{self.provider.name} rate limit reached. Wait before trying again.'}.get(response.status_code)
                raise self.error_type(hint or f'{self.provider.name} rejected this request (HTTP {response.status_code}). No operation was automatically replayed.')
            data = response.json()
            if not isinstance(data, dict) or data.get('error'):
                raise self.error_type(f'{self.provider.name} did not authorize this request. Start sign-in again and review the selected resources.')
            return data
        except (self.error_type, OAuthRefreshRejected):
            raise
        except Exception:
            raise self.error_type(f'{self.provider.name} is unavailable. Retry later; no operation was automatically replayed.') from None

    def require(self):
        if not self.enabled():
            raise self.error_type(f'Enable {self.provider.name} in Plugins first.')
        with self.lock:
            data = self.load()
            if not data.get('access_token'):
                raise self.error_type(f'Sign in with {self.provider.name} in Plugins first.')
            if data.get('refresh_rejected'):
                raise self.error_type(f'Reconnect {self.provider.name}; this authorization can no longer refresh.')
            if data.get('expires_at') and self.clock() >= data['expires_at'] - 60:
                if not data.get('refresh_token'):
                    raise self.error_type(f'{self.provider.name} authorization expired. Reconnect in Plugins.')
                try:
                    refreshed = self.token_request(data, {
                        'grant_type': 'refresh_token',
                        'refresh_token': data['refresh_token'], 'resource': self.provider.resource,
                    })
                except OAuthRefreshRejected:
                    self.save({**data, 'refresh_rejected': True, 'status': 'reauthorization_required'})
                    raise self.error_type(f'Reconnect {self.provider.name}; its refresh authorization expired or was revoked.') from None
                data = {**data, **self._tokens(refreshed)}
                self.save(data)
            return data

    def _tokens(self, value):
        token, refresh = (value.get('access_token'), value.get('refresh_token'))
        expires = value.get('expires_in')
        if (not isinstance(token, str) or not token or len(token) > 16000
                or str(value.get('token_type', '')).strip().lower() != 'bearer'
                or not isinstance(refresh, str) or not refresh or len(refresh) > 16000
                or type(expires) not in (int, float) or not 60 < expires < 366 * 86400):
            raise self.error_type(f'{self.provider.name} returned an invalid OAuth authorization response.')
        return {'access_token': token, 'refresh_token': refresh, 'expires_at': self.clock() + expires}

    def connector(self, data):
        from agent.mcp.plugin_runtime import PluginMcpConnector
        return PluginMcpConnector(plugin_id=self.provider.plugin_id, name=self.provider.plugin_id, root=Path(__file__).parent, transport='http', url=self.provider.server, headers={'Authorization': 'Bearer ' + data['access_token']})

    def _catalog(self, data, *, connector=None):
        from agent.mcp.plugin_runtime import SdkPluginMcpTransport
        from agent.tools.plugin_mcp import _run_async
        phase = 'transport'
        try:
            values = _run_async(asyncio.wait_for((self.transport or SdkPluginMcpTransport()).list_tools(connector or self.connector(data)), timeout=40))
            phase = 'catalog_validation'
            if not values or len(values) > 1000:
                raise ValueError()
            tools = [self.tool_model.model_validate(value).model_dump() for value in values]
            for tool in tools:
                if not tool['name'].isascii() or not tool['name'].replace('_', '').replace('-', '').isalnum() or len(tool['name']) > 100:
                    raise ValueError()
                Draft202012Validator.check_schema(tool['input_schema'])
            return tools
        except Exception as exc:
            code, message = catalog_failure(exc, self.provider.name) if phase == 'transport' else ('mcp_catalog_validation', f'{self.provider.name} returned a tool catalog that Vellum could not validate. This needs a connector correction, not another permissions change.')
            logger.warning(f'{self.provider.name} MCP catalog failed: phase=%s code=%s error_type=%s', phase, code, type(exc).__name__)
            raise self.error_type(message + f' Diagnostic: {code}.') from None

    def catalog(self, refresh=False):
        data = self.require()
        if not refresh and self.tools_revision == data['revision']:
            return list(self.tools)
        tools = self._catalog(data)
        with self.lock:
            if self.require()['revision'] != data['revision']:
                raise self.error_type(f'The {self.provider.name} connection changed. Refresh its tools.')
            self.tools, self.tools_revision = (tools, data['revision'])
            self.save({**self.require(), 'mcp_tool_count': len(tools)})
        self.invalidator()
        return list(tools)

    def cached_tools(self):
        data = self.load()
        return list(self.tools) if self.enabled() and data.get('revision') == self.tools_revision else []

    def client_fields(self, data):
        return {'client_id': data['client_id']} if data.get('client_id') else {}

    def register_client(self, data):
        if data.get('client_id'):
            return self.client_fields(data)
        client = self._json(self.provider.register, json={'client_name': 'Vellum', 'redirect_uris': [self.provider.callback], 'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'], 'token_endpoint_auth_method': 'none', 'scope': self.provider.scopes})
        client_id = client.get('client_id')
        if not isinstance(client_id, str) or not re.fullmatch('[A-Za-z0-9_-]{5,200}', client_id) or client.get('token_endpoint_auth_method', 'none') != 'none' or client.get('client_secret') or client.get('redirect_uris', [self.provider.callback]) != [self.provider.callback]:
            raise self.error_type(f'{self.provider.name} did not register the expected public desktop client.')
        return {'client_id': client_id}

    def token_request(self, client, parameters):
        return self._json(self.provider.token, data={'client_id': client['client_id'], **parameters})

    def start(self, request):
        if not self.enabled():
            raise self.error_type(f'Enable {self.provider.name} before connecting.')
        with self.lock:
            data = self.load()
            self._cancel_flows()
            self.flows = {}
            client = self.register_client(data)
            client_id = client['client_id']
            if any(data.get(key) != value for key, value in client.items()):
                self.save({**data, **client})
            identifier, state, verifier = (secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64))
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            url = self.provider.authorize + '?' + urlencode({'client_id': client_id, 'redirect_uri': self.provider.callback, 'scope': self.provider.scopes, 'resource': self.provider.resource, 'response_type': 'code', 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
            self.flows[identifier] = {'status': 'pending', 'message': f'Choose your {self.provider.name} account and the resources Vellum can access.', 'created': self.clock(), 'state': state, 'verifier': verifier, 'consumed': False, **client, 'original_revision': data.get('revision'), 'return_url': request.return_url, 'popup': request.popup, 'authorization_url': url}
        return self.flow_start_model(flow_id=identifier, authorization_url=url, status='pending',
            message=f"Review {self.provider.name}'s requested permissions and choose the resources to connect.")

    def flow_status(self, identifier):
        with self.lock:
            flow = self.flows.get(identifier)
            if not flow:
                raise self.error_type(f'{self.provider.name} sign-in expired. Start again.')
            if flow['status'] == 'pending' and self.clock() - flow['created'] > 600:
                flow.update(status='failed', message=f'{self.provider.name} sign-in expired. Start again.')
                flow.pop('verifier', None)
            return self.flow_status_model(flow_id=identifier, status=flow['status'], message=flow['message'])

    def callback(self, state, code, error=''):
        if not state or not state.isascii() or len(state) > 200 or (len(code) > 2048):
            raise self.error_type(f'{self.provider.name} sign-in expired. Start again.')
        with self.lock:
            identifier = next((key for key, value in self.flows.items() if secrets.compare_digest(value['state'], state)), None)
            if not identifier or self.flow_status(identifier).status != 'pending' or self.flows[identifier]['consumed']:
                raise self.error_type(f'{self.provider.name} sign-in expired or was already used.')
            flow = self.flows[identifier]
            flow['consumed'] = True
            if error or not code:
                reasons = {
                    'invalid_target': 'rejected the requested OAuth resource. The connector needs a resource-address correction.',
                    'invalid_scope': 'rejected the requested permissions. The connector needs a scope correction.',
                    'invalid_request': 'rejected the sign-in request before consent.',
                    'unauthorized_client': 'did not accept this app registration.',
                    'access_denied': 'did not grant access. You can start sign-in again.',
                }
                safe_error = error if error in reasons else 'authorization_incomplete'
                logger.warning('%s OAuth callback rejected: code=%s', self.provider.name, safe_error)
                reason = reasons.get(error, 'did not complete authorization. Start sign-in again.')
                flow.update(status='failed', message=f'{self.provider.name} {reason} Your saved connection is unchanged.')
                flow.pop('verifier', None)
                return identifier
            flow['message'] = f'Verifying your {self.provider.name} account and official MCP access…'
        Thread(target=self._finish, args=(identifier, code), daemon=True).start()
        return identifier

    def _finish(self, identifier, code):
        phase = 'exchanging authorization'
        try:
            with self.lock:
                flow = dict(self.flows[identifier])
            value = self.token_request(flow, {'grant_type': 'authorization_code', 'code': code, 'code_verifier': flow['verifier'], 'redirect_uri': self.provider.callback, 'resource': self.provider.resource})
            data = {**self._tokens(value), **self.client_fields(flow), 'revision': secrets.token_urlsafe(32)}
            phase = 'verifying your account'
            data.update(self.identity(data))
            phase = 'verifying official MCP access'
            tools = self._catalog(data)
            phase = 'saving authorization'
            with self.lock:
                current, saved = (self.flows.get(identifier), self.load())
                if not current or self.flow_status(identifier).status != 'pending' or (not self.enabled()) or (saved.get('revision') != flow['original_revision']):
                    raise self.error_type(f'The {self.provider.name} connection changed during sign-in.')
                self.save({**data, 'status': 'ready', 'checked_epoch': self.clock(), 'verified_at': datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(), 'mcp_tool_count': len(tools)})
                self.tools, self.tools_revision = (tools, data['revision'])
                current.update(status='connected', message=f'Connected to {self.provider.name}. Continue in your original Vellum window.')
            self.invalidator()
        except Exception as exc:
            logger.warning(f'{self.provider.name} OAuth stopped: phase=%s error_type=%s', phase, type(exc).__name__)
            with self.lock:
                current = self.flows.get(identifier)
                if current and current['status'] == 'pending':
                    detail = str(exc) if isinstance(exc, self.error_type) else 'Vellum encountered a local connection error.'
                    current.update(status='failed', message=f'{self.provider.name} sign-in stopped while {phase}. {detail} Vellum has not marked this sign-in complete.')
        finally:
            with self.lock:
                if identifier in self.flows:
                    self.flows[identifier].pop('verifier', None)

    def return_url(self, identifier):
        with self.lock:
            self.flow_status(identifier)
            target = urlsplit(self.flows[identifier]['return_url'])
            query = [(key, value) for key, value in parse_qsl(target.query) if key not in {'view', self.provider.plugin_id + '_oauth'}]
            return urlunsplit((target.scheme, target.netloc, target.path, urlencode(query + [('view', 'apps'), (self.provider.plugin_id + '_oauth', identifier)]), ''))

    def verify(self):
        data = self.require()
        actor = self.identity(data)
        if any((actor.get(key) != data.get(key) for key in self.identity_keys)):
            raise self.error_type(f'The {self.provider.name} account changed. Reconnect.')
        self.catalog(refresh=True)
        with self.lock:
            current = self.require()
            if current['revision'] != data['revision']:
                raise self.error_type(f'The {self.provider.name} connection changed. Verify again.')
            self.save({**current, **actor, 'status': 'ready', 'checked_epoch': self.clock(), 'verified_at': datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()})
        return self.status()

    def _cancel_flows(self):
        for flow in self.flows.values():
            if flow['status'] == 'pending':
                flow.update(status='cancelled', message=f'{self.provider.name} sign-in cancelled.')
                flow.pop('verifier', None)

    def cancel(self, identifier):
        with self.lock:
            self.flow_status(identifier)
            if self.flows[identifier]['status'] == 'pending':
                self.flows[identifier].update(status='cancelled', message=f'{self.provider.name} sign-in cancelled.')
                self.flows[identifier].pop('verifier', None)
        return {'changed': True}

    def disconnect(self):
        with self.lock:
            client = self.client_fields(self.load())
            self._cancel_flows()
            self.save({**client, 'revision': secrets.token_urlsafe(32)})
            self.tools, self.tools_revision = ([], '')
        self.invalidator()
        return self.status()
    identity_keys = ('account_id',)

    def public_identity(self, data):
        return {}

    def identity(self, data):
        raise NotImplementedError('Provider must verify its own identity.')
