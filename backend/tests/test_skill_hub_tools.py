import json

from agent.skills import HubSkillMeta, SkillHub, TapsManager
from agent.tools import skill_hub as hub_tools

from test_skill_hub import FakeSource, SAFE


class SearchableSource(FakeSource):
    def search(self, query: str, limit: int = 10):
        return [HubSkillMeta("remote-skill", "Remote skill", "url", "https://example.com/SKILL.md")]


def test_hub_search_inspect_and_audit(tmp_path) -> None:
    hub = SkillHub(tmp_path, sources=[SearchableSource(SAFE)])

    results = hub.search("remote")
    inspected = hub.inspect("https://example.com/SKILL.md")
    hub.install("https://example.com/SKILL.md", confirm=True)
    audit = hub.audit("remote-skill")

    assert results[0]["name"] == "remote-skill"
    assert inspected["files"] == ["SKILL.md", "references/guide.md"]
    assert "Remote Skill" in inspected["skill_md"]
    assert audit["verdict"] == "safe"


def test_taps_manager_adds_lists_and_removes_confirmed_repositories(tmp_path) -> None:
    taps = TapsManager(tmp_path)

    taps.add("acme/skills", path="team/skills/", confirm=True)
    assert taps.list() == [{"repo": "acme/skills", "path": "team/skills/"}]

    taps.remove("acme/skills", confirm=True)
    assert taps.list() == []


def test_skill_hub_tool_routes_read_and_confirmed_mutation_actions(tmp_path, monkeypatch) -> None:
    hub = SkillHub(tmp_path, sources=[SearchableSource(SAFE)])
    monkeypatch.setattr(hub_tools, "_HUB", hub)
    monkeypatch.setattr(hub_tools, "_TAPS", TapsManager(tmp_path))

    searched = json.loads(hub_tools.skill_hub.invoke({"action": "search", "query": "remote"}))
    blocked = json.loads(
        hub_tools.skill_hub.invoke({"action": "install", "identifier": "https://example.com/SKILL.md"})
    )
    installed = json.loads(
        hub_tools.skill_hub.invoke(
            {"action": "install", "identifier": "https://example.com/SKILL.md", "confirm": True}
        )
    )

    assert searched["results"][0]["name"] == "remote-skill"
    assert blocked["ok"] is False
    assert installed["ok"] is True
