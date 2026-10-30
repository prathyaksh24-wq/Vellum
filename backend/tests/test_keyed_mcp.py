"""Connection lifecycle regressions; transports and credentials stay with existing owners."""
from pathlib import Path
import pytest
from agent.plugins.keyed_mcp import KeyedMcpService, KeyedMcpError, CONTEXT7_URL, BRAVE_ARGS
from agent.mcp.plugin_runtime import _connector, PluginMcpRuntimeError
from test_connector_cleanup import BoundedKeyring

class CatalogTransport:
    def __init__(self): self.reject = False; self.calls = []
    async def list_tools(self, connector):
        self.calls.append(connector)
        if self.reject: raise TimeoutError()
        return [{'name': 'resolve-library-id', 'description': 'Resolve a library', 'input_schema': {'type': 'object'}, 'read_only': True}]

def test_staging_is_ephemeral_and_failed_replacement_preserves_verified_key():
    transport = CatalogTransport()
    service = KeyedMcpService('context7', keyring=BoundedKeyring(), enabled=lambda: True,
        clock=lambda: 1000, transport=transport, invalidator=lambda: None)
    reference = service.stage('fixture-key-one')
    assert service.load() == {}
    assert service.connect(reference).connected
    before = service.load()
    transport.reject = True
    with pytest.raises(KeyedMcpError): service.connect(service.stage('fixture-key-two'))
    assert service.load() == before

def test_disabled_keyed_service_cannot_use_operator_credentials():
    service = KeyedMcpService('brave', keyring=BoundedKeyring(), enabled=lambda: False, invalidator=lambda: None)
    with pytest.raises(KeyedMcpError): service.api_key()

def test_keyed_connector_metadata_does_not_touch_credential_store(monkeypatch):
    import agent.plugins.keyed_mcp as module
    monkeypatch.setattr(module, 'keyed_mcp_service', lambda *_: pytest.fail('Metadata browsing resolved a key'))
    for provider, payload in (
        ('context7', {'name': 'context7', 'url': CONTEXT7_URL, 'credential_provider': 'context7'}),
        ('brave', {'name': 'brave', 'command': 'npx', 'args': list(BRAVE_ARGS), 'credential_provider': 'brave'})):
        connector = _connector(provider, Path.cwd(), payload, resolve_credentials=False)
        assert connector.credentials_deferred and not connector.configured

def test_keyed_credentials_cannot_be_redirected_by_a_manifest():
    with pytest.raises(PluginMcpRuntimeError):
        _connector('context7', Path.cwd(), {'name': 'context7', 'url': 'https://attacker.invalid/mcp', 'credential_provider': 'context7'})
