import json
from pathlib import Path

import pytest

from agent.skills import HubSkillBundle, HubSkillMeta, SkillHub, SkillHubError


class FakeSource:
    source_id = "url"

    def __init__(self, body: str):
        self.body = body

    def fetch(self, identifier: str) -> HubSkillBundle:
        return HubSkillBundle(
            name="remote-skill",
            description="Remote skill",
            source="url",
            identifier=identifier,
            trust_level="community",
            files={
                "SKILL.md": self.body,
                "references/guide.md": "Guide",
            },
            metadata={"repository_url": "https://github.com/acme/skills"},
        )


SAFE = """---
name: remote-skill
description: Remote skill
---
# Remote Skill

## Procedure
Use verified inputs.
"""


def test_hub_installs_quarantined_bundle_and_records_provenance(tmp_path: Path) -> None:
    hub = SkillHub(tmp_path, sources=[FakeSource(SAFE)])

    result = hub.install("https://example.com/SKILL.md", category="remote", confirm=True)

    target = tmp_path / "packages" / "remote" / "remote-skill"
    assert result["name"] == "remote-skill"
    assert (target / "SKILL.md").exists()
    assert (target / "references" / "guide.md").read_text(encoding="utf-8") == "Guide"
    lock = json.loads((tmp_path / ".hub" / "lock.json").read_text(encoding="utf-8"))
    assert lock["skills"]["remote-skill"]["identifier"] == "https://example.com/SKILL.md"
    assert lock["skills"]["remote-skill"]["trust_level"] == "community"
    assert lock["skills"]["remote-skill"]["content_hash"] == result["content_hash"]


def test_hub_inspection_exposes_cli_and_agent_install_prompt(tmp_path: Path) -> None:
    detail = SkillHub(tmp_path, sources=[FakeSource(SAFE)]).inspect("https://example.com/SKILL.md")

    assert detail["install_cli"] == "npx skills add https://github.com/acme/skills --skill remote-skill"
    assert 'Review and install the "remote-skill" skill' in detail["prompt"]


def test_hub_requires_confirmation_and_force_for_community_caution(tmp_path: Path) -> None:
    caution = SAFE.replace("Use verified inputs.", "Run os.system(command).")
    hub = SkillHub(tmp_path, sources=[FakeSource(caution)])

    with pytest.raises(SkillHubError, match="confirmation"):
        hub.install("https://example.com/SKILL.md")
    with pytest.raises(SkillHubError, match="requires force"):
        hub.install("https://example.com/SKILL.md", confirm=True)

    installed = hub.install("https://example.com/SKILL.md", confirm=True, force=True)
    assert installed["scan_verdict"] == "caution"


def test_hub_check_update_and_uninstall_are_hash_based(tmp_path: Path) -> None:
    source = FakeSource(SAFE)
    hub = SkillHub(tmp_path, sources=[source])
    hub.install("https://example.com/SKILL.md", confirm=True)

    assert hub.check("remote-skill")["status"] == "current"

    source.body = SAFE.replace("Use verified inputs.", "Use updated verified inputs.")
    assert hub.check("remote-skill")["status"] == "update_available"

    updated = hub.update("remote-skill", confirm=True)
    assert updated["name"] == "remote-skill"
    assert "updated verified" in (tmp_path / "packages" / "uncategorized" / "remote-skill" / "SKILL.md").read_text(encoding="utf-8")

    hub.uninstall("remote-skill", confirm=True)
    assert not (tmp_path / "packages" / "uncategorized" / "remote-skill").exists()
    assert hub.list_installed() == []


def test_hub_rejects_unsafe_bundle_paths_before_writing(tmp_path: Path) -> None:
    source = FakeSource(SAFE)
    original = source.fetch

    def unsafe(identifier: str) -> HubSkillBundle:
        bundle = original(identifier)
        bundle.files["../escape.md"] = "blocked"
        return bundle

    source.fetch = unsafe

    with pytest.raises(SkillHubError, match="unsafe bundle path"):
        SkillHub(tmp_path, sources=[source]).install("https://example.com/SKILL.md", confirm=True)

    assert not (tmp_path.parent / "escape.md").exists()


def test_discovery_key_deduplicates_same_github_package_across_indexes() -> None:
    from_skillssh = {"source": "skills-sh", "identifier": "skills-sh/anthropics/skills/frontend-design"}
    from_skillsmp = {"source": "skillsmp", "identifier": "skillsmp/github/anthropics/skills/main/skills/frontend-design"}

    assert SkillHub._discovery_key(from_skillssh) == SkillHub._discovery_key(from_skillsmp)


class SearchSource:
    searchable = True

    def __init__(self, source_id: str, names: list[str], *, fails: bool = False):
        self.source_id = source_id
        self.names = names
        self.fails = fails

    def search(self, query: str, limit: int = 10):
        if self.fails:
            raise ValueError("source unavailable")
        return [
            HubSkillMeta(name, f"{name} description", self.source_id, f"{self.source_id}/{name}")
            for name in self.names
            if not query or query.casefold() in name.casefold()
        ][:limit]


def test_all_sources_merges_available_results_and_keeps_partial_health(tmp_path: Path) -> None:
    hub = SkillHub(
        tmp_path,
        sources=[
            SearchSource("first", ["frontend-one"]),
            SearchSource("broken", [], fails=True),
            SearchSource("second", ["frontend-two"]),
        ],
    )

    results = hub.search("frontend", source_filter="all", limit=10)

    assert {(item["source"], item["name"]) for item in results} == {
        ("first", "frontend-one"),
        ("second", "frontend-two"),
    }
    assert hub.last_search_health["broken"]["status"] == "error"
    assert hub.search("frontend", source_filter=None, limit=10) == results
