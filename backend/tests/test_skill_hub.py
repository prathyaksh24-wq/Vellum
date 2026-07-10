import json
from pathlib import Path

import pytest

from agent.skills import HubSkillBundle, SkillHub, SkillHubError


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
