import base64
import io
import zipfile

import pytest
from pydantic import ValidationError

from agent.contracts.plugin_setup import PluginSetup, MarketplaceSetup
from agent.plugins.registry import PluginRegistry
from agent.mcp.plugin_runtime import PluginMcpRuntime


def registry(tmp_path):
    return PluginRegistry(tmp_path/'plugins',state_path=tmp_path/'state.json')


def test_custom_mcp_uses_existing_registry_and_lazy_runtime(tmp_path):
    owner=registry(tmp_path)
    result=owner.add(PluginSetup(kind='mcp',name='Example',url='https://example.com/mcp'))
    assert result['id']=='custom-example'
    assert owner.contains('custom-example')
    connectors=PluginMcpRuntime(owner).connectors()
    assert len(connectors)==1 and connectors[0].url=='https://example.com/mcp'
    with pytest.raises(ValueError,match='unique'):
        owner.add(PluginSetup(name='Example'))


@pytest.mark.parametrize('url',['file:///tmp/test','http://example.com/mcp','https://user:secret@example.com/mcp','https://example.com/mcp?token=secret'])
def test_mcp_endpoint_requires_safe_configuration(url):
    with pytest.raises(ValidationError):PluginSetup(kind='mcp',name='Test',url=url)


def test_mcp_auth_configuration_accepts_references_and_rejects_embedded_secrets():
    value=PluginSetup(kind='mcp',name='Test',url='https://example.com/mcp',headers={'Authorization':'${MY_AUTH_HEADER}'})
    assert value.headers['Authorization']=='${MY_AUTH_HEADER}'
    with pytest.raises(ValidationError):
        PluginSetup(kind='mcp',name='Test',url='https://example.com/mcp',env={'TOKEN':'secret-value'},headers={'TOKEN':'${TOKEN}'})


def test_marketplace_rejects_paths_outside_repository():
    for path in ('../secrets','/absolute','C:/private'):
        with pytest.raises(ValidationError):MarketplaceSetup(repo='owner/repo',path=path)


def archive(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as target:
        for name,content in files.items():target.writestr(name,content)
    return base64.b64encode(stream.getvalue()).decode('ascii')


def test_archive_never_publishes_uploaded_executable_code(tmp_path):
    owner=registry(tmp_path)
    result=owner.add(PluginSetup(kind='archive',name='Upload',archive_b64=archive({
        'plugin.yaml':'id: uploaded\nname: Uploaded\ntype: bundle\ncategory: Personal\n',
        '__init__.py':'raise RuntimeError("do not execute uploaded code")',
    })))
    assert result['id']=='custom-upload'
    assert 'RuntimeError' not in (tmp_path/'plugins/custom/custom-upload/__init__.py').read_text()


def test_archive_blocks_traversal_and_does_not_publish_partial_plugin(tmp_path):
    owner=registry(tmp_path)
    with pytest.raises(ValueError,match='unsafe'):
        owner.add(PluginSetup(kind='archive',name='Bad',archive_b64=archive({'../escape.txt':'bad'})))
    assert not owner.contains('custom-bad')


def test_marketplace_search_uses_existing_taps_owner(tmp_path):
    from agent.skills.hub import TapsManager
    from agent.skills.hub_sources import RegisteredMarketplaceSource
    TapsManager(tmp_path).add('owner/repo',confirm=True)
    class HTTP:
        def get_json(self,url):
            assert url=='https://api.github.com/repos/owner/repo/contents/skills/'
            return [{'type':'dir','name':'write','path':'skills/write'}]
    source=RegisteredMarketplaceSource(tmp_path,HTTP())
    assert source.search('write')[0].identifier=='github/owner/repo/skills/write'


def test_setup_requires_bound_confirmation_before_writing(tmp_path):
    from agent.app_actions.lifecycle_controls import PluginSkillActionService, LifecycleControlError
    from agent.app_actions.models import AppActionContext
    owner=registry(tmp_path)
    service=PluginSkillActionService(plugin_registry=owner,skill_surface_provider=lambda:None,
        skill_hub_handler=lambda args:{},uninstall_handler=lambda name:{})
    context=AppActionContext(source='ui')
    args={'kind':'mcp','name':'Example','url':'https://example.com/mcp'}
    with pytest.raises(LifecycleControlError,match='Review'):
        service.execute('plugin.add',args,context)
    assert not owner.contains('custom-example')
    applied=service.execute('plugin.add',args,context,confirmed=True)
    assert applied['plugin']['id']=='custom-example'
