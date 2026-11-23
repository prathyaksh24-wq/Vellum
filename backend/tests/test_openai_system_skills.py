"""System bundles must reach real runtime instructions and existing owners."""
from pathlib import Path
import json

from langchain_core.messages import HumanMessage
from agent.skills.registry import SkillRegistry
from agent.skills.runtime import build_skill_activation_block, build_skill_index_block
from agent.plugins.registry import PluginRegistry
from agent.tools import plugin_mcp as tools


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / 'plugins' / 'system' / 'openai-system-skills'


def test_bundle_has_exact_requested_skills_and_loadable_references():
    registry = SkillRegistry(local_root=BUNDLE / 'skills')
    assert {row.name for row in registry.list_skills()} == {'imagegen', 'plugin-creator', 'skill-creator', 'skill-installer'}
    assert not registry.diagnostics()
    for package in registry.list_packages():
        assert registry.view_file(package.metadata.name, 'references/upstream-skill.md')
        assert package.metadata.metadata.provenance['source_ref'] == '49f948faa9258a0c61caceaf225e179651397431'


def test_matching_skill_loads_body_and_unrelated_question_keeps_it_unloaded(monkeypatch):
    from agent.skills import usage_intelligence
    activated = []
    monkeypatch.setattr(usage_intelligence, 'record_current_activation', lambda name, **kwargs: activated.append(name))
    registry = SkillRegistry(local_root=BUNDLE / 'skills')
    body = build_skill_activation_block('Create a skill for preparing weekly reports', registry)
    assert '### skill-creator' in body and 'skill_manage' in body
    assert activated == ['skill-creator']
    assert build_skill_activation_block('What skills are installed?', registry) == ''
    assert 'skill-installer' in build_skill_index_block(registry)


def test_bundle_disable_removes_skills_from_discovery(tmp_path):
    plugins = PluginRegistry(ROOT / 'plugins', state_path=tmp_path / 'state.json')
    assert BUNDLE / 'skills' in plugins.skill_roots()
    plugins.set_enabled('openai-system-skills', False)
    assert BUNDLE / 'skills' not in plugins.skill_roots()


def test_explicit_plugin_creator_reference_loads_the_matching_installed_skill(tmp_path):
    owner = 'openai-system-skills'
    registry = SkillRegistry(local_root=tmp_path, owned_external_dirs={BUNDLE / 'skills': owner})
    query = 'I need an integration for tracking invoices.'
    assert not build_skill_activation_block(query, registry, selected_skills={'plugin-creator': 'different-owner'})
    body = build_skill_activation_block(query, registry, selected_skills={'plugin-creator': owner})
    assert '### plugin-creator' in body and 'plugin.add' in body


def test_selected_plugin_exposes_only_its_discovery_bridges(monkeypatch, tmp_path):
    plugins = PluginRegistry(ROOT / 'plugins', state_path=tmp_path / 'state.json')
    monkeypatch.setattr(tools, 'get_plugin_registry', lambda: plugins)
    reference = {'kind': 'plugin', 'id': 'district', 'owner_plugin_id': 'district', 'label': 'District'}
    messages = [HumanMessage(content=[{'type': 'text', 'text': 'What movies release this week?'},
        {'type': 'vellum_attachment_text', 'text': 'User-selected reference metadata (contents not fetched):\n' + json.dumps(reference)}])]
    requested, names = tools.plugin_route_names('What movies release this week?', messages,
        {'district_mcp_catalog', 'district_mcp_describe', 'district_mcp_read', 'slack_mcp_catalog', 'district_tool_search_movies'})
    assert [row['id'] for row in requested] == ['district']
    assert names == ['district_mcp_catalog', 'district_mcp_describe', 'district_mcp_read']
    assert tools.explicit_plugin_web_error('What movies release this week?', messages, {'name': 'tool_call', 'args': {'name': 'web_search'}})
    assert tools.explicit_plugin_web_error('Also search the web', messages, {'name': 'web_search'}) is None


def test_image_tool_prepares_review_instead_of_calling_provider(monkeypatch):
    from types import SimpleNamespace
    from agent.tools import app_actions
    from agent.tools.images import image_generate
    calls = []
    monkeypatch.setattr(app_actions, 'app_action', SimpleNamespace(invoke=lambda request: calls.append(request) or 'review pending'))
    assert image_generate.invoke({'action': 'generate', 'prompt': 'An ink drawing of a mountain'}) == 'review pending'
    assert calls[0]['action_id'] == 'image.generate'
    assert 'confirm' not in calls[0]['arguments']


def test_main_agent_mode_never_preloads_a_skill_from_keywords(tmp_path):
    """The model chooses skills itself (ADR 0009); only a user's selection is preloaded."""
    owner = 'openai-system-skills'
    registry = SkillRegistry(local_root=tmp_path, owned_external_dirs={BUNDLE / 'skills': owner})
    query = 'Create and install a skill that summarizes articles'
    assert build_skill_activation_block(query, registry, selected_skills={}, match_query=False) == ''
    body = build_skill_activation_block(query, registry, selected_skills={'skill-creator': owner}, match_query=False)
    assert '### skill-creator' in body and '### skill-installer' not in body


def test_a_skill_the_user_names_as_a_skill_is_selected(tmp_path):
    from agent.skills.runtime import skills_named_in
    owner = 'openai-system-skills'
    registry = SkillRegistry(local_root=tmp_path, owned_external_dirs={BUNDLE / 'skills': owner})
    assert skills_named_in('Use my skill-creator skill to draft one', registry) == {'skill-creator': owner}
    assert skills_named_in('run /imagegen for a logo', registry) == {'imagegen': owner}
    assert skills_named_in('use the skill `plugin-creator`', registry) == {'plugin-creator': owner}
    # A bare word that equals a skill name is not a choice; nor is a longer name.
    assert skills_named_in('generate an imagegen-style logo', registry) == {}
    assert skills_named_in('Create a skill that summarizes articles', registry) == {}
    assert skills_named_in('use my skill-creator', registry) == {}
    assert skills_named_in('the skill-creator skill', registry, excluded_skills={'skill-creator'}) == {}
