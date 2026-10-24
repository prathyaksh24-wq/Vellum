"""Catalog construction must not reread every manifest for each owned skill."""
from pathlib import Path
import json

from agent.plugins import registry as module
from agent.plugins.registry import PluginRegistry
from agent.plugins.sources import PluginSourceRecord


def test_catalog_reads_one_manifest_snapshot_and_observes_next_request_changes(tmp_path, monkeypatch):
    plugin=tmp_path/"plugins"/"native"
    plugin.mkdir(parents=True)
    manifest=plugin/"plugin.yaml"
    manifest.write_text("id: native\nname: Native\ntype: connector\ncategory: Connectors\nversion: 1.0.0\n",encoding="utf-8")
    owned=tmp_path/"owned"
    for number in range(20):
        root=owned/str(number);root.mkdir(parents=True)
        (root/"SKILL.md").write_text(f"---\nname: skill-{number}\ndescription: Test skill\n---\n",encoding="utf-8")
    class Source:
        def discover(self):return [PluginSourceRecord(id="bundle",name="Bundle",version="1",description="Skills",category="Engineering",developer="Test",source="external",root=owned,skills_root=owned)]
    calls=[]
    original=module.discover_portable_plugins
    def discover(root):
        calls.append(root)
        return original(root)
    monkeypatch.setattr(module,"discover_portable_plugins",discover)
    registry=PluginRegistry(tmp_path/"plugins",state_path=tmp_path/"state.json",sources=[Source()])
    result=registry.catalog()
    assert len(next(item for item in result if item['id']=='bundle')['skills'])==20
    assert len(calls)==1, "Catalog construction repeatedly scans/parses all plugin manifests."
    manifest.write_text(manifest.read_text().replace('Native','Updated native'),encoding="utf-8")
    calls.clear()
    result=registry.catalog()
    assert next(item for item in result if item['id']=='native')['name']=='Updated native'
    assert len(calls)==1
    registry.set_enabled('bundle',False)
    assert next(item for item in registry.catalog() if item['id']=='bundle')['enabled'] is False


def test_catalog_agent_reach_status_never_starts_cli_or_claims_live_auth(monkeypatch):
    from agent.plugins import agent_reach
    monkeypatch.setattr(agent_reach.shutil,"which",lambda command:command)
    def forbid(*args,**kwargs):
        raise AssertionError("Browsing the catalog must not spawn a health-check process.")
    monkeypatch.setattr(agent_reach,"_run_health",forbid)
    value=agent_reach.agent_reach_plugin_status(probe=False,twitter_env={"TWITTER_AUTH_TOKEN":"test-auth","TWITTER_CT0":"test-csrf"})
    assert value.configured and value.status=='not_checked'
    assert 'test-auth' not in json.dumps(value.model_dump())


def test_linear_connection_status_does_not_probe_the_remote_mcp_server(tmp_path,monkeypatch):
    from agent.plugins import linear_mcp
    from agent.plugins.linear import LinearService
    class EmptyKeyring:
        def get_password(self,*args):return None
    def forbid():
        raise AssertionError("Connection metadata must not contact the remote MCP server.")
    monkeypatch.setattr(linear_mcp.LinearMcpAdapter,"catalog",forbid)
    value=LinearService(keyring=EmptyKeyring(),enabled=lambda:True).status()
    assert value.mcp_tool_count==68 and not value.connected
