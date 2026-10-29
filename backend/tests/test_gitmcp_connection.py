"""GitMCP availability, enablement, and public-reader classification."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.mcp import gitmcp_tools
from agent.mcp.audit import McpAuditLog
from agent.mcp.plugin_runtime import PluginMcpConnector, PluginMcpRuntime
from agent.plugins.registry import PluginRegistry


def test_disabled_adapter_does_not_contact_upstream(monkeypatch):
    monkeypatch.setattr('agent.plugins.registry.get_plugin_registry',
                        lambda: SimpleNamespace(is_enabled=lambda plugin_id: False))
    def forbidden(*args, **kwargs):
        raise AssertionError('Disabled GitMCP must not open a session')
    monkeypatch.setattr(gitmcp_tools, 'streamablehttp_client', forbidden)
    result = asyncio.run(gitmcp_tools.run_tool_async({'action': 'match', 'library': 'langgraph'}))
    assert 'disabled' in result


@pytest.mark.parametrize('url,expected', [('https://gitmcp.io/docs', True),
                                         ('https://example.com/mcp', False)])
def test_only_known_readers_on_official_endpoint_are_promoted(tmp_path, url, expected):
    class Transport:
        async def list_tools(self, connector):
            return [{'name': 'fetch_generic_documentation', 'read_only': False},
                    {'name': 'unknown_future_tool', 'read_only': False}]
    runtime = PluginMcpRuntime(PluginRegistry(tmp_path/'plugins',state_path=tmp_path/'state.json'),
                               transport=Transport(),audit_log=McpAuditLog(tmp_path/'audit.jsonl'))
    connector = PluginMcpConnector(plugin_id='gitmcp',name='gitmcp',root=Path(tmp_path),
                                   transport='http',url=url)
    result = asyncio.run(runtime._list_tools(connector))
    assert result[0]['read_only'] is expected
    assert result[1]['read_only'] is False


def test_public_metadata_does_not_claim_live_connection():
    status = gitmcp_tools.plugin_status()
    assert status['metadata']['connection']['anonymous'] is True
    assert status['metadata']['connection']['connected'] is False
