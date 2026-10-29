"""Hosted web/search connections reuse the existing MCP and credential owners."""
from datetime import datetime, timezone
import secrets

from agent.plugins.mcp_oauth import OfficialMcpOAuthService


class WebMcpConnection(OfficialMcpOAuthService):
    """OAuth by default; explicit adoption of an operator's configured key is optional."""

    def configured_credential(self):
        raise NotImplementedError()

    def managed(self):
        return bool(self.load().get('managed'))

    def _tokens(self, value):
        return {**super()._tokens(value), 'managed': True, 'auth_type': 'oauth'}

    def public_identity(self, data):
        return {'workspace_name': data.get('workspace_name'),
            'auth_type': data.get('auth_type', 'none'),
            'configured_key_available': bool(self.configured_credential()),
            'identity_verified': bool(data.get('identity_verified'))}

    def status(self):
        status = super().status()
        if status.connected:
            method = 'OAuth' if status.auth_type == 'oauth' else 'your API key'
            status.message = f'Official {self.provider.name} MCP access verified using {method}.'
        return status

    def use_configured(self):
        if not self.enabled():
            raise self.error_type(f'Enable {self.provider.name} before connecting.')
        token = self.configured_credential()
        if not token:
            raise self.error_type(f'No configured {self.provider.name} credential is available. Sign in with OAuth.')
        return self.connect_key(token, auth_type='configured_api_key')

    def connect_key(self, token, *, auth_type='api_key'):
        """Verify a UI-staged key before replacing the saved authorization."""
        if not self.enabled():
            raise self.error_type(f'Enable {self.provider.name} before connecting.')
        with self.lock:
            original = self.load()
        data = {'access_token': token, 'auth_type': auth_type, 'managed': True,
            'revision': secrets.token_urlsafe(32)}
        data.update(self.identity(data))
        tools = self._catalog(data)
        with self.lock:
            current = self.load()
            if current.get('revision') != original.get('revision') or not self.enabled():
                raise self.error_type('The connection changed during verification. Try again.')
            self._cancel_flows()
            self.save({**data, **({'client_id': current['client_id']} if current.get('client_id') else {}),
                'status': 'ready', 'checked_epoch': self.clock(),
                'verified_at': datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
                'mcp_tool_count': len(tools)})
            self.tools, self.tools_revision = tools, data['revision']
        self.invalidator()
        return self.status()

    def disconnect(self):
        with self.lock:
            client_id = self.load().get('client_id')
            self._cancel_flows()
            self.save({'managed': True, 'revision': secrets.token_urlsafe(32), **({'client_id': client_id} if client_id else {})})
            self.tools, self.tools_revision = [], ''
        self.invalidator()
        return self.status()
