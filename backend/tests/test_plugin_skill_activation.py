from pathlib import Path

from agent.skills.registry import SkillRegistry


def test_explicit_plugin_route_precedes_unrelated_specialist_keywords(monkeypatch):
    from agent import api
    from agent.tools import plugin_mcp
    calls=[]
    def requested(message,*,references):
        calls.append((message,references))
        return [{'id':'district','tools':['district_mcp_catalog'],'enabled':True}]
    monkeypatch.setattr(plugin_mcp,'requested_plugins',requested)
    attachment=api.ChatAttachment(kind='reference',name='District',reference={'kind':'plugin','id':'district','owner_plugin_id':'district','label':'District'})
    assert api._main_plugin_request('What movies are playing this week?',[attachment])
    assert calls[0][1][0]['id']=='district'
    monkeypatch.setattr(plugin_mcp,'requested_plugins',lambda *args,**kwargs:[{'id':'spotify','tools':['spotify_search']}])
    assert not api._main_plugin_request('Play a song',[])


def test_owned_external_skill_reports_plugin_owner(tmp_path: Path):
    local = tmp_path / "local"
    plugin_skills = tmp_path / "plugin-skills"
    package = plugin_skills / "demo"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Plugin skill\n---\n# Demo\n",
        encoding="utf-8",
    )

    registry = SkillRegistry(
        local_root=local,
        owned_external_dirs={plugin_skills: "demo-plugin"},
    )

    entry = registry.list_skills()[0]
    assert entry.owner_plugin == "demo-plugin"
    assert registry.view("demo").owner_plugin == "demo-plugin"
